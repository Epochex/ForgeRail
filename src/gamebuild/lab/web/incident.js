import { $, el, empty, detail, replace } from './dom.js';
import { state, formatValue, STEPS } from './model.js';
import { comparisonRows, outcomeTitle } from './observations.js';

let signature = '';

function actionButton(label, action, onSelect, mode = 'events') {
  const button = el('button', 'evidence-link', label); button.type = 'button';
  button.disabled = !action;
  button.addEventListener('click', () => {
    onSelect(action.id);
    // Navigation is explicit: the reader chooses when to leave the explanation.
    $('audit').open = true;
    if (mode === 'diff') {
      document.querySelectorAll('#event-list .event-detail').forEach(d => {
        if (d.querySelector('summary')?.textContent.startsWith('文件 diff')) d.open = true;
      });
    }
    $('audit').scrollIntoView({block:'start', behavior:'auto'});
  });
  return button;
}

function valueCell(value, tone = '') {
  const cell = el('td', tone);
  if (value && typeof value === 'object') {
    cell.append(detail(Array.isArray(value) ? `${value.length} 条实测记录` : '展开实测对象', formatValue(value)));
  } else cell.textContent = formatValue(value);
  return cell;
}

function comparison(rows) {
  const scroll = el('div', 'comparison-scroll');
  const table = el('table', 'outcome-table');
  const head = el('thead'), tr = el('tr');
  ['检查什么', '判定标准', '故障时实测', '修复后复验'].forEach(t => tr.append(el('th','',t)));
  head.append(tr); table.append(head);
  const body = el('tbody');
  rows.forEach(row => {
    const line = el('tr'); const label = el('th', '', row.label);
    if (row.path) label.append(el('small', 'row-path', row.path));
    line.append(label, valueCell(row.expected), valueCell(row.before, row.failed ? 'failure' : ''), valueCell(row.after, row.fixed ? 'success' : ''));
    body.append(line);
  });
  table.append(body); scroll.append(table); return scroll;
}

export function renderIncident(selected, onSelect) {
  const key = JSON.stringify([selected?.id, state.variant, state.run?.id, state.run?.actions, state.run?.status]);
  if (signature === key) return;
  signature = key;
  if (!selected) { replace('incident', empty('正在加载事故说明…')); return; }
  const guide = selected.guide;
  if (!guide) { replace('incident', empty('请重启本机服务以加载新版事故说明。')); return; }
  const mismatch = state.run && state.run.variant !== state.variant;
  const run = mismatch ? null : state.run;
  const action = kind => run?.actions.findLast(a => a.kind === kind);
  const before = action('execute')?.result;
  const verify = action('verify');
  const after = verify?.result;
  const repaired = action('repair')?.state === 'SUCCEEDED';
  const last = run?.actions.at(-1);
  const verified = run?.phase === 'verified' && verify?.state === 'SUCCEEDED' && after?.passed === true;
  const comparable = !Array.isArray(before?.facts?.issues) || Array.isArray(after?.facts?.issues);
  const header = el('div', 'incident-header');
  header.append(el('span', 'eyebrow', '事故处理单'), el('span', 'mono muted', run ? `#${run.id.slice(0,8)}` : '尚未执行此变体'));
  const headline = el('h2', verified && comparable ? 'incident-title success' : 'incident-title');
  if (last && ['FAILED','CANCELLED','INTERRUPTED'].includes(last.state)) {
    headline.textContent = `${STEPS.find(s=>s.kind===last.kind)?.label}未完成`;
  } else headline.textContent = mismatch ? '已切换事故类型，请开始新的演练' : outcomeTitle(before,after,verified,repaired);
  const scope = el('p', 'scope-line', `本案例验证：${guide.gate}${verified && comparable ? ' · 复验通过' : ''}`);
  const setup = el('div', 'incident-setup');
  setup.append(el('span','field-label','操作对象'), el('code','target-path',guide.target),
    el('span','field-label',action('inject')?.state === 'SUCCEEDED' ? '已制造的问题' : '将制造的问题'),
    el('p','mutation',guide.mutations[state.variant] || '请选择事故类型'));
  const nodes = [header, headline, scope, setup];
  if (last?.error) nodes.push(el('p','incident-error',last.error));
  const result = el('section','incident-result'); result.dataset.testid = 'checks';
  result.append(el('h3','', '检查抓到了什么'));
  if (!before) result.append(el('p','muted', '尚无扫描结果。点击“完整演练”自动走完处理过程，或在下方逐步操作。说明是预设操作，结果将在实际执行后出现。'));
  else {
    const rows = comparisonRows(before,after);
    result.append(el('p', before.fault_signature?.observed ? 'failure result-caption' : 'failure',
      before.fault_signature?.observed ? '故障阶段未通过；失败特征与本次注入相符。' : '尚未确认失败是否由所选故障引起，请检查执行记录。'));
    if (rows.length) result.append(comparison(rows));
    const rest = (before.checks || []).filter(c=>c.passed && !rows.some(row=>row.label===c.label));
    if (rest.length) {
      const details = el('details','supporting-checks'); details.append(el('summary','',`同时检查了 ${rest.length} 项其他条件`));
      details.append(comparison(rest.map(check => {
        const fixed = after?.checks?.find(c=>c.label===check.label);
        return {label:check.label,expected:check.expected,before:check.actual,after:fixed ? fixed.actual : '尚未复验',fixed:fixed?.passed};
      }))); result.append(details);
    }
    if (after?.passed === false) result.append(el('p','failure','复验仍有失败，不能交付。'));
    if (verified && comparable) result.append(el('p','success result-caption','判定依据：本次独立复验的全部断言通过；具体范围以上述检查为准。'));
  }
  nodes.push(result);
  const repair = el('div','repair-explanation');
  repair.append(el('h3','',repaired ? '实际采用的修复' : '如何修复'),el('p','',guide.repair));
  const links = el('div','evidence-links');
  links.append(actionButton('查看故障差异',action('inject'),onSelect,'diff'),actionButton('查看修复差异',action('repair'),onSelect,'diff'),actionButton('查看复验原始记录',verify,onSelect));
  repair.append(links); nodes.push(repair);
  const lesson = el('p','lesson'); lesson.append(el('strong','','工程判断  '),document.createTextNode(guide.lesson)); nodes.push(lesson);
  replace('incident',...nodes);
  // Keep action controls stable for keyboard users; update explanations only.
  const notes = ['创建独立工程并记录 Git 基线','按所选事故类型修改真实输入',guide.gate,'对照规则与实测值，引用失败步骤回执','按上方修复范围修改输入并记录 diff','使用修复后的输入再次检查，生成新回执'];
  STEPS.forEach((s,i)=>{ const row=$(`row-${s.kind}`); row.querySelector('strong').textContent=s.label; row.querySelector('small').textContent=notes[i]; });
}

export function renderTrust(report, error = '') {
  const rows = [
    ['解决了什么问题？','把资源、版本、节点和交付故障放进可重复的小工程，验证拦截与修复机制，保留文件、命令和回执。它服务于学习与回归；当前没有自主规划的 AI Agent。'],
    ['成功率怎么计算？','固定 41 个故障变体，每个各执行一次。通过要求：识别指定故障、实际修改输入、复验全部断言通过，外加该场景的独立回执检查。通过数 / 41；跳过、缺测、失败都不算通过，重复结果判为无效。手动点出的演练不混入分母。'],
    ['样本从哪来，谁定标准？','项目维护者按 16 类岗位场景人工构造并定义断言，覆盖 41 个已知变体。不是生产故障抽样，也不是公开基准；按机制选样，没有真实发生频率权重。'],
    ['是否存在数据泄漏或偏差？','没有模型训练，所以训练集重叠不适用。但场景、修复和断言同源开发，存在自证偏差。当前全部属于开发回归集，没有盲测留出集，不能据此宣称未知故障泛化率或线上成功率。'],
    ['人工复核与一致性呢？','人工复核尚未开展，没有复核一致率。建议先冻结判定表，由两位评审独立复核同一批回执，再记录分歧、仲裁和一致率。该流程是后续建议，未计入本次成绩。'],
    ['失败如何归因与回放？','run_id 关联每次 action、输入 diff、命令退出码、断言和制品摘要；点击故障/修复/复验证据即可定位原始记录。历史查看是证据回放，重新演练会创建新的执行记录；这不是模型思维链记录。'],
  ];
  const nodes=[];
  const score=el('div','evaluation-score');
  if (report?.available) {
    const s=report.summary;
    const valid=report.current_source && report.source_stable && report.exit_code===0 && s.passed===s.total;
    $('evaluation-headline').textContent = `${s.passed}/${s.total} 回归样本通过${report.current_source ? '' : ' · 旧代码结果'}`;
    score.append(el('strong',valid?'success':'',`${s.passed} / ${s.total}`),el('p','',`${(s.rate*100).toFixed(1)}% · 固定故障回归通过率 · 单批次，每变体一次`));
    score.append(el('p','muted',`失败 ${s.failed} · 跳过 ${s.skipped} · 缺测 ${s.missing} · 无效 ${s.invalid}。累计保存 ${report.batch_count} 批，当前显示最近完成批次。`));
    if (!report.current_source || !report.source_stable) score.append(el('p','failure','代码已变化或执行期间不稳定；此分数不能代表当前代码。请重新评测。'));
    score.append(el('p','mono report-id',`${report.batch_id} · ${report.environment.os} · Python ${report.environment.python}`));
    const details=el('details',''); details.append(el('summary','','逐样本成绩与版本凭据'));
    const list=el('ul','sample-results');
    s.rows.forEach(r=>list.append(el('li',r.status==='passed'?'success':'failure',`${r.case_id} / ${r.label} — ${r.status} · ${r.seconds.toFixed(2)} s${r.reason ? ' · '+r.reason : ''}`)));
    details.append(list,detail('代码与 JUnit SHA256',`Git ${report.git_head}${report.dirty ? ' + working changes' : ''}\nSource ${report.source_sha256}\nJUnit ${report.junit_sha256}\n${report.command}`)); score.append(details);
    const links=el('div','evidence-links');
    const link=el('a','evidence-link','下载评测报告'); link.href='/lab/api/evaluation/export'; link.download='forgerail-evaluation.json';
    const junit=el('a','evidence-link','下载原始 JUnit'); junit.href=`/lab/api/evaluation/${encodeURIComponent(report.batch_id)}/junit`; junit.download='results.xml';
    links.append(link,junit); score.append(links);
  } else {
    $('evaluation-headline').textContent = '尚无本机评测报告 · 不显示成功率';
    score.append(el('p','',error || '尚未运行完整固定评测集。个别演练成功不能替代总体结果。'));
  }
  score.append(el('code','reproduce-command','python scripts/evaluate_lab.py --root runtime/interactive-lab'));
  nodes.push(score);
  rows.forEach(([q,a])=>{ const block=el('article','trust-answer');block.append(el('h3','',q),el('p','',a));nodes.push(block); });
  replace('trust-content',...nodes);
}
