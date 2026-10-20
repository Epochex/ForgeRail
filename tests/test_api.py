import io
import json

from fastapi.testclient import TestClient

from gamebuild.api import create_app


def test_auth_validation_and_cancellation(tmp_path):
    app = create_app(tmp_path, "private-token")
    with TestClient(app) as c:
        assert c.get('/health').status_code == 200
        assert c.get('/v1/jobs').status_code == 401
        h = {'Authorization': 'Bearer private-token'}
        assert c.post('/v1/jobs',headers=h,json={'request':{},'key':'a'}).status_code == 400
        req = dict(project_id='demo',commit_sha='a'*40,input_digest='b'*64,adapter='lab',target='lab',branch='main')
        r = c.post('/v1/jobs',headers=h,json={'request':req,'key':'a'})
        assert r.status_code == 200
        jid = r.json()['job_id']
        assert c.post('/v1/jobs/'+jid+'/cancel',headers=h).json()['state']=='cancelled'
        assert c.get('/v1/jobs/notfound',headers=h).status_code == 404


def test_stale_upload_is_rejected_and_not_published(tmp_path):
    from gamebuild.artifacts import make_package
    app = create_app(tmp_path/'state','token'); s = app.state.store
    req=dict(project_id='demo',commit_sha='a'*40,input_digest='b'*64,adapter='lab',target='lab',branch='main')
    j=s.submit(req,'one'); s.heartbeat('w',['lab']); j=s.claim('w')
    s.cancel(j['job_id'])
    with TestClient(app) as c:
        r=c.post('/v1/attempts/'+j['job_id']+'/artifact',headers={'Authorization':'Bearer token'},
                 files={'file':('a.zip',b'bad','application/zip')},
                 data={'manifest':json.dumps({}), 'worker':'w','token':j['token']})
        assert r.status_code in (400,409)
    assert s.artifacts()==[]
