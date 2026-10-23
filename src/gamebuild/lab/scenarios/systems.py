"""Measured local cache/DAG, authority leases, process trees and network policies."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import sys
import threading
import time
import uuid
import zlib

from gamebuild.cache import ContentCache
from gamebuild.runner import run_process
from gamebuild.store import Store, Conflict
from gamebuild.artifacts import make_package
from gamebuild.diagnostics import probe_network
from .common import evidence, sha, state, loopback, http, store_handler


GOOD = {
    '07': {'include_dependency':True,'corrupt':False,'force_cold':False},
    '08': {'parallel':True,'package_after_export':True},
    '09': {'capabilities':['lab'],'slots':2,'backup':True},
    '10': {'hang':False},
    '11': {'editor':'2022.3.62f1','sdk':['lab-sdk'],'license':'valid-fixture','required_bytes':4096},
    '12': {'dns_policy':'system-loopback','tcp_listening':True,'http_status':200},
    '16': {'nodes':{'windows':['lab','sdk:windows'],'android':['lab','sdk:android'],'ios':['lab','sdk:ios']},
           'routes':{'windows':'windows','android':'android','ios':'ios'}},
}


def prepare(ctx):
    ctx.write('system-policy.json',GOOD[ctx.case_id])
    if ctx.case_id=='07':
        ctx.write('resource.txt','texture input'*1000);ctx.write('dependency.txt','importer-v1')
    elif ctx.case_id=='08':
        ctx.write('workload.bin',bytes(range(256))*8192)
    elif ctx.case_id=='10':
        ctx.write('process.py',PROCESS_PROGRAM)
    elif ctx.case_id=='09':
        from .builds import APP
        ctx.write('project/app.py',APP)
        ctx.write('project/config.json',{'mode':'Development','asset':'texture.txt'})
        ctx.write('project/texture.txt','texture:node task')
        ctx.write('build-policy.json',{'required_tests':True,'runtime_gate':True})
    ctx.commit('Local system experiment baseline')


def inject(ctx):
    p=ctx.read('system-policy.json');v=ctx.variant;c=ctx.case_id
    if c=='07': p[{'dependency':'include_dependency','corruption':'corrupt','repeat':'force_cold'}[v]]=v!='dependency'
    elif c=='08': p['parallel' if v=='serial' else 'package_after_export']=False
    elif c=='09':
        if v=='capability': p['capabilities']=['validate']
        elif v=='busy': p['slots']=1
        else: p['backup']=False
    elif c=='10': p['hang']=True
    elif c=='11':
        if v=='editor':p['editor']='2021.3.1f1'
        elif v=='sdk':p['sdk']=[]
        else:p['license']='expired-fixture';p['required_bytes']=10**19
    elif c=='12': p[{'dns':'dns_policy','tcp':'tcp_listening','http':'http_status'}[v]]={'dns':'injected-resolution-failure','tcp':False,'http':403}[v]
    else:
        if v=='sdk':p['nodes']['android']=['lab'];p['nodes']['ios']=['lab']
        else:p['routes']['android']='windows';p['routes']['ios']='android'
    ctx.write('system-policy.json',p);ctx.commit('Inject local system fault')


def repair(ctx):
    ctx.write('system-policy.json',GOOD[ctx.case_id]);ctx.commit('Repair local system policy')


def execute(ctx):
    return {'07':cache,'08':dag,'09':queue,'10':process_tree,'11':environment,'12':network,'16':matrix}[ctx.case_id](ctx)


def cache(ctx):
    p=ctx.read('system-policy.json');cache=ContentCache(ctx.output/'cache');rows=[]
    source=ctx.repo/'resource.txt';dependency=ctx.repo/'dependency.txt'
    # Restore per-action baseline; dependency changes in subsequent rounds are real files.
    ctx.write('dependency.txt','importer-v1')
    def roundtrip(name, poison=False):
        start=time.monotonic()
        inputs={'resource':source,'version':1}
        if p['include_dependency']:inputs['importer']=dependency
        key=cache.key(inputs);target=ctx.output/(name+'.bin')
        if p['force_cold']:
            key=cache.key({**inputs,'cold_round':name})
        if poison and (cache.root/key/'data').exists(): (cache.root/key/'data').write_bytes(b'corrupted cache bytes')
        hit=cache.get(key,target)
        expected=zlib.compress(source.read_bytes()+dependency.read_bytes())
        processed=0 if hit else 2
        if not hit:
            target.write_bytes(expected);cache.put(key,target)
        row=dict(round=name,key=key,hit=hit,processed_files=processed,expected_sha256=sha(expected),actual_sha256=sha(target.read_bytes()),duration_ms=round((time.monotonic()-start)*1000,3))
        rows.append(row);ctx.record('资源导入','INFO',name,**row)
        return row
    cold=roundtrip('cold');warm=roundtrip('warm')
    ctx.write('dependency.txt','importer-v2')
    changed=roundtrip('dependency-changed')
    integrity=roundtrip('integrity',poison=p['corrupt'])
    quarantine=list((cache.root/'quarantine').glob('*')) if (cache.root/'quarantine').exists() else []
    facts=evidence(ctx,'cache-report.json',dict(policy=p,rounds=rows,quarantine=[x.name for x in quarantine],quarantined_count=len(quarantine)))
    return ctx.result('缓存命中、依赖失效与污染隔离',[
        ctx.check('重复输入实际命中缓存',warm['hit'],True,warm['hit']),
        ctx.check('依赖改变使 key 失效',changed['key']!=warm['key'],True,changed['key']!=warm['key']),
        ctx.check('所有产物匹配当前实际输入',all(r['expected_sha256']==r['actual_sha256'] for r in rows),True,rows),
        ctx.check('缓存无损坏条目',not quarantine,0,len(quarantine)),
        ctx.check('污染未进入产物',integrity['expected_sha256']==integrity['actual_sha256'],integrity['expected_sha256'],integrity['actual_sha256'])],**facts)


def dag(ctx):
    p=ctx.read('system-policy.json');data=(ctx.repo/'workload.bin').read_bytes();serial=[];candidate=[]
    def work(name,rows):
        if ctx.cancelled():raise InterruptedError('experiment cancelled')
        start=time.monotonic()
        output=data
        if name=='check':
            for _ in range(70):output=hashlib.sha256(data+output[:64]).digest()
        else:
            for _ in range(8):output=zlib.compress(data,6)
        row=dict(stage=name,start=start,end=time.monotonic(),sha256=sha(output));rows.append(row)
        ctx.record('DAG 阶段','INFO',name,measurement=row)
        return output
    begin=time.monotonic();serial_outputs=[work(name,serial) for name in ('check','export')];serial_seconds=time.monotonic()-begin
    begin=time.monotonic()
    premature_start=None
    premature_content=None
    if not p['package_after_export']:
        # Actual consumer execution before its producer: the export path is absent.
        premature_start=time.monotonic()
        export_path=ctx.output/'export.bin'
        export_path.unlink(missing_ok=True)
        premature_content=export_path.read_bytes() if export_path.exists() else b''
    if p['parallel']:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(work,name,candidate) for name in ('check','export')]
            outputs=[future.result() for future in futures]
    else:outputs=[work(name,candidate) for name in ('check','export')]
    export_end=next(row['end'] for row in candidate if row['stage']=='export')
    (ctx.output/'export.bin').write_bytes(outputs[1])
    package_start=time.monotonic() if premature_start is None else premature_start
    package_content=outputs[1] if p['package_after_export'] else premature_content
    packed=zlib.compress(package_content)
    (ctx.output/'package.bin').write_bytes(packed)
    candidate.append(dict(stage='package',start=package_start,end=time.monotonic(),sha256=sha(packed)))
    loaded=zlib.decompress(packed)
    candidate.append(dict(stage='startup',start=time.monotonic(),end=time.monotonic(),sha256=sha(loaded)))
    elapsed=time.monotonic()-begin
    independent=[row for row in candidate if row['stage'] in ('check','export')]
    overlap=max(0,min(r['end'] for r in independent)-max(r['start'] for r in independent))
    facts=evidence(ctx,'dag-report.json',dict(policy=p,serial=serial,candidate=candidate,serial_seconds=serial_seconds,
        candidate_seconds=elapsed,measured_ratio=serial_seconds/elapsed,overlap_seconds=overlap,
        dependency_edges=[['export','package'],['package','startup']],critical_path_seconds=max(r['end'] for r in candidate)-begin,
        expected_payload_sha256=sha(serial_outputs[1]),actual_payload_sha256=sha(loaded)))
    return ctx.result('实测串行与依赖 DAG',[
        ctx.check('独立任务并行重叠',overlap>0,'>0',overlap),
        ctx.check('打包发生在导出后',package_start>=export_end,True,package_start>=export_end),
        ctx.check('产物逻辑内容一致',loaded==serial_outputs[1],sha(serial_outputs[1]),sha(loaded))],**facts)


def _request(ctx):
    return dict(project_id='lab',adapter='lab',target='generic',branch='main',commit_sha=ctx.git('rev-parse','HEAD'),input_digest=sha((ctx.repo/'system-policy.json').read_bytes()))


def _wait(ctx,seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if ctx.cancelled():raise InterruptedError('experiment cancelled')
        time.sleep(min(.02,max(0,deadline-time.monotonic())))


def queue(ctx):
    from ..bridge import control, claim, work, request, download
    p=ctx.read('system-policy.json');claims=[];stale=None;old=None;artifact=None;worker_result=None
    with control(ctx) as (client,connection):
        def post(path,body):
            response=client.post(path,json=body);response.raise_for_status();return response.json()
        def observed(value):
            item=value['claim']
            if item: claims.append({'worker':item['worker'],'job_id':item['job_id'],'attempt':item['attempt'],
                                    'token_sha256':sha(item['token']),'pid':value['pid']})
            return item
        req=request(ctx)
        if ctx.variant=='busy':
            post('/v1/jobs',{'request':req,'key':'busy-blocker'})
            old=observed(claim(ctx,connection,'primary',p['capabilities'],p['slots'],name='blocking-node'))
        target=post('/v1/jobs',{'request':req,'key':'target'})
        repeated=post('/v1/jobs',{'request':req,'key':'target'})
        # Negative matching and disappearing-owner probes execute in independent HTTP node processes.
        should_work=('lab' in p['capabilities'] and (ctx.variant!='busy' or p['slots']>1) and (ctx.variant!='lease' or p['backup']))
        claimed=None
        if not should_work or ctx.variant=='lease':
            probe=claim(ctx,connection,'primary',p['capabilities'],p['slots'],
                        lease_seconds=1 if ctx.variant=='lease' else 30,name='primary-probe')
            claimed=observed(probe)
        if ctx.variant=='lease' and claimed:
            old=claimed;_wait(ctx,1.06)
            client.get('/v1/jobs/'+target['job_id']).raise_for_status()
            response=client.post('/v1/attempts/'+target['job_id']+'/report',json={'worker':'primary','token':old['token'],'state':'building'})
            stale={'status':response.status_code,'body':response.json()}
            claimed=None
        if should_work:
            receipt,worker_result=work(ctx,connection,'backup' if ctx.variant=='lease' else 'primary',slots=p['slots'])
            artifact=receipt.get('artifact')
            if artifact: worker_result['download']=download(ctx,client,artifact)
            snapshot=client.get('/v1/jobs/'+target['job_id']).json()
            claims.append({'worker':snapshot['worker'],'job_id':snapshot['job_id'],'attempt':snapshot['attempt'],
                           'pid':receipt['pid'],'token_sha256':'revoked after admission'})
        snapshot=client.get('/v1/jobs/'+target['job_id']).json()
        events=client.get('/v1/events').json()
        completed=snapshot['state']=='succeeded'
        queued_reason=None if completed else ('capability_mismatch' if 'lab' not in p['capabilities'] else 'all_slots_busy' if ctx.variant=='busy' else 'lease_expired_without_backup')
    # Never expose ownership credentials in exported task snapshots.
    if snapshot.get('token'):snapshot['token_sha256']=sha(snapshot.pop('token'))
    facts=evidence(ctx,'queue-report.json',dict(policy=p,job_id=target['job_id'],idempotent_job_id=repeated['job_id'],claims=claims,
        queue_reason=queued_reason,target=snapshot,old_report=stale,events=events,completed=completed,artifact=artifact,
        worker_result=worker_result,control_pid=connection['control_pid']))
    return ctx.result('任务能力、槽位与租约',[
        ctx.check('目标被合适节点认领并执行',completed,True,queued_reason or completed),
        ctx.check('重复提交幂等',target['job_id']==repeated['job_id'],target['job_id'],repeated['job_id']),
        ctx.check('旧代次 HTTP 回传被拒绝',ctx.variant!='lease' or bool(stale and stale['status']==409),409 if ctx.variant=='lease' else 'not applicable',stale)],**facts)


def _complete_task(ctx,store,claimed,name):
    payload=ctx.output/(name+'-payload');payload.mkdir(exist_ok=True)
    request=claimed['request']
    identity=dict(build_id=claimed['job_id'],commit_sha=request['commit_sha'],input_digest=request['input_digest'],adapter='lab')
    (payload/'build-info.json').write_text(json.dumps(identity));(payload/'asset.txt').write_text('verified queue task resource')
    program='''import hashlib,json,os
from pathlib import Path
identity=json.loads(Path("build-info.json").read_text())
asset=Path("asset.txt").read_bytes()
assert asset==b"verified queue task resource"
Path("smoke.json").write_text(json.dumps({**identity,"pid":os.getpid(),"asset_loaded":bool(asset),"asset_sha256":hashlib.sha256(asset).hexdigest()}))
Path("build-report.json").write_text(json.dumps({"adapter":"lab","result":"Succeeded"}))
print("task resource verified",flush=True)
'''
    ctx.command([sys.executable,'-c',program],cwd=payload)
    package=ctx.output/(name+'.zip');manifest=make_package(payload,package,identity)
    store.report(claimed['job_id'],claimed['worker'],claimed['token'],'verifying')
    artifact=store.commit_artifact(claimed['job_id'],claimed['worker'],claimed['token'],package,manifest)
    return artifact


PROCESS_PROGRAM = '''import json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);hang=sys.argv[2]=="hang"
if len(sys.argv)>3:
    (root/"child.pid").write_text(str(os.getpid()))
    while True:
        (root/"heartbeat.txt").write_text(str(time.time_ns()))
        time.sleep(.02)
else:
    (root/"parent.pid").write_text(str(os.getpid()))
    if hang:
        child=subprocess.Popen([sys.executable,__file__,str(root),"hang","child"])
        while True: time.sleep(.02)
    else:
        (root/"completed.json").write_text(json.dumps({"pid":os.getpid(),"result":sum(range(10000))}))
        print("fixed task completed",flush=True)
'''


def process_tree(ctx):
    p=ctx.read('system-policy.json');folder=ctx.output/'process-state';folder.mkdir(exist_ok=True)
    begin=time.monotonic();cancel=lambda:ctx.cancelled() or (p['hang'] and ctx.variant=='cancel' and time.monotonic()-begin>.55)
    run=run_process([sys.executable,str(ctx.repo/'process.py'),str(folder),'hang' if p['hang'] else 'healthy'],ctx.repo,ctx.output/'process.log',.8,cancel)
    ctx.record('进程树','INFO','真实父子进程执行结束',**run)
    if ctx.cancelled():raise InterruptedError('experiment cancelled')
    heartbeat=folder/'heartbeat.txt';before=heartbeat.read_bytes() if heartbeat.exists() else None
    _wait(ctx,.12);after=heartbeat.read_bytes() if heartbeat.exists() else None
    store=Store(ctx.output/'cancel-store');job=store.submit(_request(ctx),'old-task');store.heartbeat('node',['lab']);claim=store.claim('node');store.cancel(job['job_id'])
    with loopback(store_handler(store)) as url:
        late=http(url+'/report',dict(job_id=job['job_id'],worker='node',token=claim['token'],state='building'))
    repaired_job=None
    if not p['hang'] and (folder/'completed.json').exists():
        new=store.submit(_request(ctx),'repaired-task');new_claim=store.claim('node')
        store.report(new['job_id'],'node',new_claim['token'],'building')
        _complete_task(ctx,store,new_claim,'repaired-task')
        repaired_job=store.get(new['job_id'])
        repaired_job.pop('token',None)
    pids={name:int((folder/(name+'.pid')).read_text()) for name in ('parent','child') if (folder/(name+'.pid')).exists()}
    alive={name:_pid_alive(pid) for name,pid in pids.items()}
    completed=json.loads((folder/'completed.json').read_text()) if (folder/'completed.json').exists() else None
    facts=evidence(ctx,'process-report.json',dict(policy=p,process=run,pids=pids,pids_alive_after_reap=alive,heartbeat_before=sha(before) if before else None,
        heartbeat_after=sha(after) if after else None,heartbeat_stopped=before==after,late_report=late,
        old_job_state=store.get(job['job_id'])['state'],old_job_artifacts=[a['artifact_id'] for a in store.artifacts() if a['job']==job['job_id']],
        artifact_count=len(store.artifacts()),completed=completed,repaired_job=repaired_job))
    return ctx.result('受控进程树结束与旧结果隔离',[
        ctx.check('修复任务正常退出',run['exit_code']==0 and completed is not None,0,run['exit_code']),
        ctx.check('停止后心跳不再变化',before==after,True,before==after),
        ctx.check('父子进程已退出',not any(alive.values()) and (not p['hang'] or len(pids)==2),False,alive),
        ctx.check('迟到 HTTP 回传被拒绝',late['status']==409,409,late['status']),
        ctx.check('旧任务没有准入制品',not facts['old_job_artifacts'],0,len(facts['old_job_artifacts'])),
        ctx.check('新提交任务完成',bool(repaired_job) and repaired_job['state']=='succeeded','succeeded',repaired_job)],**facts)


def _pid_alive(pid):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            code=wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
            return code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    return True


def environment(ctx):
    p=ctx.read('system-policy.json');git=ctx.command(['git','--version']);python=ctx.command([sys.executable,'--version'])
    probe=ctx.output/'write-probe';probe.write_bytes(b'writable');writable=probe.read_bytes()==b'writable'
    free=shutil.disk_usage(ctx.root).free
    measured={'git':git['stdout'].strip(),'python':python['stdout'].strip(),'os':platform.platform(),'disk_free_bytes':free,'workspace_writable':writable}
    facts=evidence(ctx,'environment-report.json',dict(measured_host=measured,injected_fixture_policy=p,
        boundary='Editor/SDK/license are injected descriptions; no Editor or SDK was launched.'))
    return ctx.result('实测主机与注入环境策略',[
        ctx.check('本机 Git 与 Python 可执行',git['exit_code']==0 and python['exit_code']==0,True,measured),
        ctx.check('工作目录实际可写',writable,True,writable),
        ctx.check('fixture Editor 精确版本匹配',p['editor']=='2022.3.62f1','2022.3.62f1',p['editor']),
        ctx.check('fixture SDK 描述满足要求','lab-sdk' in p['sdk'],['lab-sdk'],p['sdk']),
        ctx.check('fixture 授权描述有效',p['license']=='valid-fixture','valid-fixture',p['license']),
        ctx.check('预算不超过实测磁盘',p['required_bytes']<=free,free,p['required_bytes'])],**facts)


def network(ctx):
    p=ctx.read('system-policy.json');layers=[];shared_probe=None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            raw=json.dumps({'endpoint':'local-artifact','status':p['http_status']}).encode()
            self.send_response(p['http_status']);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    with loopback(Handler) as url:
        host='127.0.0.1';port=int(url.rsplit(':',1)[1])
        start=time.monotonic()
        if p['dns_policy']=='injected-resolution-failure':
            # A controlled resolver policy, explicitly labelled, no public DNS is contacted.
            try:raise socket.gaierror(socket.EAI_NONAME,'injected loopback resolver policy')
            except socket.gaierror as exc:layers.append(dict(layer='DNS',passed=False,error=str(exc),source='injected resolver policy',duration_ms=(time.monotonic()-start)*1000))
        else:
            resolved=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
            layers.append(dict(layer='DNS',passed=bool(resolved),addresses=sorted({r[4][0] for r in resolved}),source='system loopback resolver',duration_ms=(time.monotonic()-start)*1000))
        if layers[-1]['passed']:
            # Reserve a bound, non-listening loopback port: connect must be refused without a race.
            with socket.socket() as rejected:
                rejected.bind(('127.0.0.1',0));target_port=port if p['tcp_listening'] else rejected.getsockname()[1]
                start=time.monotonic()
                try:
                    with socket.create_connection((host,target_port),timeout=.5): pass
                    layers.append(dict(layer='TCP',passed=True,port=target_port,duration_ms=(time.monotonic()-start)*1000))
                except OSError as exc:
                    layers.append(dict(layer='TCP',passed=False,port=target_port,error=str(exc),duration_ms=(time.monotonic()-start)*1000))
                shared_probe=probe_network(host,target_port,f'http://{host}:{target_port}/artifact',timeout=.8)
            if layers[-1]['passed']:
                response=http(url+'/artifact');layers.append(dict(layer='HTTP',passed=response['status']==200,**response))
    first=next((r['layer'] for r in layers if not r['passed']),None)
    facts=evidence(ctx,'network-report.json',dict(policy=p,layers=layers,shared_probe=shared_probe,first_failed_layer=first,endpoint=url,scope='loopback only'))
    return ctx.result('DNS / TCP / HTTP 分层探测',[ctx.check(row['layer']+' 层通过',row['passed'],True,row) for row in layers],**facts)


def matrix(ctx):
    p=ctx.read('system-policy.json');rows=[]
    for target in ('windows','android','ios'):
        if ctx.cancelled():raise InterruptedError('experiment cancelled')
        node=p['routes'][target];capabilities=p['nodes'].get(node,[]);required=['lab','sdk:'+target]
        missing=sorted(set(required)-set(capabilities));row=dict(target=target,node=node,capabilities=capabilities,required=required,missing=missing,status='BLOCKED' if missing else 'SUCCEEDED')
        if not missing:
            payload=ctx.output/(target+'-payload');payload.mkdir(exist_ok=True)
            run=ctx.command([sys.executable,'-c','import sys,pathlib; pathlib.Path(sys.argv[1]).write_text("generic Lab payload for "+sys.argv[2]);print(sys.argv[2])',str(payload/'content.txt'),target])
            manifest=make_package(payload,ctx.output/(target+'-generic-lab.zip'),{'target':target,'adapter':'lab'})
            row.update(process=run,manifest=manifest,package_kind='generic Lab ZIP; not APK/IPA/platform executable')
        rows.append(row);ctx.record('矩阵目标','INFO',target,target_result=row)
    facts=evidence(ctx,'matrix-report.json',dict(policy=p,targets=rows))
    return ctx.result('逐平台工具链描述与任务路由',[
        ctx.check(row['target']+' 目标具备能力并实际打包',row['status']=='SUCCEEDED','SUCCEEDED',row) for row in rows],**facts)
