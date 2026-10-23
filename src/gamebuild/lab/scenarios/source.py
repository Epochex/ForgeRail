"""Disposable Git conflicts and real lock/worktree isolation."""
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time

from pathlib import Path
from .common import evidence, state

MERGED = 'def result():\n    return "feature+hotfix"\n'


def prepare(ctx):
    if ctx.case_id == '03':
        ctx.write('logic.py','def result():\n    return "base"\n')
        base = ctx.commit('Base code')
        ctx.git('checkout','-B','release')
        ctx.write('logic.py','def result():\n    return "hotfix"\n')
        hotfix = ctx.commit('Release hotfix')
        ctx.git('checkout','-B','develop',base)
        ctx.write('logic.py','def result():\n    return "feature"\n')
        develop = ctx.commit('Develop feature')
        state(ctx,base_sha=base,hotfix_sha=hotfix,target_sha=develop)
        ctx.commit('Record immutable sync inputs')
    else:
        ctx.write('version.txt','branch A')
        first = ctx.commit('Branch A source')
        ctx.git('branch','-f','branch-a',first)
        ctx.write('version.txt','branch B')
        second = ctx.commit('Branch B source')
        ctx.git('branch','-f','branch-b',second)
        ctx.write('isolation.json', {'separate':True,'correct_sha':True})
        state(ctx, first_sha=first, second_sha=second)
        ctx.commit('Record workspace plan')


def inject(ctx):
    if ctx.case_id == '03':
        # git identity is local to this disposable fixture, needed by cherry-pick --continue.
        ctx.git('config','user.name','ForgeRail Lab'); ctx.git('config','user.email','lab@example.invalid')
        result = ctx.command(['git','cherry-pick',state(ctx)['hotfix_sha']],allow_failure=True)
        if result['exit_code'] == 0: raise RuntimeError('fixture unexpectedly did not conflict')
        ctx.record('合并冲突','INFO','真实 cherry-pick 已暂停',unmerged=ctx.git('ls-files','-u'))
        if ctx.variant=='regression':
            ctx.write('logic.py','def result():\n    return "hotfix"\n')
            ctx.git('add','logic.py');ctx.git('cherry-pick','--continue')
            ctx.record('错误合并','INFO','冲突已解决但开发功能丢失，等待行为回归检查')
    else:
        ctx.write('isolation.json', {'separate':ctx.variant!='lock','correct_sha':ctx.variant!='identity'})
        ctx.commit('Inject workspace sharing or identity fault')


def repair(ctx):
    if ctx.case_id == '03':
        ctx.write('logic.py',MERGED)
        ctx.git('add','logic.py')
        if (ctx.repo/'.git/CHERRY_PICK_HEAD').exists():ctx.git('cherry-pick','--continue')
        else:ctx.commit('Correct regression introduced by conflict resolution')
        state(ctx,repair_sha=ctx.git('rev-parse','HEAD'))
        ctx.commit('Record conflict repair')
    else:
        ctx.write('isolation.json', {'separate':True,'correct_sha':True})
        ctx.commit('Isolate branch workspaces and pin SHA')


def execute(ctx):
    if ctx.case_id == '04': return workspace(ctx)
    code = ctx.read('logic.py')
    unmerged = ctx.git('ls-files','-u')
    tested = ctx.command([sys.executable,'-c','from logic import result; assert result()=="feature+hotfix"; print(result())'],allow_failure=True)
    facts = evidence(ctx,'merge-report.json', {**state(ctx),'head':ctx.git('rev-parse','HEAD'),
        'conflict_file':'logic.py','content':code,'unmerged_index':unmerged,'test':tested,
        'three_way':{stage:ctx.git('show',f':{stage}:logic.py',allow_failure=True) for stage in (1,2,3)} if unmerged else {}})
    return ctx.result('热修同步回归', [ctx.check('索引无未解决冲突',not unmerged,'',unmerged),
        ctx.check('功能与热修回归通过',tested['exit_code']==0,0,tested['exit_code'])], **facts)


LOCK_PROGRAM = '''import json,sys,time,os,hashlib
from pathlib import Path
from gamebuild.worker import NodeLock
root,out,ready,release,expected=map(Path,sys.argv[1:])
try:
    with NodeLock(root.parent/(root.name+"-locks")):
        start=time.monotonic()
        ready.write_text(str(os.getpid()))
        # Synchronization only; no timing claim is based on this wait.
        deadline=start+6
        while not release.exists():
            if time.monotonic()>deadline: raise RuntimeError("barrier timeout")
            hashlib.sha256(b"work"*10000).hexdigest()
        for _ in range(250):
            hashlib.sha256(b"work"*100000).hexdigest()
        actual=(root/"version.txt").read_text()
        out.write_text(json.dumps(dict(pid=os.getpid(),start=start,end=time.monotonic(),actual=actual,expected=str(expected))))
except RuntimeError as exc:
    print(str(exc),flush=True)
    sys.exit(23)
'''


def workspace(ctx):
    policy, saved = ctx.read('isolation.json'), state(ctx)
    works, actual_shas = [], []
    for index, sha in enumerate((saved['first_sha'],saved['second_sha'])):
        wanted = sha if index==0 or policy['correct_sha'] else saved['first_sha']
        req = dict(project_id='lab',adapter='lab',target='generic',branch=f'branch-{index}',commit_sha=wanted)
        preparation = '''import json,sys
from pathlib import Path
from gamebuild.source import SourceManager,input_digest
repo,root=map(Path,sys.argv[1:3]);request=json.loads(sys.argv[3])
request["input_digest"]=input_digest(repo,request)
print(json.dumps({"path":str(SourceManager(root,{"lab":repo}).prepare(request))},ensure_ascii=True))
'''
        prepared=ctx.command([sys.executable,'-c',preparation,ctx.repo,ctx.root/'workspaces',json.dumps(req)],timeout=15)
        work = Path(json.loads(prepared['stdout'])['path'])
        works.append(work)
        actual_shas.append(ctx.command(['git','rev-parse','HEAD'],cwd=work)['stdout'].strip())
    second_work = works[1] if policy['separate'] else works[0]
    ready_a, ready_b, release = (ctx.output/name for name in ('ready-a','ready-b','release'))
    out_a, out_b = ctx.output/'task-a.json',ctx.output/'task-b.json'
    for p in (ready_a,ready_b,release,out_a,out_b): p.unlink(missing_ok=True)
    def command(work,out,ready,expected):
        return ctx.command([sys.executable,'-c',LOCK_PROGRAM,work,out,ready,release,expected],timeout=9,allow_failure=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(command,works[0],out_a,ready_a,'branch A')
        deadline = time.monotonic()+5
        try:
            while not ready_a.exists():
                if ctx.cancelled(): raise InterruptedError('experiment cancelled')
                if time.monotonic()>deadline: raise RuntimeError('first executor did not reach lock barrier')
                time.sleep(.01)
            b = pool.submit(command,second_work,out_b,ready_b,'branch B')
            if policy['separate']:
                while not ready_b.exists():
                    if ctx.cancelled(): raise InterruptedError('experiment cancelled')
                    if time.monotonic()>deadline: raise RuntimeError('second executor did not reach barrier')
                    time.sleep(.01)
            else:
                b.result(timeout=5)
        finally:
            release.write_text('release')
        results = [a.result(),b.result()]
    receipts = [json.loads(p.read_text()) for p in (out_a,out_b) if p.exists()]
    overlap = max(0,min(r['end'] for r in receipts)-max(r['start'] for r in receipts)) if len(receipts)==2 else 0
    facts = evidence(ctx,'workspaces.json',dict(expected_shas=[saved['first_sha'],saved['second_sha']],actual_shas=actual_shas,
        directories=[str(works[0]),str(second_work)],policy=policy,processes=results,receipts=receipts,overlap_ms=round(overlap*1000,3)))
    return ctx.result('并行工作区与版本隔离',[
        ctx.check('两个真实执行器均拿到独立锁',all(r['exit_code']==0 for r in results),[0,0],[r['exit_code'] for r in results]),
        ctx.check('产物对应各自分支内容',len(receipts)==2 and [r['actual'] for r in receipts]==['branch A','branch B'],['branch A','branch B'],[r['actual'] for r in receipts]),
        ctx.check('完整 SHA 固定正确',actual_shas==[saved['first_sha'],saved['second_sha']],[saved['first_sha'],saved['second_sha']],actual_shas),
        ctx.check('独立任务执行区间重叠',overlap>0,'>0',overlap)], **facts)
