import importlib.util
import json
from pathlib import Path
from gamebuild.source import git


def test_summary_does_not_infer_parallel_unity_from_single_player_and_lab_demo(tmp_path):
    path=Path(__file__).resolve().parents[1]/'scripts/summarize.py'
    spec=importlib.util.spec_from_file_location('summary',path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    git(tmp_path,'init','-b','main'); (tmp_path/'fixture').write_text('x'); git(tmp_path,'add','.')
    git(tmp_path,'-c','user.name=Lab','-c','user.email=lab@example.invalid','commit','-m','fixture')
    (tmp_path/'reports/unity').mkdir(parents=True)
    (tmp_path/'reports/unity/engine-status.json').write_text(json.dumps({'player_build':{'status':'passed'},'player_smoke':{'status':'passed'}}))
    (tmp_path/'reports/demo.json').write_text('{"status":"passed"}')
    module.ROOT=tmp_path
    result=module.summarize()
    assert next(r for r in result['acceptance'] if r['id']=='A04')['status']=='blocked'
