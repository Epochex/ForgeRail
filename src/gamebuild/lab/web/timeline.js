import { $, el, empty, replace } from './dom.js';
import { STEPS, duration } from './model.js';

const NS = 'http://www.w3.org/2000/svg';
function bar(value, maximum, kind) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 240 8'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
  const rect = document.createElementNS(NS, 'rect');
  rect.setAttribute('width', String(Math.max(2, value / maximum * 240))); rect.setAttribute('height', '8'); rect.setAttribute('rx', '2');
  rect.setAttribute('class', `trace-bar trace-${kind}`); svg.append(rect); return svg;
}

export function renderTimeline(run, selectAction) {
  if (!run?.actions.length) { replace('timeline', empty('等待执行事件。阶段耗时来自实际时钟采样，点击可定位执行证据。')); return; }
  const finished = run.actions.filter(a => a.finished_at);
  const maximum = Math.max(1, ...finished.map(a => (a.finished_at - a.created_at) * 1000));
  const list = el('div', 'trace-list');
  for (const action of run.actions) {
    const step = STEPS.find(s => s.kind === action.kind);
    const row = el('button', `trace-row ${action.state === 'RUNNING' ? 'trace-running' : ''}`);
    row.type = 'button'; row.title = `查看${step.label}的实际阶段与证据`;
    const ms = action.finished_at ? (action.finished_at - action.created_at) * 1000 : null;
    row.append(el('span', 'trace-label', step.label), bar(ms ?? 0, maximum, action.kind), el('span', 'mono trace-time', ms === null ? '运行中' : duration(ms)));
    row.addEventListener('click', () => selectAction(action.id)); list.append(row);
  }
  const stages = (run.events || []).filter(e => e.data?.duration_ms !== undefined);
  const meta = el('p', 'trace-caption', `已采集 ${stages.length} 条实际阶段耗时。上图包含步骤调度与执行开销；各命令耗时见右侧证据。`);
  replace('timeline', list, meta);
}
