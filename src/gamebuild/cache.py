"""Immutable content cache with atomic admission and verified cold-miss recovery."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _inventory(source):
    if _linked(source):
        raise ValueError("cache source cannot be a symbolic link")
    if source.is_file():
        return {"kind": "file", "files": [{"path": "payload", "size": source.stat().st_size, "sha256": _digest(source)}], "directories": []}
    if not source.is_dir():
        raise ValueError("cache source does not exist")
    files, directories = [], []
    for parent, dirs, names in os.walk(source, followlinks=False):
        for name in dirs + names:
            path = Path(parent) / name
            if _linked(path):
                raise ValueError("cache source cannot contain symbolic links")
            relative = path.relative_to(source).as_posix()
            if path.is_dir():
                directories.append(relative)
            elif path.is_file():
                files.append({"path": relative, "size": path.stat().st_size, "sha256": _digest(path)})
            else:
                raise ValueError("cache source contains an unsupported file")
    return {"kind": "directory", "files": sorted(files, key=lambda item: item["path"]), "directories": sorted(directories)}


class ContentCache:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, inputs: dict) -> str:
        """Path values are content dependencies; JSON values must include their digests."""
        def normalize(value):
            if isinstance(value, Path):
                return {"dependency": _inventory(value)}
            if isinstance(value, dict):
                if not all(isinstance(key, str) for key in value):
                    raise ValueError("cache input mapping keys must be strings")
                return {key: normalize(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [normalize(item) for item in value]
            return value
        encoded = json.dumps(normalize(inputs), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _entry(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("cache key must be a lowercase SHA256 digest")
        return self.root / key

    def _quarantine(self, entry):
        quarantine = self.root / "quarantine"
        quarantine.mkdir(exist_ok=True)
        try:
            entry.rename(quarantine / (entry.name + "." + uuid.uuid4().hex))
        except FileNotFoundError:
            pass

    def _verify(self, entry, key):
        if not entry.exists() and not entry.is_symlink():
            return None
        try:
            if _linked(entry) or _linked(entry / "manifest.json"):
                raise ValueError("linked cache entry")
            manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
            if set(path.name for path in entry.iterdir()) != {"manifest.json", "data"}:
                raise ValueError("unexpected cache files")
            actual = _inventory(entry / "data")
            if manifest != {"schema_version": 1, "key": key, **actual}:
                raise ValueError("cache content does not match manifest")
            return manifest
        except (OSError, ValueError, TypeError):
            self._quarantine(entry)
            return None

    def put(self, key, source: Path) -> dict:
        entry = self._entry(key)
        source = Path(source)
        if _linked(source):
            raise ValueError("linked cache source")
        source = source.resolve()
        if source == self.root or source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise ValueError("source must not contain or reside in the cache root")
        expected = {"schema_version": 1, "key": key, **_inventory(source)}
        existing = self._verify(entry, key)
        if existing:
            if existing != expected:
                raise ValueError("immutable cache entry already has different contents")
            return existing
        staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.root))
        try:
            if source.is_dir():
                shutil.copytree(source, staging / "data")
            else:
                shutil.copy2(source, staging / "data")
            if {"schema_version": 1, "key": key, **_inventory(staging / "data")} != expected:
                raise ValueError("source changed during cache admission")
            (staging / "manifest.json").write_text(json.dumps(expected, sort_keys=True), encoding="utf-8")
            try:
                staging.rename(entry)
            except OSError:
                existing = self._verify(entry, key)
                if existing != expected:
                    raise ValueError("immutable concurrent cache admission conflict")
            return expected
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def get(self, key, destination: Path) -> bool:
        entry = self._entry(key)
        destination = Path(destination).absolute()
        resolved_destination = destination.resolve()
        if resolved_destination == self.root or resolved_destination.is_relative_to(self.root):
            raise ValueError("destination must not reside in the cache root")
        manifest = self._verify(entry, key)
        if not manifest:
            return False
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".cache-restore-", dir=destination.parent))
        try:
            copy = staging / "payload"
            if manifest["kind"] == "directory":
                shutil.copytree(entry / "data", copy)
            else:
                shutil.copy2(entry / "data", copy)
            # Recheck the copy to catch corruption racing the initial read.
            if {"schema_version": 1, "key": key, **_inventory(copy)} != manifest:
                self._quarantine(entry)
                return False
            copy.rename(destination)
            return True
        except (OSError, ValueError):
            if destination.exists():
                raise FileExistsError(str(destination))
            self._quarantine(entry)
            return False
        finally:
            shutil.rmtree(staging)
