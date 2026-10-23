"""Command-line entrypoints and a real, self-contained HTTP worker experiment."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid
import signal
import threading

import httpx

from .artifacts import verify_package
from .source import snapshot_request, git


def write_report(path, value):
    if path:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def wait_server(url, proc):
    for _ in range(100):
        if proc.poll() is not None: raise RuntimeError("control plane exited before readiness")
        try:
            if httpx.get(url + "/health", timeout=0.5, trust_env=False).is_success: return
        except httpx.HTTPError: pass
        time.sleep(0.1)
    raise RuntimeError("control plane readiness timed out")


def wait_job(client, job_id, timeout=1200, poll_interval=1):
    deadline=time.monotonic()+timeout
    previous=None
    if threading.current_thread() is threading.main_thread():
        previous=signal.getsignal(signal.SIGTERM)
        def terminate(*_): raise KeyboardInterrupt('CI terminated waiting build')
        signal.signal(signal.SIGTERM,terminate)
    try:
        while True:
            r=client.get('/v1/jobs/'+job_id); r.raise_for_status(); value=r.json()
            if value['state'] in ('succeeded','failed','cancelled'): return value
            if time.monotonic()>=deadline: raise TimeoutError('task wait exceeded configured timeout')
            time.sleep(min(poll_interval,max(0,deadline-time.monotonic())))
    except BaseException:
        try: client.post('/v1/jobs/'+job_id+'/cancel',timeout=5).raise_for_status()
        except Exception: pass
        raise
    finally:
        if previous is not None: signal.signal(signal.SIGTERM,previous)


def run_demo(root: Path):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    run = root / ("run-" + uuid.uuid4().hex[:10]); run.mkdir()
    repo = run / "fixture"; repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "config.json").write_text('{"version":1,"branch":"main"}')
    git(repo, "add", ".")
    git(repo, "-c", "user.name=BuildLab", "-c", "user.email=lab@example.invalid", "commit", "-m", "main fixture")
    git(repo, "checkout", "-b", "feature/resource-change")
    (repo / "config.json").write_text('{"version":2,"branch":"feature"}')
    git(repo, "add", ".")
    git(repo, "-c", "user.name=BuildLab", "-c", "user.email=lab@example.invalid", "commit", "-m", "feature fixture")
    git(repo, "checkout", "main")
    requests = [snapshot_request(repo, "demo", "lab", "lab", b) for b in ("main", "feature/resource-change")]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    url = "http://127.0.0.1:" + str(port)
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "GAMEBUILD_TOKEN": token, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    log = (run / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "gamebuild.cli", "serve", "--root", str(run / "control"), "--port", str(port)], env=env, stdout=log, stderr=subprocess.STDOUT)
    workers = []; handles = []
    try:
        wait_server(url, server)
        with httpx.Client(base_url=url, headers={"Authorization": "Bearer " + token}, timeout=15, trust_env=False) as c:
            jobs = []
            for n, request in enumerate(requests):
                r = c.post("/v1/jobs", json={"request": request, "key": "branch-" + str(n)})
                r.raise_for_status(); jobs.append(r.json())
            for n in range(2):
                handle = (run / ("worker-" + str(n) + ".log")).open("w", encoding="utf-8"); handles.append(handle)
                workers.append(subprocess.Popen([sys.executable, "-m", "gamebuild.cli", "worker", "--url", url, "--name", "node-" + str(n), "--root", str(run / ("node-" + str(n))), "--projects", json.dumps({"demo": str(repo)}), "--once"], env=env, stdout=handle, stderr=subprocess.STDOUT))
            for worker in workers:
                if worker.wait(timeout=90) != 0: raise RuntimeError("demo worker failed; inspect worker logs at " + str(run))
            completed = [c.get("/v1/jobs/" + j["job_id"]).json() for j in jobs]
            if any(j["state"] != "succeeded" for j in completed): raise RuntimeError("demo job did not complete")
            # Real bytes downloaded over HTTP, then independently verified and corrupted.
            artifact = c.get("/v1/artifacts/" + completed[0]["artifact_id"]).json()
            z = run / "download.zip"
            z.write_bytes(c.get("/v1/artifacts/" + completed[0]["artifact_id"] + "/download").content)
            verify_package(z, artifact["manifest"])
            z.write_bytes(z.read_bytes() + b"corrupted")
            tamper_rejected = False
            try: verify_package(z, artifact["manifest"])
            except ValueError: tamper_rejected = True
            c.post("/v1/jobs", json={"request": requests[0], "key": "stale"}).raise_for_status()
            c.post("/v1/workers/heartbeat", json={"worker": "expired", "capabilities": ["lab"]}).raise_for_status()
            old = c.post("/v1/workers/claim", json={"worker": "expired", "lease_seconds": 1}).json()
            time.sleep(1.1)
            rejected = c.post("/v1/attempts/" + old["job_id"] + "/report", json={"worker": "expired", "token": old["token"], "state": "building"}).status_code == 409
            c.post("/v1/jobs/" + old["job_id"] + "/cancel")
            audit = c.get("/v1/events").json()
            result = {"status": "passed", "adapter": "lab", "description": "actual HTTP, Git worktrees and two node processes; not a Unity build", "jobs": completed,
                      "stale_report_rejected": rejected, "artifact_tamper_rejected": tamper_rejected,
                      "audit_chain_valid": audit["valid"], "evidence_dir": str(run)}
            if not rejected or not tamper_rejected or not audit["valid"]: raise RuntimeError("negative acceptance failed")
            write_report(run / "result.json", result)
            return result
    finally:
        for proc in workers:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
        if server.poll() is None: server.terminate(); server.wait(timeout=10)
        for handle in handles: handle.close()
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("serve"); p.add_argument("--root", default="runtime/control"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=18765)
    p = commands.add_parser("demo"); p.add_argument("--root", default="runtime/demo"); p.add_argument("--report")
    p = commands.add_parser('lab', help='interactive local game build engineering workbench (no Unity)')
    p.add_argument('--root', default='runtime/interactive-lab')
    p.add_argument('--port', type=int, default=18766)
    p.add_argument('--open', action='store_true', help='open the authenticated local workbench')
    p = commands.add_parser("doctor"); p.add_argument("--unity"); p.add_argument("--report")
    p = commands.add_parser("worker"); p.add_argument("--url", required=True); p.add_argument("--root", default="runtime/node"); p.add_argument("--name", default="windows-1"); p.add_argument("--projects", required=True); p.add_argument("--unity"); p.add_argument("--once", action="store_true")
    p = commands.add_parser("submit"); p.add_argument("--url", required=True); p.add_argument("--project", default="demo"); p.add_argument("--repo", required=True); p.add_argument("--adapter", choices=["lab", "unity"], default="lab"); p.add_argument("--target", default="lab"); p.add_argument("--branch"); p.add_argument("--wait", action="store_true"); p.add_argument('--wait-timeout',type=float,default=1200); p.add_argument("--report"); p.add_argument("--token-env", default="GAMEBUILD_TOKEN")
    for name in ("status", "cancel"):
        p = commands.add_parser(name); p.add_argument("job"); p.add_argument("--url", required=True)
    p = commands.add_parser("release"); p.add_argument("artifact"); p.add_argument("--channel", default="test"); p.add_argument("--url", required=True)
    p = commands.add_parser("report"); p.add_argument("--root", default="runtime/control"); p.add_argument("--output", required=True)
    args = parser.parse_args()
    token = os.environ.get(getattr(args, "token_env", "GAMEBUILD_TOKEN"), "")
    if args.command == 'lab':
        import uvicorn
        import webbrowser
        from .lab.api import create_lab_app
        if not 1024 <= args.port <= 65535: parser.error('lab port must be between 1024 and 65535')
        launch = secrets.token_urlsafe(32)
        url = f'http://127.0.0.1:{args.port}/?access={launch}'
        print('ForgeRail Engineering Lab · local execution · no Unity', flush=True)
        print('Open: '+url, flush=True)
        if args.open:
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        uvicorn.run(create_lab_app(Path(args.root), launch), host='127.0.0.1', port=args.port, access_log=False, log_level='warning')
        return
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(Path(args.root), token), host=args.host, port=args.port, log_level="warning")
        return
    if args.command == "demo": value = run_demo(Path(args.root)); write_report(args.report, value)
    elif args.command == "doctor":
        from .checks import environment_report
        value = environment_report(args.unity); write_report(args.report, value)
    elif args.command == "worker":
        from .worker import work_once
        projects = json.loads(args.projects)
        while True:
            try: value = work_once(args.url, token, args.name, Path(args.root), projects, args.unity)
            except Exception as exc:
                if args.once: raise
                print(json.dumps({'status':'retrying','error':type(exc).__name__}),file=sys.stderr,flush=True)
                time.sleep(1); continue
            if args.once: break
            time.sleep(1)
    elif args.command == "report":
        from .store import Store
        s = Store(Path(args.root)); value = {"jobs": s.jobs(), "audit_valid": s.verify_events(), "events": s.events()}; write_report(args.output, value)
    else:
        with httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=30, trust_env=False) as c:
            if args.command == "submit":
                target = "StandaloneWindows64" if args.adapter == "unity" and args.target == "lab" else args.target
                request = snapshot_request(Path(args.repo), args.project, args.adapter, target, args.branch)
                r = c.post("/v1/jobs", json={"request": request, "key": uuid.uuid4().hex})
                r.raise_for_status(); value = r.json()
                if args.wait: value=wait_job(c,value['job_id'],args.wait_timeout)
                write_report(args.report, value)
            elif args.command == "status": r = c.get("/v1/jobs/" + args.job); r.raise_for_status(); value = r.json()
            elif args.command == "cancel": r = c.post("/v1/jobs/" + args.job + "/cancel"); r.raise_for_status(); value = r.json()
            else: r = c.post("/v1/releases", json={"artifact_id": args.artifact, "channel": args.channel}); r.raise_for_status(); value = r.json()
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    if isinstance(value, dict) and value.get("state") in ("failed", "cancelled"): raise SystemExit(1)


if __name__ == "__main__": main()
