"""One registered action, isolated in a managed subprocess."""
import argparse
import json
import difflib
import hashlib
import os
import shutil
import uuid
import threading
import traceback

from .context import Context
from .store import Journal


def checkpoint(context, run, action):
    """Restore the prior mutation boundary before retrying, including Git index/history."""
    from .context import confined
    if action['kind'] not in ('prepare','inject','repair'): return
    for prior in reversed(run['actions']):
        if prior['id']==action['id'] or prior['kind']!=action['kind'] or prior['state']=='SUCCEEDED': continue
        saved=confined(context.root,'checkpoints/'+prior['id'])
        if not (saved/'complete').exists(): continue
        restored=confined(context.root,'restore-'+uuid.uuid4().hex)
        shutil.copytree(saved/'fixture',restored)
        if context.repo.exists(): context.repo.replace(confined(context.root,'retired-'+uuid.uuid4().hex))
        restored.replace(context.repo)
        context.record('中断恢复','INFO','恢复上次操作前的文件和 Git 状态，再重新执行',prior_action=prior['id'])
        break
    saved=confined(context.root,'checkpoints/'+action['id'])
    saved.mkdir(parents=True,exist_ok=True)
    shutil.copytree(context.repo,saved/'fixture',dirs_exist_ok=True)
    (saved/'complete').touch()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if any(p in ('.git', '__pycache__') for p in path.relative_to(root).parts): continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256*1024: continue
        raw = path.read_bytes()
        result[path.relative_to(root).as_posix()] = {'sha256':hashlib.sha256(raw).hexdigest(),
                                                   'text':raw.decode('utf-8', errors='replace')}
        if len(result) >= 400: break
    return result


def perform(root, action_id, parent_pid=None):
    journal = Journal(root)
    action = journal.action(action_id)
    run = journal.snapshot(action['run_id'])
    root_path=journal.run_root(run['id'])
    cancel_path=root_path/'output'/action_id/'cancel.requested'
    orphaned, done = threading.Event(), threading.Event()
    def watch_parent():
        while not done.wait(.1):
            if parent_pid is not None and os.name!='nt' and os.getppid()!=parent_pid:
                cancel_path.parent.mkdir(parents=True,exist_ok=True)
                cancel_path.touch()
                orphaned.set()
                return
    threading.Thread(target=watch_parent,daemon=True).start()
    context = Context(root_path, run['case_id'], run['variant'], action['kind'],
                      emit=lambda e: journal.event(run['id'], action_id, e), action_id=action_id,
                      cancelled=lambda:cancel_path.exists() or orphaned.is_set())
    from . import scenarios
    outcome = {'state': 'SUCCEEDED', 'result': None, 'error': None}
    before = inventory(context.repo)
    try:
        kind = action['kind']
        checkpoint(context,run,action)
        before = inventory(context.repo)
        with context.stage({'prepare': '准备实验', 'inject': '制造问题', 'execute': '执行故障流程',
                            'diagnose': '定位根因', 'repair': '应用修复', 'verify': '重新验证'}[kind]):
            if kind == 'diagnose':
                from .walkthrough import GUIDES
                guide = GUIDES[run['case_id']]
                source = next(a for a in reversed(run['actions']) if a['kind'] == 'execute' and a['result'])
                previous = source['result']
                failed = [c for c in previous['checks'] if not c['passed']]
                diagnosis = dict(method='rule-based', source_action_id=source['id'],
                                 observations=previous.get('facts', {}).get('issues', failed),
                                 fault_confirmed=previous.get('fault_signature', {}).get('observed', False),
                                 intervention=guide['mutations'][run['variant']], repair_scope=guide['repair'])
                summary = f"{guide['gate']}：{len(diagnosis['observations'])} 项异常与注入记录核对；按规则定位，非 AI 自主推断。"
                result = {'summary': summary, 'checks': failed, 'diagnosis': diagnosis,
                          'facts': previous.get('facts', {}), 'execution_mode': 'lab'}
                context.record('诊断证据', 'INFO', summary, **diagnosis)
            elif kind in ('execute', 'verify'):
                result = scenarios.execute(context)
                if not result.get('checks'): raise ValueError('scenario has no observed assertions')
                expected = kind == 'verify'
                if result['passed'] != expected:
                    outcome.update(state='FAILED', error='修复尚未通过验证' if expected else '未复现预期故障，请检查注入步骤')
                elif not expected and not result.get('fault_signature',{}).get('observed'):
                    outcome.update(state='FAILED',error='未观察到指定故障的证据；本次是其他失败，请检查实际日志')
            else:
                value = getattr(scenarios, kind)(context)
                result = value if isinstance(value, dict) else {'summary': '操作完成', 'execution_mode': 'lab'}
        (context.output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        outcome['result'] = result
    except Exception as exc:
        context.record('执行异常', 'FAILED', str(exc)[:1600], traceback=traceback.format_exc()[-5000:])
        outcome.update(state='FAILED', error=type(exc).__name__+': '+str(exc)[:1600])
    finally:
        done.set()
        after = inventory(context.repo)
        changes, diffs = [], []
        for name in sorted(set(before)|set(after)):
            a, b = before.get(name), after.get(name)
            if a == b: continue
            changes.append({'path':name,'before_sha256':a['sha256'] if a else None,'after_sha256':b['sha256'] if b else None})
            diffs.extend(difflib.unified_diff((a or {}).get('text','').splitlines(True), (b or {}).get('text','').splitlines(True),
                                            fromfile='before/'+name,tofile='after/'+name))
        (context.output/'changes.diff').write_text(''.join(diffs)[:100000],encoding='utf-8')
        (context.output/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
        if changes: context.record('输入差异','INFO',f'{len(changes)} 个文件发生实际变化',changes=changes,diff=''.join(diffs)[:24000])
        (context.output/'outcome.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--action', required=True)
    parser.add_argument('--parent', type=int)
    args = parser.parse_args()
    perform(args.root, args.action, args.parent)
