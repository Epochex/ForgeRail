import concurrent.futures
import json
from pathlib import Path

import pytest

from gamebuild.store import Store, Conflict
from gamebuild.artifacts import make_package


def request(**kw):
    return dict(project_id="demo", commit_sha="a" * 40, input_digest="b" * 64,
                adapter="lab", target="lab", branch="main", **kw)


def owned(tmp_path):
    now = [1000.0]
    store = Store(tmp_path / "state", clock=lambda: now[0])
    job = store.submit(request(), "once")
    store.heartbeat("node", ["lab"])
    return store, store.claim("node", 10), now


def test_idempotency_survives_restart_and_conflicting_input_is_rejected(tmp_path):
    s = Store(tmp_path)
    a = s.submit(request(), "key")
    assert Store(tmp_path).submit(request(), "key")["job_id"] == a["job_id"]
    changed = request(); changed["commit_sha"] = "c" * 40
    with pytest.raises(Conflict):
        s.submit(changed, "key")


@pytest.mark.parametrize('field,value',[('commit_sha',None),('commit_sha',[]),('input_digest',42),('project_id',{})])
def test_malformed_identity_has_controlled_validation_error(tmp_path,field,value):
    r=request(); r[field]=value
    with pytest.raises(ValueError): Store(tmp_path).submit(r,'bad')


def test_only_one_concurrent_claim_and_capability_filter(tmp_path):
    s = Store(tmp_path)
    s.submit(request(), "one")
    s.heartbeat("bad", ["android"])
    assert s.claim("bad") is None
    for n in range(8): s.heartbeat(str(n), ["lab"])
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        claimed = list(pool.map(lambda n: s.claim(str(n)), range(8)))
    assert len([x for x in claimed if x]) == 1


def test_slot_limit_prevents_second_claim(tmp_path):
    s = Store(tmp_path)
    s.heartbeat("n", ["lab"], slots=1)
    s.submit(request(), "a"); s.submit(request(), "b")
    assert s.claim("n")
    assert s.claim("n") is None


def test_unity_claim_requires_exact_engine_and_target_capabilities(tmp_path):
    s=Store(tmp_path)
    r=request(); r.update(adapter='unity',target='StandaloneWindows64',unity_version='6000.3.0f1')
    s.submit(r,'unity')
    s.heartbeat('wrong',['unity','unity:6000.2.0f1','target:StandaloneWindows64'])
    assert s.claim('wrong') is None
    s.heartbeat('correct',['unity','unity:6000.3.0f1','target:StandaloneWindows64'])
    assert s.claim('correct')['request']['unity_version']=='6000.3.0f1'


def test_expired_worker_cannot_report_or_renew_and_fresh_attempt_differs(tmp_path):
    s, old, now = owned(tmp_path)
    now[0] += 11
    with pytest.raises(Conflict): s.renew(old["job_id"], "node", old["token"])
    new = s.claim("node", 10)
    assert new["attempt"] == 2 and new["token"] != old["token"]
    with pytest.raises(Conflict): s.report(old["job_id"], "node", old["token"], "building")


def test_attempts_are_bounded_and_cancelled_owner_cannot_report(tmp_path):
    s, job, now = owned(tmp_path)
    now[0] += 11
    second = s.claim("node", 10)
    now[0] += 11
    assert s.claim("node") is None
    assert s.get(job["job_id"])["state"] == "failed"
    j = s.submit(request(), "another"); active = s.claim("node")
    assert s.cancel(j["job_id"])["state"] == "cancelled"
    with pytest.raises(Conflict): s.report(active["job_id"], "node", active["token"], "building")


def test_stage_order_and_event_chain_are_enforced(tmp_path):
    s, j, _ = owned(tmp_path)
    with pytest.raises(Conflict): s.report(j["job_id"], "node", j["token"], "succeeded")
    s.report(j["job_id"], "node", j["token"], "building")
    s.report(j["job_id"], "node", j["token"], "verifying")
    assert s.verify_events()
    events = s.events(j["job_id"])
    assert [e["kind"] for e in events][:2] == ["submitted", "claimed"]


def package(tmp_path, job):
    d = tmp_path / (job["job_id"] + "-payload"); d.mkdir()
    identity = dict(build_id=job["job_id"], commit_sha=job["request"]["commit_sha"],
                    input_digest=job["request"]["input_digest"], adapter="lab")
    (d / "build-info.json").write_text(json.dumps(identity))
    (d / "smoke.json").write_text(json.dumps({**identity, "asset_loaded": True}))
    (d / "build-report.json").write_text(json.dumps({"result": "Succeeded", "adapter": "lab"}))
    (d / "game.txt").write_text("actual lab file")
    p = tmp_path / (job["job_id"] + ".zip")
    return p, make_package(d, p, identity)


def finish(s, j, tmp_path):
    s.report(j["job_id"], "node", j["token"], "building")
    s.report(j["job_id"], "node", j["token"], "verifying")
    p, manifest = package(tmp_path, j)
    return s.commit_artifact(j["job_id"], "node", j["token"], p, manifest)


def test_artifact_identity_mismatch_rejected_and_success_is_immutable(tmp_path):
    s, j, _ = owned(tmp_path)
    s.report(j["job_id"], "node", j["token"], "building")
    s.report(j["job_id"], "node", j["token"], "verifying")
    p, manifest = package(tmp_path, j)
    bad = {**manifest, "commit_sha": "f" * 40}
    with pytest.raises((ValueError, Conflict)): s.commit_artifact(j["job_id"], "node", j["token"], p, bad)
    a = s.commit_artifact(j["job_id"], "node", j["token"], p, manifest)
    assert s.get(j["job_id"])["state"] == "succeeded"
    with pytest.raises(Conflict): s.commit_artifact(j["job_id"], "node", j["token"], p, manifest)
    assert Path(a["path"]).is_file()
    assert Store(s.root).get(j["job_id"])["artifact_id"] == a["artifact_id"]


def test_cancelled_and_expired_artifact_uploads_cannot_commit(tmp_path):
    s, j, now = owned(tmp_path)
    s.report(j["job_id"], "node", j["token"], "building")
    s.report(j["job_id"], "node", j["token"], "verifying")
    p, manifest = package(tmp_path, j)
    now[0] += 11
    with pytest.raises(Conflict): s.commit_artifact(j["job_id"], "node", j["token"], p, manifest)
    assert not s.artifacts()


def test_release_windows_and_rollback_restore_previous_pointer(tmp_path):
    s, j, now = owned(tmp_path)
    def validate(r, a):
        import zipfile
        with zipfile.ZipFile(a['path']) as z: receipt=json.loads(z.read('smoke.json'))
        for phase in ('shadow','canary'):
            for n in range(2):
                worker='validator-'+str(n); s.heartbeat(worker,['validate'])
                s.observe(r['release_id'],worker,phase+str(n),a['artifact_id'],a['manifest']['sha256'],receipt)
                now[0]+=1.1
            s.advance(r['release_id'],True)
    a = finish(s, j, tmp_path)
    r1 = s.release(a["artifact_id"], "test")
    assert r1["phase"] == "shadow"
    with pytest.raises(Conflict): s.advance(r1["release_id"], False)
    validate(r1,a)
    b = s.submit(request(), "second"); b = s.claim("node")
    a2 = finish(s, b, tmp_path)
    r2 = s.release(a2["artifact_id"], "test")
    validate(r2,a2)
    assert s.channel("test")["artifact_id"] == a2["artifact_id"]
    s.rollback(r2["release_id"])
    assert s.channel("test")["artifact_id"] == a["artifact_id"]


def test_boolean_approval_cannot_replace_bound_validation_observations(tmp_path):
    s,j,_=owned(tmp_path); a=finish(s,j,tmp_path); r=s.release(a['artifact_id'],'test')
    with pytest.raises(Conflict): s.advance(r['release_id'],True)


def test_failed_release_observation_is_audited_and_prevents_promotion(tmp_path):
    s,j,_=owned(tmp_path); a=finish(s,j,tmp_path); r=s.release(a['artifact_id'],'test')
    s.heartbeat('validator',['validate'])
    receipt={'asset_loaded':False}
    result=s.observe(r['release_id'],'validator','failed-run',a['artifact_id'],a['manifest']['sha256'],receipt)
    assert result['passed'] is False
    with pytest.raises(Conflict): s.advance(r['release_id'],True)
    assert s.channel('test')['artifact_id'] is None
    assert any(e['kind']=='release_validation_failed' for e in s.events())


def test_orphan_blob_does_not_become_a_published_artifact(tmp_path):
    s = Store(tmp_path)
    (s.root / "blobs" / ("a" * 64 + ".zip")).write_bytes(b"incomplete")
    assert s.artifacts() == []
    assert Store(tmp_path).artifacts() == []


def test_database_failure_after_blob_admission_can_retry_without_partial_success(tmp_path):
    import sqlite3
    s, j, _ = owned(tmp_path)
    s.report(j['job_id'],'node',j['token'],'building')
    s.report(j['job_id'],'node',j['token'],'verifying')
    p,m=package(tmp_path,j)
    with sqlite3.connect(s.db) as c:
        c.execute("CREATE TRIGGER crash_before_artifact BEFORE INSERT ON artifacts BEGIN SELECT RAISE(ABORT,'simulated crash'); END")
    with pytest.raises(sqlite3.IntegrityError): s.commit_artifact(j['job_id'],'node',j['token'],p,m)
    restarted=Store(s.root,clock=s.clock)
    assert restarted.get(j['job_id'])['state']=='verifying'
    assert restarted.artifacts()==[]
    assert len(list((s.root/'blobs').glob('*.zip')))==1
    with sqlite3.connect(s.db) as c: c.execute('DROP TRIGGER crash_before_artifact')
    a=restarted.commit_artifact(j['job_id'],'node',j['token'],p,m)
    assert restarted.get(j['job_id'])['artifact_id']==a['artifact_id']
    assert len(restarted.artifacts())==1


def test_unity_actual_engine_report_must_match_pinned_version(tmp_path):
    s=Store(tmp_path/'state')
    r=request(); r.update(adapter='unity',target='StandaloneWindows64',unity_version='6000.3.0f1')
    s.submit(r,'unity')
    s.heartbeat('node',['unity','unity:6000.3.0f1','target:StandaloneWindows64']); j=s.claim('node')
    s.report(j['job_id'],'node',j['token'],'building'); s.report(j['job_id'],'node',j['token'],'verifying')
    d=tmp_path/'payload'; d.mkdir()
    identity={'build_id':j['job_id'],'commit_sha':r['commit_sha'],'input_digest':r['input_digest'],'adapter':'unity'}
    (d/'build-info.json').write_text(json.dumps({**identity,'unity_version':'6000.2.0f1'}))
    (d/'smoke.json').write_text(json.dumps({**identity,'asset_loaded':True}))
    (d/'build-report.json').write_text(json.dumps({'result':'Succeeded','adapter':'unity','unity_version':'6000.2.0f1'}))
    p=tmp_path/'payload.zip'; m=make_package(d,p,identity)
    with pytest.raises(ValueError): s.commit_artifact(j['job_id'],'node',j['token'],p,m)
