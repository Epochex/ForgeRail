from gamebuild.lab.runner import perform
from gamebuild.lab.store import Journal


def action(journal,rid,kind,key):
    value,_=journal.admit(rid,kind,key)
    perform(journal.root,value['id'])
    import json
    result=json.loads((journal.run_root(rid)/'output'/value['id']/'outcome.json').read_text(encoding='utf-8'))
    return value,result


def finish(journal,value,result):
    journal.finish(value['id'],result['state'],result.get('result'),result.get('error'))


def test_interrupted_rename_can_retry_without_reapplying_partial_mutation(tmp_path):
    j=Journal(tmp_path);run=j.create('01','naming')
    a,result=action(j,run['id'],'prepare','prepare');finish(j,a,result)
    a,result=action(j,run['id'],'inject','lost-response')
    assert result['state']=='SUCCEEDED'
    j.recover()
    a,result=action(j,run['id'],'inject','retry')
    assert result['state']=='SUCCEEDED',result
    finish(j,a,result)
    assert j.snapshot(run['id'])['phase']=='injected'


def test_wrong_failure_does_not_count_as_missing_resource_reproduction(tmp_path):
    j=Journal(tmp_path);run=j.create('06','missing_asset')
    for kind in ('prepare','inject'):
        a,result=action(j,run['id'],kind,kind);finish(j,a,result)
    (j.run_root(run['id'])/'fixture/project/app.py').write_text('invalid syntax (',encoding='utf-8')
    a,result=action(j,run['id'],'execute','wrong-failure')
    assert result['state']=='FAILED',result
    assert '指定故障' in result['error']
