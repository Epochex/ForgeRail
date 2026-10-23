"""Registered subprocess entrypoints for the Lab's real HTTP control/worker chain."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import threading

import httpx
import uvicorn


def main(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    output = Path(cfg['output'])
    external_stop = threading.Event()
    watcher_done = threading.Event()
    def watch_parent():
        while not watcher_done.wait(.05):
            if (Path(cfg['cancel_path']).exists() or Path(cfg['deadline_path']).exists() or
                    (os.name!='nt' and os.getppid()!=cfg['parent_pid'])):
                external_stop.set(); return
    threading.Thread(target=watch_parent,daemon=True).start()
    if cfg['role'] == 'server':
        from gamebuild.api import create_app
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0)); sock.listen(128)
        server = uvicorn.Server(uvicorn.Config(create_app(Path(cfg['control']), cfg['token']),
                                             log_level='error', access_log=False))
        def stop():
            while not Path(cfg['stop']).exists() and not external_stop.is_set():
                if threading.Event().wait(.05): return
            server.should_exit = True
        threading.Thread(target=stop, daemon=True).start()
        Path(cfg['ready']).write_text(json.dumps({'pid':os.getpid(),'url':f'http://127.0.0.1:{sock.getsockname()[1]}'}))
        try: server.run(sockets=[sock])
        finally: sock.close()
        return
    headers = {'Authorization':'Bearer '+cfg['token']}
    if cfg['role'] == 'claim':
        with httpx.Client(base_url=cfg['url'], headers=headers, trust_env=False) as c:
            hb = c.post('/v1/workers/heartbeat', json={'worker':cfg['worker'],'capabilities':cfg['capabilities'],'slots':cfg['slots']})
            hb.raise_for_status()
            claim = c.post('/v1/workers/claim', json={'worker':cfg['worker'],'lease_seconds':cfg['lease_seconds']})
            claim.raise_for_status()
            output.write_text(json.dumps({'pid':os.getpid(),'claim':claim.json()}),encoding='utf-8')
        return
    from gamebuild.worker import work_once
    from .context import Context
    from .scenarios.builds import build
    result_path = Path(cfg['result'])
    def builder(work, attempt, payload, request, identity, cancelled):
        ctx = Context(cfg['run_root'],cfg['case_id'],cfg['variant'],'node',
                      action_id=cfg['action_id']+'/node',cancelled=lambda:cancelled.is_set() or external_stop.is_set())
        result = build(ctx,identity,source=work/'project')
        policy = json.loads((work/'build-policy.json').read_text(encoding='utf-8'))
        configuration = json.loads((work/'project/config.json').read_text(encoding='utf-8'))['mode']
        result['release_gate'] = configuration!='Release' or (policy['required_tests'] and policy['runtime_gate'])
        result['worker_pid'] = os.getpid()
        result_path.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        if (result['compile']['exit_code'] or result['test']['exit_code'] or not result['release_gate']
                or not result['receipt'] or result['runtime']['exit_code']):
            raise RuntimeError('Lab compile/test/runtime/Release gate rejected this input')
        shutil.copytree(ctx.output/'package-payload', payload, dirs_exist_ok=True)
    try:
        artifact = work_once(cfg['url'],cfg['token'],cfg['worker'],Path(cfg['worker_root']),
                             {'lab':Path(cfg['repo'])},lab_builder=builder,slots=cfg.get('slots',1))
        output.write_text(json.dumps({'pid':os.getpid(),'artifact':artifact}),encoding='utf-8')
    except Exception as exc:
        output.write_text(json.dumps({'pid':os.getpid(),'error':type(exc).__name__+': '+str(exc)}),encoding='utf-8')
        raise
    finally:
        watcher_done.set()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('config')
    main(parser.parse_args().config)
