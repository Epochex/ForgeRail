import hashlib
import json
import subprocess
from pathlib import Path

root=Path('/workspace')
for previous in ['jenkins-demo.json','jenkins-doctor.json','jenkins-pytest.txt','jenkins-unity-job.json','jenkins-unity-verification.json']:
    (Path('/reports/labs')/previous).unlink(missing_ok=True)
def git(*args):
    return subprocess.check_output(['git','-c','safe.directory=/workspace',*args],cwd=root,text=True).strip()

files={}
for folder in ['src','tests','ci','infra','labs']:
    for path in sorted((root/folder).rglob('*')):
        if path.is_file() and path.suffix in ('.py','.groovy','.yaml','.sh','.ps1','.cs') and '__pycache__' not in path.parts:
            files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
report={'commit_sha':git('rev-parse','HEAD'),'dirty':bool(git('status','--porcelain')),'source_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),'files':files}
Path('/reports/labs/jenkins-source.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='files'}))
