# Resource, cache, process and diagnostic utilities

Task 2 implements the plan's public signatures without an engine or model dependency.

`check_assets(project, max_asset_bytes)` returns `passed` plus `issues` with `rule_id`, relative `path`, `severity`, `message` and `suggestion`. It checks file **and directory** metadata, duplicate/invalid GUIDs, case conflicts, orphan metadata, oversized assets, JSON syntax and forbidden/sensitive paths. It does not edit resources and does not replace Unity's serialized-reference/importer checks.

`environment_report(unity_path=None)` reports OS, architecture, Python, Git, workspace writability, free disk and configured Editor availability. Exact Editor patch is inferred only from a versioned Hub installation path. License and build modules remain `not_checked` until an actual Unity preflight.

`ContentCache(root).key(inputs)` hashes canonical JSON. Include engine, target, importer settings, rule/export-script versions and dependency digests. `Path` values are hashed from actual file bytes; directory dependencies include their recursive file list. Strings remain literal JSON strings, so passing only a dependency filename string cannot invalidate on content changes. `put` supports either a file or a directory. Matching repeat admissions are idempotent; differing bytes under the same key raise `ValueError`. `get` verifies the entire entry, restores via a sibling staging path, and verifies again before exposing the destination. Corruption is quarantined and returns a cold miss. Existing destinations are never intentionally replaced. Symlinks/junctions and paths that recursively contain or write into the cache root are rejected.

`run_process(argv, cwd, log_path, timeout, cancel=None)` runs real argv without a shell. Cancellation accepts a threading Event or zero-argument callback. A reader continuously drains merged stdout/stderr while retaining at most 1 MiB. Results include the required `exit_code`, `timed_out`, `cancelled`, `duration` and additional `log_truncated`/`log_path` evidence. On Windows, the child starts suspended, enters a kill-on-close Job Object, then resumes; descendants therefore cannot race assignment. POSIX uses a new session/process group. All descendants are killed even if the parent has already exited. A missing executable raises the original `OSError`; the caller can classify it as a tool/configuration failure. This module does not log argv or environment values.

`diagnose(log, stage)` returns deterministic categories, redacted evidence, next steps and uncertainty. It does not execute commands or change build gates. `probe_network(host, port, url=None, timeout=2)` returns DNS/TCP/HTTP layer results and first failed layer. HTTP must target the same endpoint, bypasses ambient proxies, does not follow redirects and does not consume response bodies. DNS is isolated behind a bounded wait; HTTP uses a socket-shutdown watchdog to bound slow-trickling headers as well as ordinary response timeout. A blocked native resolver thread is daemonized and may outlive a failed probe; no external resolver process is launched.

## Verification

Run the utility modules independently from the project virtual environment:

```bash
python -m pytest tests/test_checks.py tests/test_cache.py tests/test_runner.py tests/test_diagnostics.py -q
```

These tests exercise real subprocess descendants, filesystem data and local sockets. They do not claim Unity engine coverage. Full integration validation is `python -m pytest -q`; platform and optional tool skips are reported explicitly. Historical module measurements are separate from current checkout results.
