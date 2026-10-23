"""Bounded, same-host integration using the original API and worker protocols."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
import secrets
import sys
import threading
import time

import httpx

from gamebuild.artifacts import verify_package
from gamebuild.source import input_digest


def actor(ctx, cfg, name):
    deadline_marker=ctx.output/(name+'.deadline')
    cfg = {**cfg,'parent_pid':os.getpid(),'cancel_path':str(ctx.output/'cancel.requested'),
           'deadline_path':str(deadline_marker)}
    path = ctx.output/(name+'-credentials.json')
    path.write_text(json.dumps(cfg),encoding='utf-8')
    timeout=60 if cfg['role']=='server' else 35
    timer=threading.Timer(timeout-2,deadline_marker.touch);timer.daemon=True;timer.start()
    try:
        result=ctx.command([sys.executable,'-m','gamebuild.lab.node',str(path)],timeout=timeout,allow_failure=True,cancel_grace=2)
        if deadline_marker.exists(): raise TimeoutError('HTTP node exceeded bounded execution deadline')
        return result
    finally:
        timer.cancel()


@contextmanager
def control(ctx):
    ready,stop = ctx.output/'control-ready.json',ctx.output/'control.stop'
    ready.unlink(missing_ok=True);stop.unlink(missing_ok=True)
    token = secrets.token_urlsafe(32)
    cfg = dict(role='server',token=token,output='',control=str(ctx.output/'http-control'),ready=str(ready),stop=str(stop))
    with ThreadPoolExecutor(max_workers=1) as pool:
        server = pool.submit(actor,ctx,cfg,'control')
        try:
            deadline = time.monotonic()+10
            while True:
                if ctx.cancelled(): raise InterruptedError('experiment cancelled')
                if server.done(): raise RuntimeError('control process exited before readiness: '+server.result()['stdout'])
                if ready.exists():
                    info = json.loads(ready.read_text())
                    try:
                        if httpx.get(info['url']+'/health',trust_env=False,timeout=.2).is_success: break
                    except httpx.HTTPError: pass
                if time.monotonic()>deadline: raise TimeoutError('HTTP control readiness')
                time.sleep(.04)
            ctx.record('HTTP 控制面','INFO','独立控制面进程已就绪',**info)
            with httpx.Client(base_url=info['url'],headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10) as client:
                yield client,dict(token=token,url=info['url'],control_pid=info['pid'])
        finally:
            stop.touch()
            server.result(timeout=40)


def request(ctx):
    req = dict(project_id='lab',adapter='lab',target='generic',branch='main',commit_sha=ctx.git('rev-parse','HEAD'))
    req['input_digest'] = input_digest(ctx.repo,req)
    return req


def claim(ctx, connection, worker, capabilities, slots=1, lease_seconds=30, name='claim'):
    receipt = ctx.output/(name+'-credentials-result.json')
    process = actor(ctx,{**connection,'role':'claim','worker':worker,'capabilities':capabilities,
                         'slots':slots,'lease_seconds':lease_seconds,'output':str(receipt)},name)
    if process['exit_code']: raise RuntimeError('HTTP claim node failed: '+process['stdout'])
    value = json.loads(receipt.read_text(encoding='utf-8'))
    ctx.record('HTTP 节点认领','INFO',worker,pid=value['pid'],claimed=bool(value['claim']))
    return value


def work(ctx,connection,worker,name='build-node',slots=1):
    receipt = ctx.output/(name+'-receipt.json')
    result = ctx.output/(name+'-result.json')
    process = actor(ctx,{**connection,'role':'worker','worker':worker,'slots':slots,'worker_root':str(ctx.root/'nodes'/name),
                         'repo':str(ctx.repo),'run_root':str(ctx.root),'case_id':ctx.case_id,'variant':ctx.variant,
                         'action_id':ctx.output.name,'output':str(receipt),'result':str(result)},name)
    value = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
    observed = json.loads(result.read_text(encoding='utf-8')) if result.exists() else None
    ctx.record('HTTP Worker','SUCCEEDED' if process['exit_code']==0 else 'FAILED',worker,
               pid=value.get('pid'),exit_code=process['exit_code'],artifact=value.get('artifact'))
    if observed is None: raise RuntimeError('worker did not produce actual build observations: '+process['stdout'])
    return value,observed


def download(ctx,client,artifact,name='http-downloaded.zip'):
    response = client.get('/v1/artifacts/'+artifact['artifact_id']+'/download')
    response.raise_for_status()
    path = ctx.output/name; path.write_bytes(response.content)
    verify_package(path,artifact['manifest'])
    return {'bytes':len(response.content),'manifest':artifact['manifest'],'path':str(path)}


def build_flow(ctx):
    with control(ctx) as (client,connection):
        submitted = client.post('/v1/jobs',json={'request':request(ctx),'key':'build'})
        submitted.raise_for_status(); job = submitted.json()
        receipt,result = work(ctx,connection,'builder')
        snapshot = client.get('/v1/jobs/'+job['job_id']).json()
        if receipt.get('artifact'): result['download'] = download(ctx,client,receipt['artifact'])
        result['http_job'] = snapshot
        result['control_pid'] = connection['control_pid']
        result['worker_pid'] = receipt.get('pid')
        return result
