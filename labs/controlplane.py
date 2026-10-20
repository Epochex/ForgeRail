import json, time, urllib.request, urllib.error, uuid
from pathlib import Path
from acceptance import compose, save, run
ROOT=Path(__file__).resolve().parents[1]
credentials=json.loads((ROOT/'.runtime/credentials.json').read_text()); base='http://127.0.0.1:18981'
def request(path,data=None,authenticated=True):
    headers={'Authorization':'Bearer '+credentials['token']} if authenticated else {}
    if data is not None: data=json.dumps(data).encode();headers['Content-Type']='application/json'
    return urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=headers),timeout=5)
def execute():
    for _ in range(100):
        try: request('/openapi.json'); break
        except Exception: time.sleep(.2)
    else: raise RuntimeError('Compose API readiness timed out')
    try: request('/v1/jobs/missing',authenticated=False); raise AssertionError('missing authentication accepted')
    except urllib.error.HTTPError as exc: assert exc.code==401
    if any(job['state'] in ('leased','building','verifying','publishing') for job in json.load(request('/v1/jobs'))):
        save('controlplane',{'status':'blocked','reason':'active build exists; service restart deliberately deferred'})
        raise RuntimeError('Cannot restart control plane while a real build is active')
    sha=run(['git','rev-parse','HEAD'])[0].stdout.strip()
    job=json.load(request('/v1/jobs',{'request':{'project_id':'lab-compose','commit_sha':sha,'input_digest':'b'*64,'adapter':'unity','unity_version':'0.0.0f0','target':'StandaloneWindows64','branch':'main'},'key':'compose-'+uuid.uuid4().hex}))
    compose('restart','controlplane')
    for _ in range(60):
        try: restored=json.load(request('/v1/jobs/'+job['job_id'])); break
        except Exception: time.sleep(.2)
    else: raise RuntimeError('Compose API recovery timed out')
    assert restored['job_id']==job['job_id'] and restored['state']=='queued'
    cleanup=json.load(request('/v1/jobs/'+job['job_id']+'/cancel',{}))
    assert cleanup['state']=='cancelled'
    save('controlplane',{'status':'passed','unauthenticated_status':401,'job_id':job['job_id'],'before':job['state'],'after_restart':restored['state'],'acceptance_job_cleanup':'cancelled','persistence':'Linux project-owned control_data volume'})
if __name__=='__main__':execute()
