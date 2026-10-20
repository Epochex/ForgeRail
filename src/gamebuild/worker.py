"""Serial worker. Renewal runs independently from the child build process."""
import json
import os
from pathlib import Path
import sys
import re
import subprocess
import threading
import time

import httpx

from .artifacts import make_package
from .runner import run_process
from .source import SourceManager
from .preflight import cached_asset_check


class NodeLock:
    """A process-held lock prevents two owners from sharing writable engine state."""
    def __init__(self, root):
        self.root = Path(root)

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = (self.root / ".node.lock").open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0: self.file.write(b"0"); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("node workspace already has an executor") from exc
        return self

    def __exit__(self, *args):
        if os.name == "nt":
            import msvcrt
            self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()


def work_once(url, token, worker, root: Path, projects: dict, unity_path=None, lease_seconds=30):
    with NodeLock(root):
        return _work_once(url, token, worker, root, projects, unity_path, lease_seconds)


def _work_once(url, token, worker, root: Path, projects: dict, unity_path=None, lease_seconds=30):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": "Bearer " + token}
    caps = ["lab"] + ['project:'+name for name in projects]
    if unity_path:
        if os.name == 'nt':
            version_result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command','(Get-Item -LiteralPath $env:GAMEBUILD_UNITY_EXE).VersionInfo.ProductVersion'],env={**os.environ,'GAMEBUILD_UNITY_EXE':str(unity_path)},capture_output=True,text=True,timeout=10)
            version_text=version_result.stdout
        else:
            version_text=subprocess.run([str(unity_path),'-version'],capture_output=True,text=True,timeout=10).stdout
        match=re.search(r'\d+\.\d+\.\d+[abfp]\d+',version_text)
        if not match: raise RuntimeError('cannot establish exact installed Unity Editor version')
        caps += ['unity','unity:'+match.group(0),'target:StandaloneWindows64']
    with httpx.Client(base_url=url, headers=headers, timeout=15, trust_env=False) as client:
        def post(path, body):
            r = client.post(path, json=body); r.raise_for_status(); return r.json()
        post("/v1/workers/heartbeat", {"worker": worker, "capabilities": caps})
        job = post("/v1/workers/claim", {"worker": worker, "lease_seconds": lease_seconds})
        if not job: return None
        jid = job["job_id"]; owner = {"worker": worker, "token": job["token"]}
        cancelled = threading.Event(); done = threading.Event()

        def renew():
            while not done.wait(max(0.2, lease_seconds / 3)):
                try:
                    post("/v1/attempts/" + jid + "/renew", {**owner, "seconds": lease_seconds})
                    post("/v1/workers/heartbeat", {"worker": worker, "capabilities": caps})
                except Exception:
                    cancelled.set(); return

        thread = threading.Thread(target=renew, daemon=True); thread.start()
        attempt = root / jid / str(job["attempt"]); payload = attempt / "payload"
        payload.mkdir(parents=True)
        request = job["request"]
        identity = {"build_id": jid, "commit_sha": request["commit_sha"], "input_digest": request["input_digest"], "adapter": request["adapter"]}
        try:
            work = SourceManager(root / "source", projects).prepare(request)
            post("/v1/attempts/" + jid + "/report", {**owner, "state": "building"})
            if request["adapter"] == "lab":
                # A real child reads the checked-out fixture. This is explicitly not a game engine build.
                script = "import pathlib,json,sys,time; p=pathlib.Path(sys.argv[1]); x=json.loads((p/'config.json').read_text()); print(json.dumps({'lab_config':x}),flush=True); time.sleep(max(0,min(60,float(x.get('work_seconds',0)))));"
                result = run_process([sys.executable, "-c", script, str(work)], cwd=work,
                                     log_path=attempt / "build.log", timeout=30, cancel=cancelled)
                if result["exit_code"] != 0: raise RuntimeError("lab child failed")
                (payload / "game.txt").write_text((work / "config.json").read_text(), encoding="utf-8")
                (payload / "build-info.json").write_text(json.dumps(identity), encoding="utf-8")
                (payload / "smoke.json").write_text(json.dumps({**identity, "asset_loaded": True}), encoding="utf-8")
                (payload / "build-report.json").write_text(json.dumps({"result": "Succeeded", "adapter": "lab", "child": result}), encoding="utf-8")
            else:
                if not unity_path: raise RuntimeError("Unity Editor missing")
                project = work / "unity" / "BuildLab"
                preflight = cached_asset_check(project, root / "cache", attempt / "asset-check.json", request["target"])
                if not preflight["passed"]: raise RuntimeError("resource preflight failed; inspect asset-check.json")
                req = attempt / "build-request.json"
                req.write_text(json.dumps({**identity, "output_dir": str(payload), "target": request["target"], "configuration": request.get("configuration", "Development")}), encoding="utf-8")
                result = run_process([str(unity_path), "-batchmode", "-nographics", "-quit", "-projectPath", str(project), "-executeMethod", "GameBuild.BuildEntry.Build", "-buildTarget", "Win64", "-buildRequest", str(req), "-logFile", str(attempt / "unity.log")], cwd=work, log_path=attempt / "build.log", timeout=900, cancel=cancelled)
                if result["exit_code"] != 0: raise RuntimeError("Unity build failed; inspect node log")
                exes = [p for p in (payload / "player").glob("*.exe") if "CrashHandler" not in p.name]
                if len(exes) != 1: raise RuntimeError("expected one Windows Player")
                smoke = run_process([str(exes[0]), "-batchmode", "-nographics", "--smoke-output", str(payload / "smoke.json")], cwd=exes[0].parent, log_path=attempt / "player.log", timeout=60, cancel=cancelled)
                if smoke["exit_code"] != 0: raise RuntimeError("Player smoke failed")
                for name in ("build-info.json", "smoke.json"):
                    p = payload / name; data = json.loads(p.read_text(encoding="utf-8-sig"))
                    if any(data.get(k) != v for k, v in identity.items() if k != "adapter"): raise RuntimeError("Unity runtime identity mismatch")
                    data["adapter"] = "unity"; p.write_text(json.dumps(data), encoding="utf-8")
                p = payload / "build-report.json"; data = json.loads(p.read_text(encoding="utf-8-sig")); data["adapter"] = "unity"; p.write_text(json.dumps(data), encoding="utf-8")
            if cancelled.is_set(): raise RuntimeError("lease revoked or cancellation received")
            post("/v1/attempts/" + jid + "/report", {**owner, "state": "verifying"})
            package = attempt / "package.zip"; manifest = make_package(payload, package, identity)
            with package.open("rb") as f:
                response = client.post("/v1/attempts/" + jid + "/artifact", data={**owner, "manifest": json.dumps(manifest)}, files={"file": ("package.zip", f, "application/zip")}, timeout=120)
                response.raise_for_status()
            return response.json()
        except Exception as exc:
            try: post("/v1/attempts/" + jid + "/report", {**owner, "state": "failed", "detail": type(exc).__name__ + ": " + str(exc)[:500]})
            except Exception: pass
            raise
        finally:
            done.set(); thread.join(timeout=3)
