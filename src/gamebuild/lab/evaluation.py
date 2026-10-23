"""Fixed, authored regression corpus. Never infer a score from demo history."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from .catalog import CASES


def source_fingerprint(repo):
    repo = Path(repo)
    paths = sorted([*repo.glob('src/gamebuild/**/*.py'),
                    *repo.glob('tests/test_lab*.py'),
                    *repo.glob('tests/conftest.py'),
                    *repo.glob('scripts/evaluate_lab.py'),
                    *repo.glob('pyproject.toml'), *repo.glob('uv.lock'),
                    *repo.glob('requirements.lock')])
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(repo).as_posix().encode())
        digest.update(b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def summarize_junit(path):
    nodes = list(ET.parse(path).getroot().iter('testcase'))
    rows = []
    for case in CASES:
        for variant in case['variants']:
            key = f"{case['id']}-{variant['id']}"
            matches = [n for n in nodes if n.get('name') == f'test_every_variant_closes_real_loop[{key}]']
            state, reason, seconds = 'missing', '未执行或未生成结果', 0
            if len(matches) > 1:
                state, reason = 'invalid', '重复结果，不能选择其中一次计分'
            elif matches:
                node = matches[0]
                seconds = float(node.get('time', 0))
                state, reason = 'passed', ''
                for tag, status in [('skipped', 'skipped'), ('failure', 'failed'), ('error', 'failed')]:
                    child = node.find(tag)
                    if child is not None:
                        state, reason = status, child.get('message', '')[:500]
            rows.append(dict(case_id=case['id'], variant=variant['id'], label=variant['label'],
                             status=state, reason=reason, seconds=seconds))
    counts = {status: sum(r['status'] == status for r in rows)
              for status in ('passed', 'failed', 'skipped', 'missing', 'invalid')}
    return dict(total=len(rows), rate=counts['passed']/len(rows), rows=rows, **counts)
