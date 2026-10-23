import json
from pathlib import Path


def test_readiness_is_published_only_after_complete_json(tmp_path,monkeypatch):
    from gamebuild.lab.node import publish_ready
    ready=tmp_path/'ready.json'
    original=Path.write_text
    def inspect(path,*args,**kwargs):
        assert path!=ready
        assert not ready.exists()
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',inspect)
    publish_ready(ready,{'pid':123,'url':'http://127.0.0.1:1'})
    assert json.loads(ready.read_text())['pid']==123
