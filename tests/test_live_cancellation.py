"""Cancel a real node while its actual child is running over loopback HTTP."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx

from gamebuild.source import git, snapshot_request
from gamebuild.cli import wait_server


def test_live_cancellation_stops_running_node_and_never_publishes(tmp_path):
    repo=tmp_path/'repo'; repo.mkdir()
    git(repo,'init','-b','main')
    (repo/'config.json').write_text('{"work_seconds":30}')
    git(repo,'add','.')
    git(repo,'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','slow lab input')
    request=snapshot_request(repo,'demo','lab','lab')
    token=secrets.token_hex(24)
    env={**os.environ,'GAMEBUILD_TOKEN':token,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    url='http://127.0.0.1:'+str(port)
    server_log=(tmp_path/'server.log').open('w'); node_log=(tmp_path/'node.log').open('w')
    server=subprocess.Popen([sys.executable,'-m','gamebuild.cli','serve','--root',str(tmp_path/'control'),'--port',str(port)],env=env,stdout=server_log,stderr=subprocess.STDOUT)
    node=None
    try:
        wait_server(url,server)
        with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=5) as c:
            j=c.post('/v1/jobs',json={'request':request,'key':'slow'}).json()
            code='from gamebuild.worker import work_once; from pathlib import Path; import os,json,sys; work_once(sys.argv[1],os.environ["GAMEBUILD_TOKEN"],"cancel-node",Path(sys.argv[2]),json.loads(sys.argv[3]),lease_seconds=1)'
            node=subprocess.Popen([sys.executable,'-c',code,url,str(tmp_path/'node'),json.dumps({'demo':str(repo)})],env=env,stdout=node_log,stderr=subprocess.STDOUT)
            for _ in range(200):
                state=c.get('/v1/jobs/'+j['job_id']).json()['state']
                if state=='building': break
                assert state not in ('failed','succeeded'),state
                time.sleep(0.05)
            else: raise AssertionError('node never entered building')
            time.sleep(0.8)
            assert c.get('/v1/jobs/'+j['job_id']).json()['state']=='building'
            assert c.post('/v1/jobs/'+j['job_id']+'/cancel').json()['state']=='cancelled'
            assert node.wait(timeout=10)!=0
            final=c.get('/v1/jobs/'+j['job_id']).json()
            assert final['state']=='cancelled' and final['artifact_id'] is None
    finally:
        for p in (node,server):
            if p is not None and p.poll() is None: p.terminate(); p.wait(timeout=10)
        server_log.close(); node_log.close()


def test_continuous_worker_survives_a_failed_child_and_accepts_next_job(tmp_path):
    repo=tmp_path/'repo'; repo.mkdir(); git(repo,'init','-b','main')
    (repo/'config.json').write_text('invalid-json'); git(repo,'add','.')
    git(repo,'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','bad input')
    bad=snapshot_request(repo,'demo','lab','lab')
    (repo/'config.json').write_text('{}'); git(repo,'add','.')
    git(repo,'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','fixed input')
    good=snapshot_request(repo,'demo','lab','lab')
    token=secrets.token_hex(24); env={**os.environ,'GAMEBUILD_TOKEN':token,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    url='http://127.0.0.1:'+str(port)
    log=(tmp_path/'processes.log').open('w')
    server=subprocess.Popen([sys.executable,'-m','gamebuild.cli','serve','--root',str(tmp_path/'control'),'--port',str(port)],env=env,stdout=log,stderr=subprocess.STDOUT)
    node=None
    try:
        wait_server(url,server)
        with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=5) as c:
            first=c.post('/v1/jobs',json={'request':bad,'key':'bad'}).json()
            second=c.post('/v1/jobs',json={'request':good,'key':'good'}).json()
            node=subprocess.Popen([sys.executable,'-m','gamebuild.cli','worker','--url',url,'--root',str(tmp_path/'node'),'--name','daemon','--projects',json.dumps({'demo':str(repo)})],env=env,stdout=log,stderr=subprocess.STDOUT)
            for _ in range(200):
                state=c.get('/v1/jobs/'+second['job_id']).json()['state']
                if state=='succeeded': break
                assert node.poll() is None,'worker daemon exited after first failed build'
                time.sleep(.05)
            else: raise AssertionError('following job did not complete')
            assert c.get('/v1/jobs/'+first['job_id']).json()['state']=='failed'
    finally:
        for p in (node,server):
            if p is not None and p.poll() is None: p.terminate(); p.wait(timeout=10)
        log.close()
