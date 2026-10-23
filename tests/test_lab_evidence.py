import hashlib
import json
import pytest
from gamebuild.lab.context import Context
from gamebuild.lab.store import Journal, LabConflict


def test_evidence_hash_detects_later_mutation_and_cannot_cross_run(tmp_path):
    journal=Journal(tmp_path)
    run=journal.create('13','zip')
    action,_=journal.admit(run['id'],'prepare','prepare')
    output=journal.run_root(run['id'])/'output'/action['id']
    output.mkdir(parents=True)
    report=output/'proof.json'
    report.write_text('{"observed": 17}')
    journal.register_evidence(run['id'],action['id'])
    item=journal.snapshot(run['id'])['evidence'][0]
    metadata,path=journal.evidence(run['id'],item['id'])
    assert json.loads(path.read_text())=={'observed':17}
    other=journal.create('13','zip')
    with pytest.raises(KeyError): journal.evidence(other['id'],item['id'])
    report.write_text('{"observed": 18}')
    assert json.loads(journal.evidence(run['id'],item['id'])[1].read_text())=={'observed':17}
    path.write_text('{"observed": 19}')
    with pytest.raises(LabConflict,match='changed'): journal.evidence(run['id'],item['id'])


def test_evidence_path_traversal_is_rejected_even_if_database_is_corrupted(tmp_path):
    journal=Journal(tmp_path/'lab')
    run=journal.create('13','zip')
    with journal.connection(True) as c:
        c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',('malicious',run['id'],'a','../../outside',1,'a'*64))
    with pytest.raises(ValueError): journal.evidence(run['id'],'malicious')


def test_context_commands_cancel_before_launch_and_write_no_success_receipt(tmp_path):
    import sys
    ctx=Context(tmp_path,'10','cancel','execute',cancelled=lambda:True)
    with pytest.raises(InterruptedError):
        ctx.command([sys.executable,'-c','print("should not execute")'])
    assert not list(tmp_path.rglob('receipt.json'))
