import { $, el, empty, replace, setOptions } from './dom.js';
import { STEPS, state, currentCase, busy, statusLabel, PHASE_LABELS } from './model.js';
import { renderEvidence } from './evidence.js';
import { renderTimeline } from './timeline.js';
import { renderIncident } from './incident.js';

let sidebarKey = '', caseKey = '', timelineKey = '';
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
  const run = state.run?.variant === state.variant ? state.run : null;
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
  renderIncident(selected, onSelectAction);
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
