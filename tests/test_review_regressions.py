import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamebuild.api import create_app
from gamebuild.source import SourceManager, snapshot_request, git
from gamebuild.artifacts import make_package
from gamebuild.store import Store


def test_reused_snapshot_rejects_untracked_execution_inputs(tmp_path):
    repo=tmp_path/'repo'; repo.mkdir(); git(repo,'init','-b','main')
    (repo/'config.json').write_text('{}'); git(repo,'add','.')
    git(repo,'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','fixture')
    req=snapshot_request(repo,'demo','lab','lab'); manager=SourceManager(tmp_path/'node',{'demo':str(repo)})
    work=manager.prepare(req); (work/'extra.cs').write_text('untracked input')
    with pytest.raises(ValueError,match='untracked'): manager.prepare(req)


@pytest.mark.parametrize('url,body',[
    ('/v1/workers/heartbeat',{'worker':7,'capabilities':['lab']}),
    ('/v1/workers/heartbeat',{'worker':'node','capabilities':None}),
    ('/v1/workers/claim',{'worker':'node','lease_seconds':'thirty'}),
    ('/v1/releases',{'artifact_id':'a','channel':1}),
])
def test_api_rejects_malformed_fields_without_500_or_poisoned_workers(tmp_path,url,body):
    with TestClient(create_app(tmp_path,'token')) as c:
        response=c.post(url,json=body,headers={'Authorization':'Bearer token'})
        assert response.status_code in (400,422)


@pytest.mark.parametrize('wrong',['target','configuration','status','bundle','report_identity','missing_player'])
def test_unity_admission_binds_complete_receipt_and_expected_payload(tmp_path,wrong):
    import hashlib
    s=Store(tmp_path/'state')
    req=dict(project_id='demo',commit_sha='a'*40,input_digest='b'*64,adapter='unity',target='StandaloneWindows64',branch='main',configuration='Development',unity_version='6000.3.0f1')
    s.submit(req,'unity'); s.heartbeat('node',['unity','unity:6000.3.0f1','target:StandaloneWindows64']); j=s.claim('node')
    s.report(j['job_id'],'node',j['token'],'building'); s.report(j['job_id'],'node',j['token'],'verifying')
    d=tmp_path/'payload'; d.mkdir()
    bundle=b'controlled bundle bytes'; sha=hashlib.sha256(bundle).hexdigest()
    identity=dict(build_id=j['job_id'],commit_sha=req['commit_sha'],input_digest=req['input_digest'],adapter='unity',unity_version=req['unity_version'],target=req['target'],configuration=req['configuration'],bundle_sha256=sha,config_sha256='c'*64)
    info=dict(identity); smoke={**identity,'status':'passed','asset_loaded':True}; report={**identity,'result':'Succeeded','status':'passed','resource_inputs':[{'path':'Assets/BundleSource/demo-config.json','sha256':'c'*64}]}
    if wrong=='target': info['target']='Android'
    if wrong=='configuration': smoke['configuration']='Release'
    if wrong=='status': smoke['status']='failed'
    if wrong=='bundle': smoke['bundle_sha256']='d'*64
    if wrong=='report_identity': report['build_id']='another-build'
    (d/'build-info.json').write_text(json.dumps(info)); (d/'smoke.json').write_text(json.dumps(smoke)); (d/'build-report.json').write_text(json.dumps(report))
    (d/'bundles').mkdir(); (d/'bundles/demo').write_bytes(bundle)
    player=d/'player'; player.mkdir()
    if wrong!='missing_player': (player/'GameBuildLab.exe').write_bytes(b'MZfixture')
    embedded=player/'GameBuildLab_Data/StreamingAssets/GameBuild'; embedded.mkdir(parents=True)
    (embedded/'demo').write_bytes(bundle); (embedded/'build-info.json').write_text(json.dumps(identity))
    p=tmp_path/'payload.zip'; manifest=make_package(d,p,identity)
    with pytest.raises(ValueError): s.commit_artifact(j['job_id'],'node',j['token'],p,manifest)
