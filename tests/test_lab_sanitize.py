import json
from gamebuild.lab.sanitize import clean, clean_text
from gamebuild.lab.store import Journal


def test_recursive_json_and_escaped_windows_paths_are_redacted(tmp_path):
    value={'nested':{'token':'do-not-leak','old_token':'also-secret','password':'private'},'path':str(tmp_path/'file')}
    public=clean(value,[tmp_path])
    assert public['nested']['token']=='[REDACTED]'
    encoded=clean_text(json.dumps(value),[tmp_path])
    assert 'do-not-leak' not in encoded and 'also-secret' not in encoded
    assert 'private' not in encoded
    assert '[lab]' in encoded


def test_recovery_collects_sanitized_immutable_evidence_and_blocks_sqlite(tmp_path):
    j=Journal(tmp_path);r=j.create('09','lease');a,_=j.admit(r['id'],'prepare','one')
    folder=j.run_root(r['id'])/'output'/a['id'];folder.mkdir(parents=True)
    (folder/'report.json').write_text(json.dumps({'token':'secret-worker','path':str(tmp_path)}))
    (folder/'control.sqlite3').write_bytes(b'token=hidden')
    j.recover()
    entries=j.snapshot(r['id'])['evidence']
    assert len(entries)==1 and entries[0]['path'].endswith('report.json')
    _,path=j.evidence(r['id'],entries[0]['id'])
    assert 'secret-worker' not in path.read_text()
    assert '[lab]' in path.read_text()
