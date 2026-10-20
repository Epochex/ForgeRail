import argparse, json, os, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'reports'/'labs'
ROLES=['core','edge','collector','processor','gateway','scheduler','exporter','observer']

def identity_matches(actual, expected, running_image, expected_image):
    return running_image == expected_image and all(actual.get(k)==v for k,v in expected.items())

def verify_evidence(root):
    missing=[name for name in ['images','runtime','messaging','jenkins'] if not (Path(root)/(name+'.json')).exists()]
    invalid=[]
    for name in ['images','runtime','messaging','jenkins']:
        if name in missing: continue
        try:
            if json.loads((Path(root)/(name+'.json')).read_text())['status']!='passed': invalid.append(name)
        except (ValueError, KeyError): invalid.append(name)
    return {'status':'failed' if missing or invalid else 'passed','missing':missing,'invalid':invalid}

def run(argv, *, check=True, log=None):
    started=time.monotonic()
    p=subprocess.run([str(x) for x in argv],cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True)
    if log:
        (REPORTS/log).write_text(p.stdout+p.stderr,encoding='utf-8')
    if check and p.returncode:
        raise RuntimeError(f'command failed ({p.returncode}): {argv[:3]}\n{p.stderr[-1500:]}')
    return p,round(time.monotonic()-started,3)

def docker(*args,**kwargs): return run(['docker',*args],**kwargs)
def inspect(image): return docker('image','inspect',image,'--format','{{.Id}}')[0].stdout.strip()
def save(name,data):
    REPORTS.mkdir(parents=True,exist_ok=True); (REPORTS/(name+'.json')).write_text(json.dumps(data,indent=2),encoding='utf-8'); print(name+': '+data.get('status','recorded'),flush=True)
def compose(*args,**kwargs): return docker('compose','--env-file','.runtime/lab.env','-p','gamebuildlab','-f','infra/compose.yaml',*args,**kwargs)

def images():
    sha=run(['git','rev-parse','HEAD'])[0].stdout.strip(); rounds=[]; run_id=uuid.uuid4().hex[:10]
    for name,app,dep,cold in [('cold','v1','v1',True),('warm','v1','v1',False),('app_change','v2','v1',False),('dependency_change','v2','v2',False)]:
        entries=[]
        for role in ROLES:
            image=f'gamebuildlab/{role}:{sha[:12]}-{run_id}-{name}'
            assert docker('image','inspect',image,check=False)[0].returncode!=0
            argv=['build','-f','infra/Dockerfile.targets','--target',role,'--build-arg',f'BUILD_SHA={sha}','--build-arg',f'APP_REVISION={app}','--build-arg',f'DEP_REVISION={dep}','-t',image,'.']
            if cold: argv.insert(1,'--no-cache')
            p,duration=docker(*argv,log=f'build-{name}-{role}.log')
            image_id=inspect(image)
            # Container itself imports the HTTP module and reads the exact embedded identity.
            p,_=docker('run','--rm',image,'python','-c',"import sys,json;sys.path.insert(0,'/app');import runtime;print(json.dumps(runtime.IDENTITY))")
            actual=json.loads(p.stdout); assert actual['role']==role and actual['sha']==sha and actual['app_revision']==app
            entries.append({'role':role,'image_tag':image,'image_id':image_id,'seconds':duration,'cached_steps':(REPORTS/f'build-{name}-{role}.log').read_text().count('CACHED'),'identity':actual})
        rounds.append({'name':name,'seconds':round(sum(e['seconds'] for e in entries),3),'targets':entries})
    save('images',{'status':'passed','run_id':run_id,'commit_sha':sha,'cold_definition':'--no-cache per target; no global cache deleted; base image pre-pulled','rounds':rounds})

def runtime():
    image_report=json.loads((REPORTS/'images.json').read_text())
    targets={entry['role']:entry for entry in image_report['rounds'][0]['targets']}
    image=targets['core']['image_tag']; edge=targets['edge']['image_tag']; sha=image_report['commit_sha']; results=[]
    archive=ROOT/'.runtime'/'offline-core.tar'
    docker('save','-o',archive,image); import hashlib
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    backup='gamebuildlab/core:offline-preserved-'+uuid.uuid4().hex[:10]
    docker('tag',image,backup)
    docker('image','rm',image)
    missing,_=docker('image','inspect',image,check=False); assert missing.returncode!=0
    incomplete=archive.with_name('offline-incomplete.tar')
    archive_bytes=archive.read_bytes(); incomplete.write_bytes(archive_bytes[:len(archive_bytes)//2])
    bad_import,_=docker('load','-i',incomplete,check=False,log='offline-incomplete-load.log')
    assert bad_import.returncode!=0
    assert docker('image','inspect',image,check=False)[0].returncode!=0
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==digest
    docker('load','-i',archive,log='offline-load.log')
    assert inspect(image)==inspect(backup)
    for role,tag,port in [('core',image,18982),('edge',edge,18983)]:
        name='gamebuildlab-'+role; docker('rm','-f',name,check=False)
        docker('run','--pull=never','-d','--name',name,'--network','gamebuildlab_default','-p',f'127.0.0.1:{port}:8080','-e','CONFIG_VERSION=v1',tag)
        try:
            for _ in range(50):
                try:
                    actual=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/build-info',timeout=2));break
                except Exception: time.sleep(.2)
            running=docker('inspect',name,'--format','{{.Image}}')[0].stdout.strip(); expected={'role':role,'sha':sha,'config':'v1'}
            assert identity_matches(actual,expected,running,inspect(tag))
            assert not identity_matches(actual,dict(expected,config='bad'),running,inspect(tag))
            wrong=inspect(edge if role=='core' else image); assert not identity_matches(actual,expected,wrong,inspect(tag))
            docker('rm','-f',name)
            docker('run','--pull=never','-d','--name',name,'--network','gamebuildlab_default','-p',f'127.0.0.1:{port}:8080','-e','CONFIG_VERSION=bad',tag)
            for _ in range(50):
                try: drift=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/build-info',timeout=2)); break
                except Exception: time.sleep(.2)
            assert not identity_matches(drift,expected,running,inspect(tag))
            bad_module,_=docker('run','--rm',tag,'python','-c','import missing_gamebuild_module',check=False)
            assert bad_module.returncode!=0
            docker('rm','-f',name)
            docker('run','--pull=never','-d','--name',name,'--network','gamebuildlab_default','-p',f'127.0.0.1:{port}:8080','-e','CONFIG_VERSION=v1',tag)
            for _ in range(50):
                try: restored=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/build-info',timeout=2)); break
                except Exception: time.sleep(.2)
            assert identity_matches(restored,expected,running,inspect(tag))
            results.append({'role':role,'container_image':running,'runtime':actual,'drift_runtime':drift,'config_drift_rejected':True,'wrong_image_rejected':True,'missing_module_exit':bad_module.returncode,'stable_restored':restored})
        finally: docker('rm','-f',name)
    save('runtime',{'status':'passed','offline_sha256':digest,'incomplete_import_exit':bad_import.returncode,'incomplete_import_target_absent':True,'offline_import':'docker save; target tag removed and absence checked; truncated archive rejected; docker load restores identical ID; --pull=never runtime','services':results,'k3d':{'status':'not_run','reason':'optional; no isolated Kubernetes execution performed'},'systemd':{'status':'not_run','reason':'Docker execution is not systemd validation'}})

def services():
    image_report=json.loads((REPORTS/'images.json').read_text()); results=[]
    for entry in image_report['rounds'][0]['targets']:
        name='gamebuildlab-check-'+uuid.uuid4().hex[:10]
        docker('run','--pull=never','-d','--name',name,'--network','none',entry['image_tag'])
        try:
            for _ in range(30):
                p,_=docker('exec',name,'python','-c',"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/build-info',timeout=2).read().decode())",check=False)
                if p.returncode==0: break
                time.sleep(.2)
            else: raise RuntimeError('target HTTP service did not start: '+entry['role'])
            actual=json.loads(p.stdout); running=docker('inspect',name,'--format','{{.Image}}')[0].stdout.strip()
            assert identity_matches(actual,{'role':entry['role'],'sha':image_report['commit_sha'],'config':'v1'},running,entry['image_id'])
            results.append({'role':entry['role'],'image_id':running,'http_runtime':actual})
        finally: docker('rm','-f',name)
    save('services',{'status':'passed','network':'none; HTTP queried via docker exec loopback','targets':results})

def messaging():
    suffix=uuid.uuid4().hex[:10]; out={}; volume='gamebuildlab_ledger_'+suffix
    docker('volume','create',volume)
    try:
        for env in ['stable','shadow']:
            topic='gamebuildlab-'+env+'-'+suffix; group=topic+'-consumer'
            compose('exec','-T','redpanda','rpk','topic','create',topic,'--partitions','1')
            base=['run','--rm','-v',str(ROOT/'labs')+':/workspace/labs:ro','--network','gamebuildlab_default','-v',volume+':/ledger','gamebuildlab-tools','python','/workspace/labs/messaging.py']
            docker(*base,'--mode','produce','--topic',topic)
            offset=100 if env=='shadow' else 0
            crash,_=docker(*base,'--mode','consume','--topic',topic,'--group',group,'--db',f'/ledger/{env}.sqlite','--value-offset',str(offset),'--crash',check=False,log=f'{env}-crash.log'); assert crash.returncode==23
            p,_=docker(*base,'--mode','consume','--topic',topic,'--group',group,'--db',f'/ledger/{env}.sqlite','--value-offset',str(offset),log=f'{env}-restart.log')
            result=json.loads(p.stdout.strip().splitlines()[-1]); assert result['duplicates']==1 and result['summary']['unique']==12 and result['summary']['total']==66+12*offset
            out[env]={'topic':topic,'group':group,'ledger':f'{env}.sqlite','crash_exit':23,**result}
        # Read stable again after shadow completed: no cross-environment side effects.
        p,_=docker('run','--rm','-v',volume+':/ledger','gamebuildlab-tools','python','-c',"import sys,json;sys.path.insert(0,'/workspace/labs');from ledger import Ledger;print(json.dumps(Ledger('/ledger/stable.sqlite').summary()))")
        assert json.loads(p.stdout)=={'unique':12,'total':66,'checkpoint':11}
        save('messaging',{'status':'passed','events_per_namespace':12,'side_effect_isolation':True,'environments':out,'ledger_volume':volume})
    except Exception:
        raise

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['images','services','runtime','messaging','verify']);args=p.parse_args()
    REPORTS.mkdir(parents=True,exist_ok=True)
    if args.action=='verify':
        result=verify_evidence(REPORTS);save('summary',result);sys.exit(result['status']!='passed')
    try: globals()[args.action]()
    except Exception as exc:
        save(args.action,{'status':'failed','error':str(exc)});raise
if __name__=='__main__':main()
