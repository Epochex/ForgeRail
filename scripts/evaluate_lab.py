"""Run the entire fixed corpus once; archive every invocation, including failures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import uuid

from gamebuild.lab.evaluation import source_fingerprint, summarize_junit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('runtime/interactive-lab'))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    batch_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    target = args.root.resolve() / 'evaluations' / batch_id
    target.mkdir(parents=True)
    xml = target / 'results.xml'
    before = source_fingerprint(repo)
    command = [sys.executable, '-m', 'pytest', 'tests/test_lab_scenarios.py::test_every_variant_closes_real_loop',
               '-q', '--tb=short', f'--junitxml={xml}']
    started = datetime.now(timezone.utc).isoformat()
    # Keep the full raw output; do not silently retry failed samples.
    with (target / 'pytest.log').open('w', encoding='utf-8') as log:
        completed = subprocess.run(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
    if not xml.exists():
        xml.write_text('<testsuite/>', encoding='utf-8')
    summary = summarize_junit(xml)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True).strip())
    report = dict(schema='forgerail-regression-v1', batch_id=batch_id, started_at=started,
                  finished_at=datetime.now(timezone.utc).isoformat(), execution_mode='lab',
                  corpus='authored-41-v1', source_sha256=before, git_head=head, dirty=dirty,
                  source_stable=before == source_fingerprint(repo), exit_code=completed.returncode,
                  environment=dict(os=platform.platform(), python=platform.python_version()),
                  junit_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),
                  command='python -m pytest tests/test_lab_scenarios.py::test_every_variant_closes_real_loop -q --junitxml=results.xml',
                  summary=summary)
    (target / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(batch_id=batch_id, **{k:v for k,v in summary.items() if k!='rows'}), ensure_ascii=False))
    return 0 if summary['passed'] == summary['total'] and report['source_stable'] and completed.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
