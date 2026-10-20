"""Cached filesystem checks; engine semantic validation is always separate."""
import json
from pathlib import Path
import time

from .cache import ContentCache
from .checks import check_assets


def cached_asset_check(project: Path, cache_root: Path, report_path: Path, target: str):
    project, report_path = Path(project), Path(report_path)
    cache = ContentCache(cache_root)
    inputs = {"rules": "asset-preflight-v1", "target": target}
    for name in ("Assets", "ProjectSettings", "Packages"):
        if (project / name).exists(): inputs[name] = project / name
    start = time.monotonic(); key = cache.key(inputs)
    hit = cache.get(key, report_path)
    if hit: result = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        result = check_assets(project)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        cache.put(key, report_path)
    return {**result, "cache_hit": hit, "cache_key": key, "duration": time.monotonic() - start}
