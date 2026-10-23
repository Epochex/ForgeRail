import pytest
from gamebuild.lab.store import Journal, LabConflict


def test_action_order_idempotency_and_completed_history(tmp_path):
    journal = Journal(tmp_path)
    run = journal.create('01', 'naming')
    with pytest.raises(LabConflict): journal.admit(run['id'], 'verify', 'early')
    action, created = journal.admit(run['id'], 'prepare', 'same')
    assert created
    assert journal.admit(run['id'], 'prepare', 'same') == (action, False)
    with pytest.raises(LabConflict): journal.admit(run['id'], 'prepare', 'other')
    journal.finish(action['id'], 'SUCCEEDED', {'summary': 'prepared'})
    assert journal.snapshot(run['id'])['phase'] == 'prepared'
    assert journal.snapshot(run['id'])['allowed_actions'] == ['inject']
    assert Journal(tmp_path).snapshot(run['id'])['actions'][0]['result']['summary'] == 'prepared'


def test_recovery_preserves_events_and_cancellation_never_means_verified(tmp_path):
    j = Journal(tmp_path)
    r = j.create('01', 'naming')
    a, _ = j.admit(r['id'], 'prepare', 'first')
    j.event(r['id'], a['id'], {'stage': 'prepare', 'status': 'RUNNING', 'message': 'started'})
    j.recover()
    snapshot = j.snapshot(r['id'])
    assert snapshot['status'] == 'INTERRUPTED'
    assert snapshot['phase'] == 'created' and snapshot['busy_action'] is None
    assert snapshot['events'][0]['message'] == 'started'
    assert snapshot['actions'][0]['state'] == 'INTERRUPTED'


def test_two_run_capacity_and_unknown_evidence(tmp_path):
    j = Journal(tmp_path)
    runs = [j.create('01', 'naming') for _ in range(3)]
    for r in runs[:2]: j.admit(r['id'], 'prepare', 'start')
    with pytest.raises(LabConflict): j.admit(runs[2]['id'], 'prepare', 'start')
    with pytest.raises(KeyError): j.evidence(runs[0]['id'], '../outside')
