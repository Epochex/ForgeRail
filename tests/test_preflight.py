import json
from gamebuild.preflight import cached_asset_check


def test_resource_changes_invalidate_cache_and_same_input_hits(tmp_path):
    p=tmp_path/'project'; a=p/'Assets'; a.mkdir(parents=True)
    (a/'config.json').write_text('{"resource":1}')
    (a/'config.json.meta').write_text('guid: '+'1'*32+'\n')
    r1=cached_asset_check(p,tmp_path/'cache',tmp_path/'first.json','Win64')
    r2=cached_asset_check(p,tmp_path/'cache',tmp_path/'second.json','Win64')
    assert r1['passed'] and not r1['cache_hit'] and r2['cache_hit']
    (a/'config.json').write_text('{broken')
    r3=cached_asset_check(p,tmp_path/'cache',tmp_path/'third.json','Win64')
    assert not r3['passed'] and not r3['cache_hit']
    assert any(i['rule_id']=='invalid_json' for i in r3['issues'])
