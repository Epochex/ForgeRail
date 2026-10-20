"""Read-only filesystem preflight; Unity semantic checks remain in the Editor."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile


def check_assets(project: Path, max_asset_bytes=100 * 1024 * 1024) -> dict:
    project = Path(project).resolve()
    assets = project / "Assets"
    issues = []

    def issue(rule, path, message, suggestion):
        issues.append({"rule_id": rule, "path": path.relative_to(project).as_posix(),
                       "severity": "error", "message": message, "suggestion": suggestion})

    if not assets.is_dir():
        issue("missing_assets", assets, "Assets directory is missing", "Select a Unity project root")
        return {"passed": False, "issues": issues}
    guids, names = {}, {}
    # os.walk avoids following symbolic links into unrelated directories.
    paths = []
    for parent, directories, files in os.walk(assets, followlinks=False):
        paths.extend(Path(parent) / name for name in sorted(directories + files))
    for path in sorted(paths):
        relative = path.relative_to(project).as_posix()
        logical = relative[:-5] if relative.endswith(".meta") else relative
        folded = logical.casefold()
        if folded in names and names[folded] != logical:
            issue("case_conflict", path, f"Case conflicts with {names[folded]}", "Use a unique case-insensitive resource name")
        names.setdefault(folded, logical)
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            issue("symlink", path, "Resource links are not allowed", "Keep resources inside the project")
            continue
        if any(part.casefold() in {".git", "node_modules", "library", "temp", "obj", "logs"}
               for part in path.relative_to(assets).parts) or path.name.casefold() in {".env", "credentials.json", "id_rsa", "id_ed25519"} or path.suffix.casefold() in {".pem", ".pfx", ".key"}:
            issue("forbidden_path", path, "Temporary or sensitive content is not allowed in Assets", "Remove it from the resource tree")
        if path.suffix == ".meta":
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                text = ""
            matches = re.findall(r"^guid:\s*([0-9a-fA-F]{32})\s*$", text, re.MULTILINE)
            if len(matches) != 1:
                issue("invalid_guid", path, "Metadata must contain exactly one 32-digit GUID", "Regenerate metadata deliberately in Unity")
            else:
                guid = matches[0].lower()
                if guid in guids:
                    issue("duplicate_guid", path, f"GUID already used by {guids[guid]}", "Assign unique Unity metadata and repair references")
                guids[guid] = relative
            original = path.with_name(path.name[:-5])
            if not original.exists():
                issue("orphan_meta", path, "Metadata has no matching resource", "Restore the resource or remove stale metadata")
            continue
        if not path.with_name(path.name + ".meta").is_file():
            issue("missing_meta", path, "Resource metadata is missing", "Import and commit the generated .meta file")
        if path.is_file():
            if path.stat().st_size > max_asset_bytes:
                issue("asset_too_large", path, "Resource exceeds configured size limit", "Reduce the asset or review the size policy")
            if path.suffix.casefold() == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, ValueError):
                    issue("invalid_json", path, "Configuration is not valid JSON", "Correct the JSON syntax")
    return {"passed": not issues, "issues": issues}


def environment_report(unity_path=None) -> dict:
    """Report availability, never infer license/build-module health from a file."""
    workspace = Path.cwd()
    try:
        with tempfile.TemporaryFile(dir=workspace):
            writable = True
    except OSError:
        writable = False
    git = shutil.which("git")
    git_version = None
    if git:
        try:
            git_version = subprocess.run([git, "--version"], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    editor = Path(unity_path) if unity_path else None
    available = bool(editor and editor.is_file())
    version = None
    # Hub installation layout contains an exact patch; do not launch a licensed Editor.
    if available:
        version = next((part for part in editor.parts if re.fullmatch(r"\d+\.\d+\.\d+[abfp]\d+", part)), None)
    return {"os": platform.platform(), "architecture": platform.machine(), "python": sys.version.split()[0],
            "git": git_version, "disk_free_bytes": shutil.disk_usage(workspace).free,
            "workspace": str(workspace), "workspace_writable": writable,
            "unity": {"available": available, "path": str(editor) if editor else None,
                      "version": version, "license": "not_checked", "build_modules": "not_checked"}}
