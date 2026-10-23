import time
from fastapi.testclient import TestClient
from gamebuild.lab.api import create_lab_app


def wait(client, rid):
    end = time.monotonic()+25
    while time.monotonic() < end:
        value = client.get('/lab/api/runs/'+rid).json()
        if value['busy_action'] is None: return value
        time.sleep(.05)
    raise AssertionError('action did not complete')


def test_auth_origin_order_and_real_action_roundtrip(tmp_path):
    with TestClient(create_lab_app(tmp_path, 'test-launch-token'), base_url='http://127.0.0.1') as c:
        assert c.get('/lab/api/cases').status_code == 401
        response = c.get('/?access=test-launch-token', follow_redirects=False)
        assert response.status_code == 303 and 'HttpOnly' in response.headers['set-cookie']
        cases = c.get('/lab/api/cases').json()
        assert len(cases) == 16
        body = {'case_id': cases[0]['id'], 'variant': cases[0]['variants'][0]['id']}
        assert c.post('/lab/api/runs', json=body, headers={'Origin':'https://example.org'}).status_code == 403
        r = c.post('/lab/api/runs', json=body).json(); rid = r['id']
        assert c.post(f'/lab/api/runs/{rid}/actions', json={'kind':'verify','request_key':'invalid'}).status_code == 409
        for kind in ['prepare','inject','execute','diagnose','repair','verify']:
            response = c.post(f'/lab/api/runs/{rid}/actions', json={'kind':kind,'request_key':kind})
            assert response.status_code == 202, response.text
            duplicate = c.post(f'/lab/api/runs/{rid}/actions', json={'kind':kind,'request_key':kind})
            assert duplicate.json()['id'] == response.json()['id']
            state = wait(c,rid)
            assert state['actions'][-1]['state'] == 'SUCCEEDED', state['actions'][-1]
        assert state['phase'] == 'verified'
        assert state['actions'][2]['result']['passed'] is False
        assert state['actions'][-1]['result']['passed'] is True
        assert state['events'] and state['evidence']
        e = state['evidence'][0]
        assert c.get(f"/lab/api/runs/{rid}/evidence/{e['id']}").status_code == 200
        assert c.get(f'/lab/api/runs/{rid}/evidence/unknown').status_code == 404
        exported = c.get(f'/lab/api/runs/{rid}/export')
        assert exported.json()['execution_mode'] == 'lab'
        assert 'test-launch-token' not in exported.text
        assert str(tmp_path).replace('\\','\\\\') not in exported.text


def test_cancel_preserves_unfinished_phase_and_can_retry(tmp_path):
    with TestClient(create_lab_app(tmp_path, 'test-launch-token'), base_url='http://127.0.0.1') as c:
        c.get('/?access=test-launch-token',follow_redirects=False)
        case=c.get('/lab/api/cases').json()[0]
        rid=c.post('/lab/api/runs',json={'case_id':case['id'],'variant':case['variants'][0]['id']}).json()['id']
        c.post(f'/lab/api/runs/{rid}/actions',json={'kind':'prepare','request_key':'cancel-me'})
        assert c.post(f'/lab/api/runs/{rid}/cancel').json()['requested'] is True
        run=wait(c,rid)
        assert run['status']=='CANCELLED' and run['phase']=='created'
        assert run['allowed_actions']==['prepare']


def test_invalid_host_and_unknown_cases(tmp_path):
    with TestClient(create_lab_app(tmp_path,'token'),base_url='http://127.0.0.1') as c:
        assert c.get('/health',headers={'Host':'attacker.invalid'}).status_code==403
        c.get('/?access=token',follow_redirects=False)
        assert c.post('/lab/api/runs',json={'case_id':'bad','variant':'bad'}).status_code==422


def test_completed_action_replay_and_export_never_expose_structured_credentials(tmp_path):
    with TestClient(create_lab_app(tmp_path,'token'),base_url='http://127.0.0.1') as c:
        c.get('/?access=token',follow_redirects=False)
        j=c.app.state.service.journal
        r=j.create('09','lease');a,_=j.admit(r['id'],'prepare','same')
        j.finish(a['id'],'SUCCEEDED',{'facts':{'token':'internal-worker-token','path':str(tmp_path/'private')}})
        replay=c.post(f"/lab/api/runs/{r['id']}/actions",json={'kind':'prepare','request_key':'same'})
        assert replay.status_code==202
        assert replay.json()['result']['facts']['token']=='[REDACTED]'
        for url in (f"/lab/api/runs/{r['id']}",f"/lab/api/runs/{r['id']}/export"):
            response=c.get(url)
            assert 'internal-worker-token' not in response.text
            assert '[lab]' in response.text
