"""Immutable packages. Validation never extracts an untrusted ZIP."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile
import re

MAX_BYTES = 1024 ** 3
FORBIDDEN = {".git", ".env", "node_modules", ".venv", "Library", "Temp", "credentials.json"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def safe_name(name: str) -> None:
    p = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or p.is_absolute()
            or ".." in p.parts or any(x in FORBIDDEN for x in p.parts)
            or name != p.as_posix() or name.endswith("/")):
        raise ValueError("unsafe or forbidden package path")
    reserved={'con','prn','aux','nul'}|{'com'+str(i) for i in range(1,10)}|{'lpt'+str(i) for i in range(1,10)}
    for part in p.parts:
        if (part.endswith((' ','.')) or part.split('.')[0].casefold() in reserved or part.casefold() in {x.casefold() for x in FORBIDDEN}
                or part.casefold().startswith('.env') or part.casefold().endswith(('.pem','.pfx','.key'))):
            raise ValueError('nonportable or sensitive package path')


def make_package(directory: Path, output: Path, identity: dict) -> dict:
    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.is_relative_to(directory): raise ValueError("output must be outside payload")
    files = []
    for p in sorted(directory.rglob("*")):
        if p.is_symlink(): raise ValueError("symlink in package")
        if not p.is_file(): continue
        name = p.relative_to(directory).as_posix(); safe_name(name)
        files.append({"path": name, "size": p.stat().st_size, "sha256": digest(p)})
    if not files or sum(x["size"] for x in files) > MAX_BYTES: raise ValueError("invalid package size")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for entry in files: z.write(directory / entry["path"], entry["path"])
    return {**identity, "schema_version": 1, "files": files, "size": output.stat().st_size, "sha256": digest(output)}


def verify_package(package: Path, manifest: dict) -> dict:
    package = Path(package)
    if (not isinstance(manifest,dict) or type(manifest.get('size')) is not int
            or not isinstance(manifest.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',manifest['sha256'])):
        raise ValueError('malformed package manifest')
    if package.stat().st_size > MAX_BYTES or package.stat().st_size != manifest.get("size"):
        raise ValueError("package size mismatch")
    if digest(package) != manifest.get("sha256"): raise ValueError("package checksum mismatch")
    expected = manifest.get("files", [])
    if not isinstance(expected,list) or not expected or len(expected) > 100000: raise ValueError("invalid file manifest")
    for item in expected:
        if (not isinstance(item,dict) or not isinstance(item.get('path'),str) or type(item.get('size')) is not int or item['size']<0
                or not isinstance(item.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',item['sha256'])):
            raise ValueError('malformed file manifest')
    paths = [x["path"] for x in expected]
    if len(paths) != len(set(x.casefold() for x in paths)): raise ValueError("duplicate package path")
    for name in paths: safe_name(name)
    with zipfile.ZipFile(package) as z:
        infos = z.infolist()
        if len(infos) != len(expected) or set(z.namelist()) != set(paths): raise ValueError("file inventory mismatch")
        if sum(x.file_size for x in infos) > MAX_BYTES: raise ValueError("expanded size limit exceeded")
        for item in expected:
            info = z.getinfo(item["path"])
            if stat.S_ISLNK(info.external_attr >> 16): raise ValueError("ZIP symlink rejected")
            if info.file_size != item["size"]: raise ValueError("file size mismatch")
            h = hashlib.sha256()
            with z.open(info) as f:
                for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
            if h.hexdigest() != item["sha256"]: raise ValueError("file checksum mismatch")
        if "build-info.json" in paths:
            if z.getinfo("build-info.json").file_size > 65536: raise ValueError("identity too large")
            info = json.loads(z.read("build-info.json"))
            if not isinstance(info,dict): raise ValueError('malformed embedded identity')
            for key in ("build_id", "commit_sha", "input_digest", "adapter"):
                if key in manifest and info.get(key) != manifest[key]: raise ValueError("embedded identity mismatch")
    return manifest
