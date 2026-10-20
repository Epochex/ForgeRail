import json
from pathlib import Path
import subprocess

import pytest

from gamebuild.source import snapshot_request, SourceManager
from gamebuild.cli import run_demo
from gamebuild.worker import NodeLock


def init_repo(path):
    path.mkdir()
    subprocess.run(['git','init','-b','main',str(path)],check=True,capture_output=True)
    (path/'config.json').write_text('{"version":1}')
    subprocess.run(['git','-C',str(path),'add','.'],check=True)
    subprocess.run(['git','-C',str(path),'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','fixture'],check=True,capture_output=True)


def test_source_snapshot_rejects_dirty_tree_and_fixes_full_commit(tmp_path):
    repo=tmp_path/'repo'; init_repo(repo)
    r=snapshot_request(repo,'demo','lab','lab')
    assert len(r['commit_sha'])==40 and len(r['input_digest'])==64
    manager=SourceManager(tmp_path/'node',{'demo':str(repo)})
    a=manager.prepare(r)
    assert (a/'config.json').read_text()=='{"version":1}'
    (repo/'config.json').write_text('dirty')
    with pytest.raises(ValueError): snapshot_request(repo,'demo','lab','lab')
    bad={**r,'input_digest':'0'*64}
    with pytest.raises(ValueError): manager.prepare(bad)
    with pytest.raises(ValueError): manager.prepare({**r,'project_id':'unknown'})


def test_live_http_workers_two_branches_and_publication(tmp_path):
    result=run_demo(tmp_path/'demo')
    assert result['status']=='passed'
    assert len(result['jobs'])==2
    assert all(j['state']=='succeeded' for j in result['jobs'])
    assert len({j['request']['commit_sha'] for j in result['jobs']})==2
    assert result['stale_report_rejected'] is True
    assert result['artifact_tamper_rejected'] is True
    assert result['audit_chain_valid'] is True
    assert result['adapter']=='lab'


def test_same_node_workspace_cannot_be_used_by_two_executors(tmp_path):
    with NodeLock(tmp_path):
        with pytest.raises(RuntimeError):
            with NodeLock(tmp_path): pass
    with NodeLock(tmp_path): pass
