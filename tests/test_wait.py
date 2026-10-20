import pytest
from fastapi.testclient import TestClient
from gamebuild.api import create_app
from gamebuild.cli import wait_job


def test_wait_timeout_revokes_remote_task_before_returning(tmp_path):
    app=create_app(tmp_path,'token'); s=app.state.store
    req=dict(project_id='demo',commit_sha='a'*40,input_digest='b'*64,adapter='lab',target='lab',branch='main')
    j=s.submit(req,'waiting')
    with TestClient(app,headers={'Authorization':'Bearer token'}) as c:
        with pytest.raises(TimeoutError): wait_job(c,j['job_id'],timeout=.01,poll_interval=.005)
    assert s.get(j['job_id'])['state']=='cancelled'
