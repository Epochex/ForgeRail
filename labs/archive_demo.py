"""Archive the committed lab packages and safe logs, excluding SQLite lease data."""
import json
import shutil
import sqlite3
from pathlib import Path
from gamebuild.artifacts import verify_package

report=Path('/reports/labs/jenkins-demo.json')
if report.exists():
    result=json.loads(report.read_text())
    run=Path(result['evidence_dir']).resolve()
    if not run.is_relative_to(Path('/tmp/gamebuild-jenkins-demo')):
        raise ValueError('unexpected demo evidence directory')
    destination=Path('evidence/demo'); destination.mkdir(parents=True,exist_ok=True)
    for log in run.glob('*.log'): shutil.copy2(log,destination/log.name)
    with sqlite3.connect(run/'control/state.sqlite3') as db:
        for artifact_id,package,encoded in db.execute('SELECT id,path,manifest FROM artifacts'):
            manifest=json.loads(encoded)
            package=Path(package).resolve()
            if not package.is_relative_to(run/'control/blobs'): raise ValueError('unexpected artifact directory')
            verify_package(package,manifest)
            shutil.copy2(package,destination/(artifact_id+'.zip'))
            (destination/(artifact_id+'.manifest.json')).write_text(json.dumps(manifest,indent=2))
