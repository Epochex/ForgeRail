"""Isolated browser-test service, never the user's interactive data directory."""
from pathlib import Path
import json
import uuid
import uvicorn
from gamebuild.lab.api import create_lab_app

def prepare_root(runtime=Path('runtime')):
    root=runtime/'browser-runs'/uuid.uuid4().hex
    root.mkdir(parents=True,exist_ok=True)
    (runtime/'browser-test-root.json').write_text(json.dumps(str(root.resolve())),encoding='utf-8')
    return root


if __name__ == '__main__':
    root=prepare_root()
    uvicorn.run(create_lab_app(root, 'browser-acceptance-only'), host='127.0.0.1', port=18767,
                access_log=False, log_level='warning')
