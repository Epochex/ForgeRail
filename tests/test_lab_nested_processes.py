"""Cancel and owner-death regressions across the new HTTP node process boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from gamebuild.lab.api import create_lab_app
from gamebuild.lab.context import Context


def eventually(probe,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=probe()
        if value:return value
        time.sleep(.04)
    raise AssertionError('process condition was not observed')


def setup_hanging_node(client,root):
    run=client.post('/lab/api/runs',json={'case_id':'05','variant':'release_gate'}).json()
    rid=run['id']
    def action(kind):
        client.post(f'/lab/api/runs/{rid}/actions',json={'kind':kind,'request_key':kind}).raise_for_status()
        value=eventually(lambda:(lambda v: v if not v['busy_action'] else None)(client.get('/lab/api/runs/'+rid).json()))
        assert value['actions'][-1]['state']=='SUCCEEDED',value['actions'][-1]
    action('prepare')
    ctx=Context(Path(root)/'runs'/rid,'05','release_gate','fixture')
    text=ctx.read('project/app.py')
    live=Path(root).resolve()/'runtime-child.pid';beat=Path(root).resolve()/'runtime-heartbeat.txt'
    replacement=('root=Path(__file__).parent\n    import time\n'
                 f'    Path({str(live)!r}).write_text(str(os.getpid()))\n'
                 f'    while True:\n        Path({str(beat)!r}).write_text(str(time.time_ns()))\n        time.sleep(.02)')
    ctx.write('project/app.py',text.replace('root=Path(__file__).parent',replacement))
    ctx.commit('Registered test fixture hangs during independent runtime')
    action('inject')
    client.post(f'/lab/api/runs/{rid}/actions',json={'kind':'execute','request_key':'execute'}).raise_for_status()
    eventually(lambda:live.exists() and beat.exists())
    return rid,live,beat


def test_cancel_http_worker_reaps_its_nested_runtime_process(tmp_path):
    with TestClient(create_lab_app(tmp_path,'test'),base_url='http://127.0.0.1') as client:
        client.get('/?access=test',follow_redirects=False)
        rid,live,beat=setup_hanging_node(client,tmp_path)
        client.post('/lab/api/runs/'+rid+'/cancel').raise_for_status()
        run=eventually(lambda:(lambda v:v if not v['busy_action'] else None)(client.get('/lab/api/runs/'+rid).json()))
        assert run['status']=='CANCELLED'
        before=beat.read_bytes();time.sleep(.25)
        assert beat.read_bytes()==before


@pytest.mark.skipif(os.name=='nt',reason='POSIX owner-death/session regression; Windows uses Job Objects')
def test_killed_service_propagates_stop_through_node_to_runtime(tmp_path):
    # A separate service process is essential: TestClient teardown is graceful, not a crash.
    script=tmp_path/'owner.py'
    script.write_text('''import sys,time,json
from pathlib import Path
from fastapi.testclient import TestClient
from gamebuild.lab.api import create_lab_app
from test_lab_nested_processes import setup_hanging_node
root=Path(sys.argv[1])
with TestClient(create_lab_app(root,'test'),base_url='http://127.0.0.1') as c:
 c.get('/?access=test',follow_redirects=False)
 rid,live,beat=setup_hanging_node(c,root)
 (root/'ready.json').write_text(json.dumps({'rid':rid,'beat':str(beat)}))
 while True: time.sleep(.1)
''',encoding='utf-8')
    env={**os.environ,'PYTHONPATH':os.pathsep.join([str(Path('src').resolve()),str(Path('tests').resolve())])}
    with (tmp_path/'owner.log').open('wb') as log:
        owner=subprocess.Popen([sys.executable,str(script),str(tmp_path/'data')],env=env,stdout=log,stderr=log)
        try:
            ready=tmp_path/'data/ready.json'
            eventually(lambda:ready.exists(),30)
            info=json.loads(ready.read_text());beat=Path(info['beat'])
            owner.kill();owner.wait(timeout=5)
            # Cooperative orphan detection and nested reap complete before the outer grace expires.
            time.sleep(3.5)
            before=beat.read_bytes();time.sleep(.3)
            assert beat.read_bytes()==before
        finally:
            if owner.poll() is None:owner.kill();owner.wait(timeout=5)
