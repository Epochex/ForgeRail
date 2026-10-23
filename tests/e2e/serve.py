"""Isolated browser-test service, never the user's interactive data directory."""
from pathlib import Path
import uuid
import uvicorn
from gamebuild.lab.api import create_lab_app

if __name__ == '__main__':
    root = Path('runtime/browser-runs')/uuid.uuid4().hex
    Path('runtime/browser-test-root.json').write_text(__import__('json').dumps(str(root.resolve())),encoding='utf-8')
    uvicorn.run(create_lab_app(root, 'browser-acceptance-only'), host='127.0.0.1', port=18767,
                access_log=False, log_level='warning')
