"""All advertised Lab variants must reproduce a fault and verify a real repair."""
import json
import os
import pytest

from gamebuild.lab.context import Context
from gamebuild.lab.catalog import CASES
from gamebuild.lab.scenarios import prepare, inject, execute, repair
from gamebuild.lab.scenarios.common import tree_digest

VARIANTS = [(case['id'], variant['id']) for case in CASES for variant in case['variants']]


@pytest.mark.parametrize('case_id,variant', VARIANTS)
def test_every_variant_closes_real_loop(tmp_path, case_id, variant):
    events = []
    def context(action):
        return Context(tmp_path, case_id, variant, action, emit=events.append)
    prepare(context('prepare'))
    inject(context('inject'))
    failed = execute(context('execute'))
    assert failed['passed'] is False, failed
    assert any(not c['passed'] for c in failed['checks'])
    assert failed['fault_signature']['observed'] is True,failed
    before = failed['facts']
    failed_input = tree_digest(tmp_path/'fixture')
    repair(context('repair'))
    assert tree_digest(tmp_path/'fixture') != failed_input
    verified = execute(context('verify'))
    assert verified['passed'] is True, verified
    assert all(c['passed'] for c in verified['checks'])
    assert verified['facts'] != before
    assert verified['execution_mode'] == 'lab'
    assert events and any(e['status'] == 'RUNNING' for e in events)
    if case_id == '04':
        assert verified['facts']['overlap_ms'] > 0
        assert verified['facts']['actual_shas'] == verified['facts']['expected_shas']
        assert len({r['pid'] for r in verified['facts']['receipts']}) == 2
    elif case_id == '07' and variant == 'corruption':
        assert before['quarantined_count'] == 1
        assert before['rounds'][-1]['actual_sha256'] == before['rounds'][-1]['expected_sha256']
    elif case_id == '09':
        assert verified['facts']['target']['state'] == 'succeeded'
        assert not verified['facts']['target']['token']
        assert verified['facts']['worker_result']['receipt']['pid'] != verified['facts']['worker_result']['worker_pid']
        assert verified['facts']['worker_result']['download']['bytes'] > 0
        if variant == 'lease':
            assert [c['attempt'] for c in verified['facts']['claims']] == [1, 2]
            assert verified['facts']['old_report']['status'] == 409
    elif case_id == '10':
        assert before['process']['timed_out' if variant == 'timeout' else 'cancelled'] is True
        assert set(before['pids']) == {'parent', 'child'}
        assert not any(before['pids_alive_after_reap'].values())
        assert before['heartbeat_before'] == before['heartbeat_after']
        assert verified['facts']['repaired_job']['state'] == 'succeeded'
    elif case_id == '14':
        assert before['admission_error']
        assert verified['facts']['final_pointer'] == verified['facts']['baseline_pointer']
        assert verified['facts']['restored']['runtime']['exit_code'] == 0
    elif case_id == '15':
        assert verified['facts']['client_receipt']['pid'] != os.getpid()
        assert verified['facts']['client_receipt']['observed_files'] == verified['facts']['expected_inventory']
    elif case_id == '16':
        assert any(r['status'] == 'BLOCKED' for r in before['targets'])
        assert all(r['status'] == 'SUCCEEDED' for r in verified['facts']['targets'])


def test_runtime_receipt_is_written_by_launched_process(tmp_path):
    ctx = Context(tmp_path, '06', 'missing_asset', 'prepare')
    prepare(ctx)
    inject(ctx)
    result = execute(ctx)
    assert not result['passed']
    assert result['facts']['runtime']['exit_code'] != 0
    assert not result['facts'].get('receipt')
    repair(ctx)
    result = execute(ctx)
    assert result['passed']
    receipt = result['facts']['receipt']
    assert receipt['pid'] != os.getpid()
    assert receipt['asset_loaded'] is True
    assert len(receipt['asset_sha256']) == 64
    assert receipt['build_id'] == result['facts']['identity']['build_id']


def test_cancelled_context_never_executes(tmp_path):
    ctx = Context(tmp_path, '01', 'import', 'prepare', cancelled=lambda: True)
    with pytest.raises(InterruptedError):
        prepare(ctx)


def test_catalog_is_complete_and_explains_boundaries():
    assert [c['id'] for c in CASES] == [f'{i:02}' for i in range(1, 17)]
    for case in CASES:
        assert all(case[key] for key in ('title', 'category', 'role', 'description', 'impact', 'variants', 'diagnosis', 'repair', 'interview', 'boundary'))
        assert len({v['id'] for v in case['variants']}) == len(case['variants'])


@pytest.mark.parametrize('case_id,variant', [('03','text_conflict'),('04','lock')])
def test_git_preparation_can_be_retried(tmp_path,case_id,variant):
    ctx=Context(tmp_path,case_id,variant,'prepare')
    prepare(ctx)
    prepare(ctx)
    assert (tmp_path/'fixture/.git').exists()


def test_unexpected_missing_input_is_an_execution_error(tmp_path):
    ctx=Context(tmp_path,'11','editor','prepare')
    prepare(ctx)
    (ctx.repo/'system-policy.json').unlink()
    with pytest.raises(FileNotFoundError):
        execute(ctx)


def test_worktrees_roundtrip_unicode_paths_across_processes(tmp_path):
    root=tmp_path/'中文实验目录'
    ctx=Context(root,'04','lock','prepare')
    prepare(ctx);inject(ctx)
    assert execute(ctx)['passed'] is False
    repair(ctx)
    result=execute(ctx)
    assert result['passed'] is True
    assert all('中文实验目录' in p for p in result['facts']['directories'])
