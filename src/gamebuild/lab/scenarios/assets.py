"""Filesystem resource policy, stable GUID graph and incremental client updates."""
import json
import re
import shutil
import sys
import zipfile

from gamebuild.checks import check_assets
from .common import evidence, sha, state, tree_digest

GUID_A, GUID_B = 'a'*32, 'b'*32


def prepare(ctx):
    if ctx.case_id == '15':
        ctx.write('versions/v1/texture.txt', 'blue')
        ctx.write('versions/v1/prefab.json', {'texture_sha256':sha('blue')})
        ctx.write('versions/v1/audio.txt', 'unchanged sound'*100)
        ctx.write('versions/v2/texture.txt', 'orange')
        ctx.write('versions/v2/prefab.json', {'texture_sha256':sha('orange')})
        ctx.write('versions/v2/audio.txt', 'unchanged sound'*100)
        ctx.write('dependencies.json', {'prefab.json':['texture.txt'], 'texture.txt':[], 'audio.txt':[]})
        ctx.write('update-policy.json', {'mode':'incremental','include_dependents':True})
    else:
        ctx.write('Assets/hero_texture.txt', 'blue texture')
        ctx.write('Assets/hero_texture.txt.meta', f'guid: {GUID_A}\ncompression: compressed\nreadable: false\n')
        ctx.write('Assets/hero_material.txt', 'material')
        ctx.write('Assets/hero_material.txt.meta', f'guid: {GUID_B}\n')
        ctx.write('prefabs/hero.json', {'name':'hero','references':[GUID_A, GUID_B]})
        ctx.write('scenes/main.json', {'prefabs':['hero']})
        ctx.write('asset-policy.json', {'max_bytes':256,'pattern':'^[a-z][a-z0-9_]*\\.txt$','compression':'compressed','readable':False})
    sha1 = ctx.commit('Lab resource baseline')
    state(ctx, baseline_sha=sha1)


def inject(ctx):
    v = ctx.variant
    if ctx.case_id == '15':
        policy = ctx.read('update-policy.json')
        policy['mode' if v == 'full' else 'include_dependents'] = 'full' if v == 'full' else False
        ctx.write('update-policy.json', policy)
    elif ctx.case_id == '01':
        if v == 'import': ctx.write('Assets/hero_texture.txt.meta', f'guid: {GUID_A}\ncompression: none\nreadable: true\n')
        elif v == 'budget': ctx.write('Assets/hero_texture.txt', b'x'*1024)
        else:
            for suffix in ('', '.meta'):
                (ctx.repo / ('Assets/hero_texture.txt'+suffix)).rename(ctx.repo / ('Assets/Hero Bad.txt'+suffix))
            ctx.write('named-reference.json', {'path':'Assets/Hero Bad.txt'})
            ctx.record('文件变更','INFO','资源与命名引用同步改为非法名称', old='hero_texture.txt', new='Hero Bad.txt')
    else:
        if v == 'duplicate_guid': ctx.write('Assets/hero_material.txt.meta', f'guid: {GUID_A}\n')
        elif v == 'missing_reference': ctx.write('prefabs/hero.json', {'name':'hero','references':['f'*32]})
        else: ctx.write('prefabs/hero.json', '{ "references": [ broken')
    state(ctx, fault_sha=ctx.commit('Inject resource fault'))


def repair(ctx):
    if ctx.case_id == '15':
        ctx.write('update-policy.json', {'mode':'incremental','include_dependents':True})
    else:
        ctx.git('restore', '--source='+state(ctx)['baseline_sha'], '--', 'Assets', 'prefabs', 'scenes', 'asset-policy.json')
        # Git restore removes tracked renamed fault inputs as part of directory restoration.
        if (ctx.repo/'named-reference.json').exists():
            ctx.write('named-reference.json', {'path':'Assets/hero_texture.txt'})
        ctx.record('文件变更','INFO','从固定基线恢复资源 GUID 和描述', source_sha=state(ctx)['baseline_sha'])
    state(ctx, repair_sha=ctx.commit('Restore resource policy and dependency closure'))


def execute(ctx):
    if ctx.case_id == '15': return incremental(ctx)
    policy = ctx.read('asset-policy.json')
    report = check_assets(ctx.repo, max_asset_bytes=policy['max_bytes'])
    issues = list(report['issues'])
    for issue in issues:
        if issue['rule_id'] == 'asset_too_large':
            issue.update(expected=policy['max_bytes'], actual=(ctx.repo/issue['path']).stat().st_size, unit='bytes')
    reverse, guid_paths = {}, {}
    for meta in sorted((ctx.repo/'Assets').glob('*.meta')):
        match = re.search(r'^guid:\s*([a-f0-9]{32})', meta.read_text(), re.M)
        if match: guid_paths[match[1]] = meta.name
    if ctx.case_id == '01':
        for resource in sorted((ctx.repo/'Assets').glob('*.txt')):
            if not re.fullmatch(policy['pattern'], resource.name):
                issues.append({'rule_id':'asset_name','path':resource.name,'expected':policy['pattern'],'actual':resource.name})
            if 'texture' in resource.name or 'Hero' in resource.name:
                meta = resource.with_name(resource.name+'.meta').read_text()
                for key, want in [('compression',policy['compression']),('readable',str(policy['readable']).lower())]:
                    match = re.search(r'^'+key+r':\s*(\S+)', meta, re.M)
                    got = match[1] if match else None
                    if got != want: issues.append({'rule_id':'texture_'+key,'path':str(resource.name),'expected':want,'actual':got})
    for prefab in (ctx.repo/'prefabs').glob('*.json'):
        try:
            description = json.loads(prefab.read_text())
        except json.JSONDecodeError as exc:
            issues.append({'rule_id':'prefab_schema','path':prefab.name,'actual':str(exc)})
            continue
        if not isinstance(description,dict) or not isinstance(description.get('references'),list):
            issues.append({'rule_id':'prefab_schema','path':prefab.name,'actual':description}); continue
        for reference in description['references']:
            reverse.setdefault(reference,[]).append('prefabs/'+prefab.name)
            if reference not in guid_paths: issues.append({'rule_id':'unresolved_reference','path':prefab.name,'actual':reference})
    affected_prefabs = {path.rsplit('/',1)[-1].removesuffix('.json') for paths in reverse.values() for path in paths} if issues else set()
    affected_prefabs.update(issue['path'].removesuffix('.json') for issue in issues if issue['rule_id']=='prefab_schema')
    affected_scenes = []
    for scene in (ctx.repo/'scenes').glob('*.json'):
        if set(json.loads(scene.read_text())['prefabs']) & affected_prefabs:
            affected_scenes.append('scenes/'+scene.name)
    facts = evidence(ctx,'resource-report.json', {'issues':issues,'reverse_dependencies':reverse,
                      'affected_scenes':affected_scenes, 'guid_index':guid_paths,
                      'input_digest':tree_digest(ctx.repo/'Assets'), 'prefab_digest':tree_digest(ctx.repo/'prefabs'),
                      'sha':ctx.git('rev-parse','HEAD')})
    return ctx.result('资源策略与引用扫描', [ctx.check('资源违规数为零',not issues,0,len(issues))], **facts)


def incremental(ctx):
    base, target = ctx.repo/'versions/v1', ctx.repo/'versions/v2'
    dependencies, policy = ctx.read('dependencies.json'), ctx.read('update-policy.json')
    changed = {p.name for p in target.iterdir() if p.read_bytes() != (base/p.name).read_bytes()}
    # texture is the authored change; prefab is a generated dependent.
    authored = {'texture.txt'}
    closure = set(authored)
    while True:
        expanded = closure | {name for name, deps in dependencies.items() if set(deps) & closure}
        if expanded == closure: break
        closure = expanded
    selected = set(dependencies) if policy['mode']=='full' else (closure if policy['include_dependents'] else authored)
    package = ctx.output/'incremental.zip'
    expected_inventory = {p.name:sha(p.read_bytes()) for p in target.iterdir()}
    update_manifest = dict(base_version=base.name,target_version=target.name,files=expected_inventory)
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(selected): archive.write(target/name,name)
        archive.writestr('.lab-update.json',json.dumps(update_manifest,sort_keys=True))
    full_package=ctx.output/'full-reference.zip'
    with zipfile.ZipFile(full_package,'w',zipfile.ZIP_DEFLATED) as archive:
        for resource in sorted(target.iterdir()):archive.write(resource,resource.name)
        archive.writestr('.lab-update.json',json.dumps(update_manifest,sort_keys=True))
    client = ctx.output/'client'
    receipt_path = ctx.output/'client-receipt.json'
    program = '''import hashlib,json,os,shutil,sys,zipfile
from pathlib import Path
base,package,client,receipt=map(Path,sys.argv[1:])
shutil.copytree(base,client,dirs_exist_ok=True)
with zipfile.ZipFile(package) as archive:
    manifest=json.loads(archive.read(".lab-update.json"))
    assert manifest["base_version"]==base.name, "patch base version mismatch"
    for name in archive.namelist():
        if name!=".lab-update.json": (client/name).write_bytes(archive.read(name))
loaded=json.loads((client/"prefab.json").read_text())["texture_sha256"]==hashlib.sha256((client/"texture.txt").read_bytes()).hexdigest()
observed={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in client.iterdir()}
loaded=loaded and observed==manifest["files"]
if not loaded: shutil.copytree(base,client,dirs_exist_ok=True)
receipt.write_text(json.dumps(dict(pid=os.getpid(),loaded=loaded,observed_files=observed,fallback_to_baseline=not loaded,applied_version=manifest["target_version"] if loaded else base.name)))
sys.exit(0 if loaded else 31)
'''
    process = ctx.command([sys.executable,'-c',program,base,package,client,receipt_path],allow_failure=True)
    receipt = json.loads(receipt_path.read_text())
    loaded = receipt['loaded']
    equal = receipt['observed_files'] == expected_inventory
    full_bytes = full_package.stat().st_size
    downloaded = package.stat().st_size
    facts = evidence(ctx,'incremental-report.json',dict(changed=sorted(changed), authored=sorted(authored), affected=sorted(closure),
        selected=sorted(selected), reused=sorted(set(dependencies)-selected), downloaded_bytes=downloaded,
        zip_bytes=package.stat().st_size, full_bytes=full_bytes, client_loaded=loaded, client_equal=equal,
        fallback_to_baseline=not loaded, target_digest=tree_digest(target), client_digest=tree_digest(client),
        policy=policy, package_sha256=sha(package.read_bytes()),client_process=process,client_receipt=receipt,expected_inventory=expected_inventory))
    return ctx.result('增量包应用与依赖闭包',[
        ctx.check('只重打依赖闭包',selected==closure,sorted(closure),sorted(selected)),
        ctx.check('独立客户端加载更新资源',loaded,True,loaded),
        ctx.check('客户端完整内容匹配目标版本',equal,tree_digest(target),facts['client_digest']),
        ctx.check('下载字节小于全量',downloaded<full_bytes, '<'+str(full_bytes),downloaded)], **facts)
