import { $, el, empty, detail, replace, setOptions } from './dom.js';
import { STEPS, state, currentCase, busy, statusLabel, formatValue, PHASE_LABELS } from './model.js';
import { renderEvidence } from './evidence.js';
import { renderTimeline } from './timeline.js';

let sidebarKey = '', caseKey = '', checksKey = '', timelineKey = '';
export function buildSteps(onAction, onSelect) {
  for (const [index, step] of STEPS.entries()) {
    const row = el('li', 'step'); row.id = `row-${step.kind}`;
    const badge = el('button', 'step-number mono', String(index + 1).padStart(2, '0'));
    badge.type = 'button'; badge.title = `定位${step.label}的执行证据`;
    badge.addEventListener('click', () => { const action = state.run?.actions.findLast(a => a.kind === step.kind); if (action) onSelect(action.id); });
    const body = el('div', 'step-body'); body.append(el('strong', '', step.stage), el('small', '', step.note));
    const button = el('button', 'step-action', step.label); button.id = `step-${step.kind}`; button.dataset.testid = `step-${step.kind}`; button.type = 'button'; button.disabled = true;
    button.addEventListener('click', () => onAction(step.kind));
    row.append(badge, body, button); $('steps').append(row);
  }
}

export function render(onCase, onSelectAction) {
  const selected = currentCase();
  const run = state.run;
  const locked = busy();
  const root = document.querySelector('[data-testid="workbench"]');
  root.dataset.phase = run?.phase || ''; root.dataset.runId = run?.id || '';
  $('error-banner').hidden = !state.error; $('error-text').textContent = state.error;
  const sidebarSignature = JSON.stringify([state.cases, state.caseId, state.search, state.role, state.histories.filter(r => r.status === 'VERIFIED').map(r => r.case_id)]);
  if (sidebarSignature !== sidebarKey) {
    const cases = state.cases.filter(c => `${c.title} ${c.category} ${c.role} ${c.description}`.toLowerCase().includes(state.search.toLowerCase()) && (!state.role || c.role.includes(state.role)));
    const groups = new Map();
    cases.forEach(c => { if (!groups.has(c.category)) groups.set(c.category, []); groups.get(c.category).push(c); });
    const sections = [...groups].map(([category, items]) => {
      const group = el('section', 'case-group'); group.append(el('h2', '', category));
      items.forEach(c => {
        const button = el('button', `case-button ${c.id === state.caseId ? 'selected' : ''}`);
        button.type = 'button'; button.dataset.testid = `case-${c.id}`; button.setAttribute('aria-current', c.id === state.caseId ? 'true' : 'false'); button.title = `${c.title} · ${c.role}`;
        const completed = state.histories.some(r => r.case_id === c.id && r.status === 'VERIFIED');
        button.append(el('span', 'case-number mono', c.id), el('span', 'case-name', c.title), el('span', completed ? 'case-completed' : 'case-chevron', completed ? '✓' : '›'));
        button.addEventListener('click', () => onCase(c.id)); group.append(button);
      }); return group;
    });
    replace('case-list', ...(sections.length ? sections : [empty('没有匹配场景，尝试其他关键词或角色。')]));
    $('case-count').textContent = `${cases.length} CASES`; sidebarKey = sidebarSignature;
  }
  if (selected && caseKey !== selected.id) {
    $('case-eyebrow').textContent = `${selected.category} / CASE ${selected.id} / ${selected.role}`;
    $('case-title').textContent = selected.title; $('case-description').textContent = selected.description;
    $('case-impact').textContent = selected.impact; $('breadcrumb').textContent = selected.title;
    $('boundary').textContent = selected.boundary;
    replace('learning', ...[['诊断线索', selected.diagnosis], ['修复思路', selected.repair], ['面试追问', selected.interview]].map(([label, text]) => {
      const node = el('div', 'learning-item'); node.append(el('h3', '', label), el('p', '', text)); return node;
    }));
    caseKey = selected.id;
  }
  setOptions($('fault-variant'), (selected?.variants || []).map(v => [v.id, v.label]), state.variant);
  $('fault-variant').disabled = locked;
  $('new-run').disabled = locked || !selected;
  $('run-all').disabled = locked || !selected;
  $('run-all').setAttribute('aria-busy', String(state.autoRunning));
  $('cancel-run').disabled = !(state.submitting || state.autoRunning || run?.busy_action) || state.cancelRequested;
  $('cancel-run').textContent = state.cancelRequested && (state.submitting || state.autoRunning || run?.busy_action) ? '正在停止…' : '停止执行';
  $('run-status').textContent = statusLabel(run);
  $('status-dot').className = `status-dot ${run?.busy_action ? 'running' : run?.status === 'VERIFIED' ? 'verified' : run?.status === 'FAILED' ? 'failed' : ''}`;
  $('run-short-id').textContent = run ? `#${run.id.slice(0, 8)}` : 'NO RUN';
  const done = Math.max(0, STEPS.findIndex(s => s.phase === run?.phase) + 1);
  $('workflow-count').textContent = `${done} / 6`;
  for (const [index, step] of STEPS.entries()) {
    const allowed = run?.allowed_actions?.includes(step.kind);
    const action = run?.actions.findLast(a => a.kind === step.kind);
    $(`step-${step.kind}`).disabled = !allowed || locked;
    $(`row-${step.kind}`).className = `step ${index < done ? 'complete' : ''} ${allowed ? 'next' : ''} ${action?.state === 'RUNNING' ? 'active' : ''} ${state.actionId && action?.id === state.actionId ? 'inspected' : ''}`;
  }
  const lastError = run?.actions.findLast(a => a.error)?.error;
  $('workflow-note').textContent = run?.status === 'CANCELLED' ? '执行已停止，现场和证据已保留。可以重试当前步骤或新建实验。' : ['FAILED', 'INTERRUPTED'].includes(run?.status) ? lastError || '操作未完成，请检查证据后重试。' : state.autoRunning ? '完整演练正在依次执行同一套六步操作；可随时停止。' : state.cancelRequested && !locked ? '完整演练已停止，已完成的阶段和证据已保留。可以继续下一步操作。' : run?.phase === 'verified' ? '六步闭环已完成。查看失败与复验对比，下载证据，或创建下一次实验。' : '阶段与结果均来自后端实际执行。预期故障被观测到后，流程进入诊断与修复。';
  const checkSignature = JSON.stringify([run?.id, run?.actions]);
  if (checksKey !== checkSignature) { renderChecks(run); checksKey = checkSignature; }
  const timelineSignature = JSON.stringify([run?.id, run?.actions, run?.events?.length]);
  if (timelineKey !== timelineSignature) { renderTimeline(run, onSelectAction); timelineKey = timelineSignature; }
  renderEvidence();
  const history = state.histories.filter(r => r.case_id === state.caseId);
  if (run && !history.some(r => r.id === run.id)) history.unshift(run);
  setOptions($('history-select'), history.length ? history.map(r => [r.id, `${new Date(r.created_at * 1000).toLocaleString('zh-CN', { hour12: false })} · ${r.status === 'CANCELLED' ? '已取消' : PHASE_LABELS[r.phase] || r.status} · ${r.id.slice(0, 6)}`]) : [['', '暂无执行记录']], run?.id || '');
  $('history-select').disabled = locked || !history.length;
  const exportLink = $('export-run');
  exportLink.setAttribute('aria-disabled', String(!run));
  if (run) { exportLink.href = `/lab/api/runs/${encodeURIComponent(run.id)}/export`; exportLink.download = `forgerail-${run.id.slice(0, 8)}.json`; }
  else exportLink.removeAttribute('href');
}

function renderChecks(run) {
  const lastAction = run?.actions.at(-1);
  const resultAction = lastAction?.state === 'FAILED' ? lastAction : run?.actions.findLast(a => a.result);
  const latest = resultAction?.result;
  if (!latest && lastAction?.state !== 'FAILED') { replace('check-list', empty('运行流程后，在这里查看预期与实测值。执行阶段发现故障，复验阶段验证修复。')); replace('result-heading'); replace('comparison'); $('checks-count').textContent = '—'; return; }
  const checks = latest?.checks || [];
  const passed = checks.filter(c => c.passed).length;
  $('checks-count').textContent = checks.length ? `${passed} / ${checks.length} 通过` : '待执行验证';
  let title = '操作完成 · 待执行验证', tone = 'result-neutral';
  if (resultAction?.state === 'FAILED') { title = '执行失败 · 查看日志'; tone = 'result-fail'; }
  else if (run.phase === 'verified' && resultAction?.kind === 'verify' && resultAction.state === 'SUCCEEDED' && latest?.passed === true) { title = '构建成功'; tone = 'result-pass'; }
  else if (resultAction?.kind === 'execute' && resultAction.state === 'SUCCEEDED' && latest?.passed === false && latest.fault_signature?.observed === true) { title = '已捕获预期故障'; tone = 'result-fail'; }
  else if (resultAction?.kind === 'diagnose') { title = '诊断已完成'; }
  else if (latest?.passed === false) { title = '检测到失败 · 待核对故障证据'; tone = 'result-fail'; }
  else if (latest?.passed === true) { title = '当前步骤断言通过'; tone = 'result-pass'; }
  const heading = el('div', `result-summary ${tone}`);
  heading.append(el('strong', '', title), el('span', 'badge', 'Lab'), el('p', '', resultAction?.error || latest?.summary || '本次操作未完成，请查看原始执行记录。'));
  replace('result-heading', heading);
  replace('check-list', ...(checks.length ? checks.map(check => {
    const row = el('article', 'check-row');
    const head = el('div', 'check-heading'); head.append(el('span', check.passed ? 'check-state success' : 'check-state failure', check.passed ? '✓ 通过' : '× 未通过'), el('strong', '', check.label));
    row.append(head);
    if (check.expected !== null && check.expected !== undefined || check.actual !== null && check.actual !== undefined) {
      const values = el('dl', 'check-values');
      values.append(el('dt', '', '预期'), el('dd', 'mono', formatValue(check.expected)), el('dt', '', '实测'), el('dd', 'mono', formatValue(check.actual))); row.append(values);
    }
    return row;
  }) : [empty(resultAction?.state === 'FAILED' ? '执行器未提供本次有效断言，请查看失败阶段与原始日志。' : '本步骤已完成实际输入或状态变更；需要执行流程或重新验证后，才能判断断言结果。')]));
  if (latest?.facts && Object.keys(latest.facts).length) $('check-list').append(detail('本次实际观察 / facts', formatValue(latest.facts), 'facts-detail'));
  const before = run.actions.findLast(a => a.kind === 'execute' && a.result)?.result;
  const after = run.actions.findLast(a => a.kind === 'verify' && a.result)?.result;
  if (!before) { replace('comparison'); return; }
  const comparison = el('div', 'comparison');
  for (const [label, result] of [['修复前 / 执行流程', before], ['修复后 / 重新验证', after]]) {
    const box = el('div', 'comparison-item'); box.append(el('span', 'eyebrow', label), el('strong', result ? result.passed ? 'success' : 'failure' : 'muted', result ? `${result.checks.filter(c => c.passed).length} / ${result.checks.length} 通过` : '等待复验'), el('small', '', result?.summary || '应用修复后重新验证，形成独立回执。')); comparison.append(box);
  }
  replace('comparison', comparison);
}
