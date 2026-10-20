import base64, hashlib, http.cookiejar, json, time, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def execute():
    credentials=json.loads((ROOT/'.runtime/credentials.json').read_text())
    env=dict(line.split('=',1) for line in (ROOT/'.runtime/lab.env').read_text().splitlines() if '=' in line)
    base='http://127.0.0.1:'+env.get('JENKINS_PORT','18980')
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    auth='Basic '+base64.b64encode(('labadmin:'+credentials['password']).encode()).decode()
    def request(path,data=None,headers=None):
        req=urllib.request.Request(base+path,data=data,headers={'Authorization':auth,**(headers or {})})
        return opener.open(req,timeout=30)
    for _ in range(180):
        try: crumb=json.load(request('/crumbIssuer/api/json')); break
        except Exception: time.sleep(1)
    else: raise RuntimeError('Jenkins authenticated readiness timed out')
    try:
        urllib.request.urlopen(base+'/api/json',timeout=5)
        raise AssertionError('anonymous Jenkins access accepted')
    except urllib.error.HTTPError as exc:
        assert exc.code in (401,403)
    executors=json.load(request('/api/json?tree=numExecutors'))['numExecutors']
    assert executors==0
    headers={crumb['crumbRequestField']:crumb['crumb']}
    plugins=json.load(request('/pluginManager/api/json?tree=plugins[shortName,version,active]'))
    (ROOT/'reports/labs/jenkins-plugins.json').write_text(json.dumps(plugins,indent=2),encoding='utf-8')
    nodes=json.load(request('/computer/api/json?tree=computer[displayName,offline]'))
    for _ in range(90):
        if any(x['displayName']=='linux-lab' and not x['offline'] for x in nodes['computer']):break
        time.sleep(1);nodes=json.load(request('/computer/api/json?tree=computer[displayName,offline]'))
    else:raise RuntimeError('Separate Linux agent never connected')
    queued=request('/job/gamebuild-lab/buildWithParameters',data=b'RUN_UNITY=true',headers=headers).headers['Location']; queuepath=queued.replace(base,'')
    for _ in range(90):
        queue=json.load(request(queuepath+'api/json'))
        if 'executable' in queue:break
        time.sleep(1)
    else:raise RuntimeError('Jenkins queued job not started')
    number=queue['executable']['number']; path=f'/job/gamebuild-lab/{number}/'
    for _ in range(900):
        result=json.load(request(path+'api/json'))
        if not result['building']:break
        time.sleep(1)
    else:raise RuntimeError('Jenkins job timed out')
    logs=request(path+'consoleText').read().decode()
    for sensitive in credentials.values(): logs=logs.replace(sensitive,'[REDACTED]')
    (ROOT/'reports/labs/jenkins-console.txt').write_text(logs,encoding='utf-8')
    (ROOT/f'reports/labs/jenkins-{number}-console.txt').write_text(logs,encoding='utf-8')
    if result['result']=='SUCCESS':
        archived=json.load(request(path+'artifact/evidence/jenkins-demo.json'))
        assert archived['status']=='passed'
        unity=json.load(request(path+'artifact/evidence/jenkins-unity-verification.json'))
        assert unity['status']=='passed' and unity['adapter']=='unity'
        digest=hashlib.sha256(); size=0
        with request(path+'artifact/evidence/unity/package.zip') as artifact:
            while chunk:=artifact.read(1024*1024): digest.update(chunk); size+=len(chunk)
        assert digest.hexdigest()==unity['manifest']['sha256'] and size==unity['manifest']['size']
    report={'status':'passed' if result['result']=='SUCCESS' else 'failed','build_number':number,'url':base+path,'result':result['result'],'controller_executors':executors,'anonymous_access_rejected':True,'agent':'linux-lab','nodes':nodes,'artifacts':result.get('artifacts',[]),'duration_ms':result['duration']}
    if result['result']=='SUCCESS': report['unity']={'job_id':unity['job_id'],'artifact_id':unity['artifact_id'],'archive_sha256_verified':digest.hexdigest(),'archive_bytes':size}
    (ROOT/'reports/labs/jenkins.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/f'reports/labs/jenkins-{number}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='artifacts'},indent=2))
    if report['status']!='passed': raise SystemExit(1)
if __name__=='__main__':execute()
