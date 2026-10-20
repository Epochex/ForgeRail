"""Bound test-channel observations to actually downloaded and executed artifacts."""
import json
from pathlib import Path
import time
import uuid
import zipfile

import httpx

from .artifacts import verify_package
from .runner import run_process


def validate_release(url, token, artifact_id, root: Path, channel='interview'):
    root=Path(root).resolve(); root.mkdir(parents=True,exist_ok=True)
    with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},timeout=120,trust_env=False) as client:
        def post(path,value):
            r=client.post(path,json=value); r.raise_for_status(); return r.json()
        r=client.get('/v1/artifacts/'+artifact_id); r.raise_for_status(); manifest=r.json()['manifest']
        release=post('/v1/releases',{'artifact_id':artifact_id,'channel':channel})
        observations=[]
        for phase in ('shadow','canary'):
            for index in range(2):
                worker='validation-'+str(index); validation_id=uuid.uuid4().hex
                work=root/release['release_id']/phase/worker; work.mkdir(parents=True)
                package=work/'package.zip'
                with client.stream('GET','/v1/artifacts/'+artifact_id+'/download') as response:
                    response.raise_for_status()
                    with package.open('wb') as output:
                        for chunk in response.iter_bytes(): output.write(chunk)
                verify_package(package,manifest)
                with zipfile.ZipFile(package) as archive:
                    if manifest['adapter']=='unity': archive.extractall(work/'payload')
                    else: receipt=json.loads(archive.read('smoke.json'))
                if manifest['adapter']=='unity':
                    payload=work/'payload'; receipt_path=work/'fresh-smoke.json'
                    result=run_process([str(payload/'player/GameBuildLab.exe'),'-batchmode','-nographics','--smoke-output',str(receipt_path)],cwd=payload/'player',log_path=work/'player.log',timeout=60)
                    if result['exit_code']!=0: raise RuntimeError('release validation Player failed')
                    receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig'))
                post('/v1/workers/heartbeat',{'worker':worker,'capabilities':['validate']})
                observation=post('/v1/releases/'+release['release_id']+'/observations',{'worker':worker,'validation_id':validation_id,'artifact_id':artifact_id,'sha256':manifest['sha256'],'receipt':receipt})
                if observation['passed'] is not True: raise RuntimeError('release validation receipt failed')
                observations.append({**observation,'worker':worker,'artifact_id':artifact_id,'phase':phase,'evidence_dir':str(work)})
                if index==0: time.sleep(1.1)
            release.update(post('/v1/releases/'+release['release_id']+'/advance',{'passed':True}))
        result={'status':'passed','artifact_id':artifact_id,'release':release,'observations':observations,'scope':'two logical validation nodes on this host; fresh Player executions for Unity artifacts'}
        (root/(release['release_id']+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
