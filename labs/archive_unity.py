"""Retrieve the committed real Unity package without exposing the API credential."""
import json
import os
import zipfile
from pathlib import Path
import httpx
from gamebuild.artifacts import verify_package

job=json.loads(Path('/reports/labs/jenkins-unity-job.json').read_text())
assert job['state']=='succeeded' and job['request']['adapter']=='unity'
destination=Path('evidence/unity'); destination.mkdir(parents=True,exist_ok=True)
with httpx.Client(base_url='http://controlplane:8000',headers={'Authorization':'Bearer '+os.environ['GAMEBUILD_TOKEN']},trust_env=False,timeout=120) as client:
    response=client.get('/v1/artifacts/'+job['artifact_id']); response.raise_for_status()
    manifest=response.json()['manifest']
    package=destination/'package.zip'
    with client.stream('GET','/v1/artifacts/'+job['artifact_id']+'/download') as response:
        response.raise_for_status()
        with package.open('wb') as output:
            for chunk in response.iter_bytes(): output.write(chunk)
verify_package(package,manifest)
assert manifest['adapter']=='unity'
(destination/'manifest.json').write_text(json.dumps(manifest,indent=2))
receipts={}
with zipfile.ZipFile(package) as archive:
    for name in ['build-info.json','build-report.json','smoke.json']:
        receipts[name]=json.loads(archive.read(name).decode('utf-8-sig'))
        (destination/name).write_text(json.dumps(receipts[name],indent=2))
assert receipts['smoke.json']['asset_loaded'] is True
assert receipts['smoke.json']['commit_sha']==job['request']['commit_sha']
report={'status':'passed','adapter':'unity','job_id':job['job_id'],'artifact_id':job['artifact_id'],'manifest':manifest,'receipts':receipts,'archive_path':'evidence/unity/package.zip'}
Path('/reports/labs/jenkins-unity-verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'status':'passed','artifact_id':job['artifact_id'],'sha256':manifest['sha256']}))
