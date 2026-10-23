"""Small execution contract shared by independently testable scenarios."""
from contextlib import contextmanager
import difflib
import json
from pathlib import Path
import sys
import time
import uuid

from gamebuild.runner import run_process


def confined(root: Path, relative: str) -> Path:
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or ':' in str(relative):
        raise ValueError('path must remain inside this experiment')
    candidate = root / rel
    for part in [candidate, *candidate.parents]:
        if part == root.parent:
            break
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('linked experiment paths are not allowed')
    if not candidate.resolve().is_relative_to(root):
        raise ValueError('path escapes experiment')
    return candidate


class Context:
    def __init__(self, root, case_id, variant, action, emit=None, cancelled=None, action_id=None):
        self.root = Path(root).resolve()
        self.case_id, self.variant, self.action = case_id, variant, action
        self.repo = self.root / 'fixture'
        self.output = self.root / 'output' / (action_id or action)
        self.repo.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self._emit = emit or (lambda e: None)
        self.cancelled = cancelled or (lambda: False)
        self.started = time.monotonic()

    def record(self, stage, status, message, **data):
        self._emit({'stage': stage, 'status': status, 'message': message,
                    'at': time.time(), 'elapsed_ms': round((time.monotonic()-self.started)*1000, 3),
                    'data': data})

    @contextmanager
    def stage(self, name):
        if self.cancelled():
            raise InterruptedError('experiment cancelled')
        start = time.monotonic()
        self.record(name, 'RUNNING', name)
        try:
            yield
        except Exception as exc:
            self.record(name, 'FAILED', str(exc)[:1200], duration_ms=round((time.monotonic()-start)*1000, 3))
            raise
        else:
            self.record(name, 'SUCCEEDED', name, duration_ms=round((time.monotonic()-start)*1000, 3))

    def write(self, relative, value):
        path = confined(self.repo, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        before = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
        if isinstance(value, bytes):
            path.write_bytes(value)
            after = f'[binary: {len(value)} bytes]'
        else:
            after = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
            path.write_text(after, encoding='utf-8')
        diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          fromfile='before/'+relative, tofile='after/'+relative))
        self.record('文件变更', 'INFO', relative, path=relative, diff=diff[:24000])
        return path

    def read(self, relative):
        path = confined(self.repo, relative)
        text = path.read_text(encoding='utf-8')
        return json.loads(text) if path.suffix == '.json' else text

    def command(self, argv, cwd=None, timeout=10, allow_failure=False, cancel_grace=0):
        cwd = Path(cwd or self.repo).resolve()
        if not cwd.is_relative_to(self.root):
            raise ValueError('command cwd escapes experiment')
        log = self.output / ('command-'+uuid.uuid4().hex[:10]+'.log')
        command = [str(x) for x in argv]
        if Path(command[0]).resolve() == Path(sys.executable).resolve():
            command[1:1] = ['-X', 'utf8']
        requested = None
        def stop():
            nonlocal requested
            if not self.cancelled(): return False
            if requested is None: requested = time.monotonic()
            return time.monotonic()-requested >= cancel_grace
        result = run_process(command, cwd, log, min(timeout, 60), stop)
        result['stdout'] = log.read_text(encoding='utf-8', errors='replace')[:32000]
        result['log_path'] = log.relative_to(self.root).as_posix()
        result['duration_ms'] = round(result['duration']*1000, 3)
        stage = '源码版本' if Path(str(argv[0])).stem == 'git' else '命令执行'
        if 'py_compile' in argv: stage = '源码编译'
        elif any('from app import healthy' in str(x) for x in argv): stage = '行为测试'
        elif any(str(x).endswith('app.py') for x in argv[1:]): stage = '启动验证'
        self.record(stage, 'SUCCEEDED' if result['exit_code'] == 0 else 'FAILED',
                    ' '.join(str(x) for x in argv)[:1500], **result)
        if result['cancelled'] or self.cancelled():
            raise InterruptedError('experiment cancelled')
        if result['exit_code'] != 0 and not allow_failure:
            raise RuntimeError(f"command exited {result['exit_code']}: {result['stdout'][-1600:]}")
        return result

    def git(self, *args, allow_failure=False):
        return self.command(['git', *args], allow_failure=allow_failure)['stdout'].strip()

    def commit(self, message):
        if not (self.repo / '.git').exists():
            self.git('init', '-b', 'main')
        self.git('add', '.')
        self.git('-c', 'user.name=ForgeRail Lab', '-c', 'user.email=lab@example.invalid',
                 'commit', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')

    @staticmethod
    def check(label, passed, expected=None, actual=None):
        return {'label': label, 'passed': bool(passed), 'expected': expected, 'actual': actual}

    def result(self, summary, checks, **facts):
        if not checks:
            raise ValueError('a result requires observed assertions')
        return {'passed': all(c['passed'] for c in checks), 'summary': summary,
                'checks': checks, 'facts': facts, 'execution_mode': 'lab'}
