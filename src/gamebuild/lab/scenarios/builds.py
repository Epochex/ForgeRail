"""Compile, package, independently launch, admit and release real Lab bytes."""
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
import zipfile

from gamebuild.artifacts import make_package, verify_package, digest
from gamebuild.store import Store, Conflict
from .common import evidence, sha, state, tree_digest

APP = '''import hashlib,json,os
from pathlib import Path
def healthy(): return 42
def main():
    root=Path(__file__).parent
    config=json.loads((root/"config.json").read_text())
    assert config["mode"] in ("Development","Release"), "unsupported runtime mode"
    asset=(root/config["asset"]).read_bytes()
    assert asset.startswith(b"texture:"), "invalid texture format"
    identity=json.loads((root/"build-info.json").read_text())
    receipt={**identity,"pid":os.getpid(),"asset_loaded":bool(asset),"asset_sha256":hashlib.sha256(asset).hexdigest()}
    (root/"smoke.json").write_text(json.dumps(receipt))
    print(json.dumps(receipt),flush=True)
if __name__=="__main__": main()
'''


def prepare(ctx):
    ctx.write('project/app.py', APP)
    ctx.write('project/config.json', {'mode':'Release' if ctx.case_id=='05' and ctx.variant=='release_gate' else 'Development','asset':'texture.txt'})
    ctx.write('project/texture.txt','texture:blue')
    ctx.write('build-policy.json', {'required_tests':True,'runtime_gate':True,'candidate_valid':True,'observations':True})
    baseline = ctx.commit('Valid executable Lab fixture')
    state(ctx,baseline_sha=baseline)


def inject(ctx):
    if ctx.case_id == '05':
        if ctx.variant=='compile': ctx.write('project/app.py',APP+'\ndef malformed(:\n')
        elif ctx.variant=='test': ctx.write('project/app.py',APP.replace('return 42','return 7'))
        else:
            p=ctx.read('build-policy.json'); p['required_tests']=False; ctx.write('build-policy.json',p)
    elif ctx.case_id == '06':
        if ctx.variant=='missing_asset':
            p=ctx.read('project/config.json');p['asset']='missing.txt';ctx.write('project/config.json',p)
        elif ctx.variant=='runtime_config':
            p=ctx.read('project/config.json');p['mode']='broken';ctx.write('project/config.json',p)
        else: ctx.write('project/app.py',APP.replace('root=Path(__file__).parent','raise RuntimeError("fixture startup crash")\n    root=Path(__file__).parent'))
    elif ctx.case_id=='13':
        ctx.write('admission-policy.json',{'mutation':ctx.variant})
    else:
        policy=ctx.read('build-policy.json');policy['observations' if ctx.variant=='gate' else 'candidate_valid']=False
        ctx.write('build-policy.json',policy)
    state(ctx,fault_sha=ctx.commit('Inject build or delivery fault'))


def repair(ctx):
    ctx.git('restore','--source='+state(ctx)['baseline_sha'],'--','project','build-policy.json')
    ctx.record('文件变更','INFO','从固定 Git 基线恢复构建输入',source_sha=state(ctx)['baseline_sha'])
    if ctx.case_id=='13': ctx.write('admission-policy.json',{'mutation':None})
    state(ctx,repair_sha=ctx.commit('Restore build gates and fixed input'))


def identity(ctx, build_id=None):
    return dict(build_id=build_id or 'lab-'+uuid.uuid4().hex[:12],commit_sha=ctx.git('rev-parse','HEAD'),
                input_digest=tree_digest(ctx.repo/'project'),adapter='lab')


def build(ctx, ident, name='package', source=None):
    source=Path(source or ctx.repo/'project')
    payload=ctx.output/(name+'-payload')
    shutil.copytree(source,payload,dirs_exist_ok=True)
    for cache in payload.rglob('__pycache__'): shutil.rmtree(cache)
    (payload/'build-info.json').write_text(json.dumps(ident),encoding='utf-8')
    compiled=ctx.command([sys.executable,'-m','py_compile',str(payload/'app.py')],allow_failure=True)
    tests=ctx.command([sys.executable,'-c','from app import healthy; assert healthy()==42; print("behavior test passed")'],cwd=payload,allow_failure=True)
    if compiled['exit_code']!=0 or tests['exit_code']!=0:
        return {'identity':ident,'compile':compiled,'test':tests,'package':None,'runtime':None,'receipt':None}
    # First ZIP proves that producing an archive and passing runtime are separate stages.
    for cache in payload.rglob('__pycache__'): shutil.rmtree(cache)
    (payload/'build-report.json').write_text(json.dumps({'result':'Succeeded','adapter':'lab'}))
    archive=ctx.output/(name+'.zip')
    manifest=make_package(payload,archive,ident)
    verify_package(archive,manifest)
    unpacked=ctx.output/(name+'-unpacked');unpacked.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z: z.extractall(unpacked)
    (unpacked/'smoke.json').unlink(missing_ok=True)
    runtime=ctx.command([sys.executable,str(unpacked/'app.py')],cwd=unpacked,allow_failure=True)
    receipt=json.loads((unpacked/'smoke.json').read_text()) if (unpacked/'smoke.json').exists() else None
    if receipt is not None:
        # The only source of smoke.json bytes is the launched runtime process.
        shutil.copyfile(unpacked/'smoke.json',payload/'smoke.json')
        manifest=make_package(payload,archive,ident)
    return dict(identity=ident,compile=compiled,test=tests,package=str(archive),manifest=manifest,
                runtime=runtime,receipt=receipt,download_directory=str(unpacked))


def execute(ctx):
    if ctx.case_id=='14': return release(ctx)
    ident=identity(ctx)
    if ctx.case_id=='05':
        from ..bridge import build_flow
        result=build_flow(ctx)
        ident=result['identity']
    else:
        result=build(ctx,ident)
    checks=[ctx.check('源码编译通过',result['compile']['exit_code']==0,0,result['compile']['exit_code']),
            ctx.check('行为测试通过',result['test']['exit_code']==0,0,result['test']['exit_code'])]
    if ctx.case_id=='05':
        configuration=ctx.read('project/config.json')['mode'];policy=ctx.read('build-policy.json')
        checks.append(ctx.check('Release 必需测试与运行门禁',configuration!='Release' or (policy['required_tests'] and policy['runtime_gate']),True,policy))
        checks.append(ctx.check('HTTP Worker 制品准入完成',result['http_job']['state']=='succeeded','succeeded',result['http_job']['state']))
    if result['runtime'] is not None:
        checks += [ctx.check('打包后独立启动进程退出成功',result['runtime']['exit_code']==0,0,result['runtime']['exit_code']),
                   ctx.check('运行回执绑定本次制品',bool(result['receipt']) and all(result['receipt'].get(k)==v for k,v in ident.items()),ident,result['receipt'])]
    if ctx.case_id=='13':
        checks += admission(ctx,result)
    facts=evidence(ctx,'build-evidence.json',result)
    return ctx.result('编译、打包、启动与准入',checks,**facts)


def admitted_build(ctx,store,name,source=None):
    ident=identity(ctx)
    req=dict(project_id='lab',branch='main',target='generic',adapter='lab',commit_sha=ident['commit_sha'],input_digest=ident['input_digest'])
    job=store.submit(req,name+'-'+uuid.uuid4().hex)
    store.heartbeat('builder',['lab'])
    claimed=store.claim('builder')
    if claimed['job_id']!=job['job_id']: raise RuntimeError('unexpected build claim order')
    ident['build_id']=job['job_id']
    result=build(ctx,ident,name,source)
    store.report(job['job_id'],'builder',claimed['token'],'building')
    store.report(job['job_id'],'builder',claimed['token'],'verifying')
    result['job']=job;result['claim']=claimed
    return result


def admission(ctx,result):
    store=Store(ctx.output/'admission-store')
    # Admit the actual runtime-verified package against immutable inputs.
    old_ident=result['identity']
    req=dict(project_id='lab',branch='main',target='generic',adapter='lab',commit_sha=old_ident['commit_sha'],input_digest=old_ident['input_digest'])
    job=store.submit(req,uuid.uuid4().hex);store.heartbeat('builder',['lab']);claim=store.claim('builder')
    # Build again with the authority's issued job ID, rather than rewriting an existing package identity.
    result.update(build(ctx,{**old_ident,'build_id':job['job_id']},'admission'))
    store.report(job['job_id'],'builder',claim['token'],'building');store.report(job['job_id'],'builder',claim['token'],'verifying')
    package=Path(result['package']); manifest=dict(result['manifest'])
    mutation=ctx.read('admission-policy.json')['mutation']
    if mutation=='zip':
        with package.open('ab') as file: file.write(b'tampered')
    elif mutation=='manifest':
        manifest['files']=[{**x,'sha256':'0'*64} if x['path']=='texture.txt' else x for x in manifest['files']]
    elif mutation=='identity': manifest['build_id']='wrong-version'
    admitted=None;error=None
    try:
        verify_package(package,manifest)
        admitted=store.commit_artifact(job['job_id'],'builder',claim['token'],package,manifest)
    except (ValueError,zipfile.BadZipFile) as exc:
        error=str(exc)
    result.update(admission_error=error,admitted_artifact=admitted,expected_sha256=manifest['sha256'],actual_sha256=digest(package),
                  expected_build_id=job['job_id'],actual_manifest_build_id=manifest['build_id'],mutation=mutation,
                  store_artifact_count=len(store.artifacts()))
    checks=[ctx.check('制品通过真实 Store 准入',admitted is not None,'admitted',error)]
    if admitted:
        downloaded=ctx.output/'independent-download.zip';shutil.copyfile(admitted['path'],downloaded)
        verify_package(downloaded,admitted['manifest'])
        result['download_sha256']=digest(downloaded)
        checks.append(ctx.check('独立下载字节摘要一致',digest(downloaded)==admitted['manifest']['sha256'],admitted['manifest']['sha256'],digest(downloaded)))
    else:
        checks.append(ctx.check('坏包未进入制品库',len(store.artifacts())==0,0,len(store.artifacts())))
    return checks


def _pause(ctx, seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if ctx.cancelled(): raise InterruptedError('experiment cancelled')
        time.sleep(min(.04,max(0,deadline-time.monotonic())))


def _observe(ctx,store,proposal,artifact,name,invalid=False):
    observations=[]
    for index in range(2):
        worker=f'validator-{index}'
        store.heartbeat(worker,['validate'])
        # Independent validators each read and start the admitted immutable package.
        folder=ctx.output/f'{name}-validator-{index}';folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(artifact['path']) as z: z.extractall(folder)
        (folder/'smoke.json').unlink(missing_ok=True)
        if invalid and index==1:
            config=json.loads((folder/'config.json').read_text());config['asset']='canary-missing-resource.txt'
            (folder/'config.json').write_text(json.dumps(config))
            ctx.record('灰度故障注入','INFO','验证节点的资源映射指向缺失文件',worker=worker,actual_config=config)
        validator='''import app,json,os,sys
from pathlib import Path
try:
    app.main()
except Exception as exc:
    identity=json.loads(Path("build-info.json").read_text())
    Path("smoke.json").write_text(json.dumps({**identity,"asset_loaded":False,"pid":os.getpid(),"error":repr(exc)}))
    sys.exit(17)
'''
        run=ctx.command([sys.executable,'-c',validator],cwd=folder,allow_failure=True)
        receipt=json.loads((folder/'smoke.json').read_text())
        observed=store.observe(proposal['release_id'],worker,f'{name}-{index}',artifact['artifact_id'],artifact['manifest']['sha256'],receipt)
        observations.append({'worker':worker,'process':run,'receipt':receipt,'observation':observed,'observed_at':time.time()})
        if index==0: _pause(ctx,1.02)
    return observations


def release(ctx):
    store=Store(ctx.output/'release-store');policy=ctx.read('build-policy.json')
    records=[]
    # Build stable from the baseline bytes, independently of injected candidate policy.
    base_source=ctx.output/'base-source';base_source.mkdir(exist_ok=True)
    for name in ('app.py','config.json','texture.txt'):
        (base_source/name).write_text(ctx.git('show',state(ctx)['baseline_sha']+':project/'+name),encoding='utf-8')
    base=admitted_build(ctx,store,'baseline',base_source)
    base_art=store.commit_artifact(base['job']['job_id'],'builder',base['claim']['token'],Path(base['package']),base['manifest'])
    proposal=store.release(base_art['artifact_id'],'stable')
    for phase in ('shadow','canary'):
        observations=_observe(ctx,store,proposal,base_art,'baseline-'+phase)
        records.append({'phase':'baseline-'+phase,'observations':observations,'advance':store.advance(proposal['release_id'],True)})
    baseline_pointer=store.channel('stable')
    candidate=admitted_build(ctx,store,'candidate')
    artifact=store.commit_artifact(candidate['job']['job_id'],'builder',candidate['claim']['token'],Path(candidate['package']),candidate['manifest'])
    proposed=store.release(artifact['artifact_id'],'stable')
    error=None;promoted=False;rollback=None;restored=None
    try:
        if not policy['observations']:
            store.advance(proposed['release_id'],True)
        else:
            for phase in ('shadow','canary'):
                observations=_observe(ctx,store,proposed,artifact,'candidate-'+phase,invalid=(phase=='canary' and not policy['candidate_valid']))
                records.append({'phase':'candidate-'+phase,'observations':observations})
                records[-1]['advance']=store.advance(proposed['release_id'],True)
            promoted=store.channel('stable')['artifact_id']==artifact['artifact_id']
            rollback=store.rollback(proposed['release_id'])
            restored=store.artifact(store.channel('stable')['artifact_id'])
    except Conflict as exc:
        error=str(exc)
    loaded=None
    if restored:
        folder=ctx.output/'rollback-client';folder.mkdir(exist_ok=True)
        downloaded=ctx.output/'rollback-download.zip';shutil.copyfile(restored['path'],downloaded);verify_package(downloaded,restored['manifest'])
        with zipfile.ZipFile(downloaded) as z: z.extractall(folder)
        (folder/'smoke.json').unlink(missing_ok=True)
        run=ctx.command([sys.executable,str(folder/'app.py')],cwd=folder)
        loaded={'runtime':run,'receipt':json.loads((folder/'smoke.json').read_text()),'texture':(folder/'texture.txt').read_text(),'download_sha256':digest(downloaded)}
    facts=evidence(ctx,'release-report.json',dict(policy=policy,baseline_artifact=base_art,candidate_artifact=artifact,
        baseline_pointer=baseline_pointer,final_pointer=store.channel('stable'),promoted=promoted,rollback=rollback,
        admission_error=error,observations=records,restored=loaded,events=store.events()))
    return ctx.result('候选观察、晋级与回滚',[
        ctx.check('候选通过两个阶段真实观察',promoted,True,error or promoted),
        ctx.check('回滚恢复 stable 基线',bool(restored) and restored['artifact_id']==base_art['artifact_id'],base_art['artifact_id'],store.channel('stable')['artifact_id']),
        ctx.check('回滚后独立下载并启动基线内容',bool(loaded) and loaded['texture']=='texture:blue' and loaded['receipt']['build_id']==base['identity']['build_id'],base['identity']['build_id'],loaded)],**facts)
