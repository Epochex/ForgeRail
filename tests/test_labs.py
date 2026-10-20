import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    path = ROOT / 'labs' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_dedup_persists_across_restart_and_shadow_isolation(tmp_path):
    ledger = load('ledger')
    a = ledger.Ledger(tmp_path / 'stable.sqlite')
    assert a.apply({'id': 'a', 'value': 7}, 0)
    assert not ledger.Ledger(tmp_path / 'stable.sqlite').apply({'id': 'a', 'value': 7}, 0)
    shadow = ledger.Ledger(tmp_path / 'shadow.sqlite')
    assert shadow.apply({'id': 'a', 'value': 99}, 0)
    assert a.summary() == {'unique': 1, 'total': 7, 'checkpoint': 0}
    assert shadow.summary()['total'] == 99

def test_runtime_rejects_wrong_image_and_configuration():
    acceptance = load('acceptance')
    expected = {'role':'core', 'sha':'a'*40, 'config':'v1'}
    assert acceptance.identity_matches(expected, expected, 'sha256:one', 'sha256:one')
    assert not acceptance.identity_matches(expected, expected, 'sha256:two', 'sha256:one')
    assert not acceptance.identity_matches(dict(expected, config='v2'), expected, 'same', 'same')

def test_required_evidence_missing_is_failure(tmp_path):
    acceptance = load('acceptance')
    result = acceptance.verify_evidence(tmp_path)
    assert result['status'] == 'failed'
    assert {'images', 'runtime', 'messaging', 'jenkins'} == set(result['missing'])

def test_failed_report_does_not_pass_evidence_gate(tmp_path):
    import json
    acceptance = load('acceptance')
    for name in ['images','runtime','messaging','jenkins']:
        (tmp_path/(name+'.json')).write_text(json.dumps({'status':'failed' if name=='runtime' else 'passed'}))
    result=acceptance.verify_evidence(tmp_path)
    assert result['status']=='failed'
    assert result['invalid']==['runtime']
