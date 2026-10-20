"""Only registered repositories and managed worktrees may supply build input."""
import hashlib
import json
from pathlib import Path
import subprocess
import re
import shutil


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return r.stdout.decode("utf-8", errors="replace").strip()


def input_digest(repo, request):
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", request["commit_sha"]],
                             check=True, capture_output=True).stdout
    config = {k: v for k, v in request.items() if k not in ("input_digest", "branch")}
    return hashlib.sha256(archive + json.dumps(config, sort_keys=True).encode()).hexdigest()


def snapshot_request(repo: Path, project: str, adapter: str, target: str, branch=None):
    repo = Path(repo).resolve()
    if git(repo, "status", "--porcelain"): raise ValueError("source repository must be clean; commit source first")
    sha = git(repo, "rev-parse", branch or "HEAD")
    request = {"project_id": project, "adapter": adapter, "target": target,
               "branch": branch or git(repo, "branch", "--show-current") or "detached",
               "commit_sha": sha, "configuration": "Release", "build_script_version": "1"}
    if adapter == 'unity':
        text=git(repo,'show',sha+':unity/BuildLab/ProjectSettings/ProjectVersion.txt')
        match=re.search(r'm_EditorVersion:\s*(\S+)',text)
        if not match: raise ValueError('Unity project has no pinned Editor version')
        request['unity_version']=match.group(1)
    request["input_digest"] = input_digest(repo, request)
    return request


class SourceManager:
    def __init__(self, root: Path, projects: dict):
        self.root = Path(root).resolve(); self.projects = projects
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self, request):
        project = request["project_id"]
        if project not in self.projects: raise ValueError("project is not registered on node")
        origin = Path(self.projects[project]).resolve()
        key = hashlib.sha256(json.dumps([project, request.get("branch"), request["target"]]).encode()).hexdigest()[:20]
        mirror = self.root / ("repo-" + hashlib.sha256(project.encode()).hexdigest()[:16])
        if not mirror.exists():
            subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout", str(origin), str(mirror)], check=True, capture_output=True)
        git(mirror, "fetch", "origin", request["commit_sha"])
        if input_digest(mirror, request) != request["input_digest"]: raise ValueError("source input digest mismatch")
        work = self.root / ("work-" + key)
        if not work.resolve().is_relative_to(self.root): raise ValueError('workspace escapes managed root')
        if work.exists(): git(work, "reset", "--hard", request["commit_sha"])
        else: git(mirror, "worktree", "add", "--detach", str(work), request["commit_sha"])
        if git(work, "rev-parse", "HEAD") != request["commit_sha"]: raise ValueError("worktree commit mismatch")
        # Retain engine Library, but clear only explicitly declared generated assets.
        for relative in ('Assets/Generated','Assets/Generated.meta','Assets/StreamingAssets/GameBuild','Assets/StreamingAssets/GameBuild.meta','Assets/__GameBuildAcceptance','Assets/__GameBuildAcceptance.meta'):
            generated=work/'unity/BuildLab'/relative
            if generated.exists() or generated.is_symlink():
                if not generated.resolve().is_relative_to(work): raise ValueError('generated path escapes managed workspace')
                if generated.is_dir() and not generated.is_symlink(): shutil.rmtree(generated)
                else: generated.unlink()
        streaming=work/'unity/BuildLab/Assets/StreamingAssets'
        if streaming.is_dir() and not any(streaming.iterdir()) and not git(work,'ls-files','unity/BuildLab/Assets/StreamingAssets','unity/BuildLab/Assets/StreamingAssets.meta'):
            streaming.rmdir(); streaming.with_name('StreamingAssets.meta').unlink(missing_ok=True)
        extras=git(work,'ls-files','--others','--exclude-standard')
        if extras: raise ValueError('untracked execution input in managed worktree; freeze project settings and sources first')
        if git(work,'status','--porcelain','--untracked-files=no'): raise ValueError('managed source differs from fixed commit')
        ignored=git(work,'ls-files','--others','--ignored','--exclude-standard').splitlines()
        allowed=('unity/BuildLab/Library/','unity/BuildLab/Temp/','unity/BuildLab/Obj/','unity/BuildLab/Logs/','unity/BuildLab/UserSettings/')
        for name in ignored:
            if name.startswith(allowed) or name=='unity/BuildLab/Assets/StreamingAssets.meta' or (name.startswith('unity/BuildLab/') and name.endswith(('.csproj','.sln'))): continue
            raise ValueError('untracked ignored input outside declared engine cache')
        return work
