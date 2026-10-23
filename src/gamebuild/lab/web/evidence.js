import { $, el, empty, detail, replace, setOptions } from './dom.js';
import { STEPS, state, duration, clock, formatValue } from './model.js';
import { evidenceUrl, readEvidence } from './api.js';

let eventSignature = '', fileSignature = '', previewSerial = 0;
const name = kind => STEPS.find(s => s.kind === kind)?.label || kind;

function diffBlock(diff) {
  const pre = el('pre', 'diff');
  for (const line of String(diff).split('\n')) {
    pre.append(el('span', line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-remove' : '', `${line}\n`));
  }
  return pre;
}

function eventNode(event) {
  const node = el('article', `event event-${event.status.toLowerCase()}`);
  node.dataset.seq = event.seq;
  const head = el('div', 'event-heading');
  head.append(el('span', 'event-stage', event.stage), el('span', 'mono event-time', clock(event.at)));
  node.append(head, el('p', 'event-message', event.message));
  const data = event.data || {};
  if (data.duration_ms !== undefined || data.exit_code !== undefined) {
    const meta = el('div', 'event-meta mono');
    if (data.exit_code !== undefined) meta.append(el('span', data.exit_code === 0 ? 'success' : 'failure', `exit ${data.exit_code}`));
    if (data.duration_ms !== undefined) meta.append(el('span', '', duration(data.duration_ms)));
    node.append(meta);
  }
  if (data.diff !== undefined) {
    const block = el('details', 'event-detail');
    block.append(el('summary', '', `文件 diff · ${data.path || '变更'}`), diffBlock(data.diff));
    node.append(block);
  }
  if (data.stdout !== undefined) node.append(detail('原始命令输出 / stdout', data.stdout || '（无标准输出）', 'event-detail'));
  const extra = Object.fromEntries(Object.entries(data).filter(([key]) => !['stdout', 'diff', 'duration_ms', 'exit_code'].includes(key)));
  if (Object.keys(extra).length) node.append(detail('结构化执行记录', formatValue(extra), 'event-detail'));
  return node;
}

export function renderEvidence() {
  const run = state.run;
  const actions = run?.actions || [];
  setOptions($('evidence-action'), [['', '全部步骤'], ...actions.map(a => [a.id, `${name(a.kind)} · ${a.state}`])], state.actionId);
  $('tab-events').setAttribute('aria-selected', String(state.tab === 'events'));
  $('tab-files').setAttribute('aria-selected', String(state.tab === 'files'));
  $('events-panel').hidden = state.tab !== 'events';
  $('files-panel').hidden = state.tab !== 'files';
  const events = (run?.events || []).filter(e => !state.actionId || e.action_id === state.actionId);
  const files = (run?.evidence || []).filter(e => !state.actionId || e.action_id === state.actionId);
  $('event-count').textContent = events.length;
  $('file-count').textContent = files.length;
  const eventKey = JSON.stringify([run?.id, state.actionId, events]);
  if (eventSignature !== eventKey) {
    const open = new Set([...$('event-list').querySelectorAll('details[open]')].map(n => `${n.closest('[data-seq]').dataset.seq}:${n.querySelector('summary').textContent}`));
    replace('event-list', ...(events.length ? events.map(eventNode) : [empty(run ? '此步骤尚未产生执行记录。' : '执行后，点击阶段节点可定位这里的命令、日志与文件变更。')]));
    $('event-list').querySelectorAll('details').forEach(n => { n.open = open.has(`${n.closest('[data-seq]').dataset.seq}:${n.querySelector('summary').textContent}`); });
    eventSignature = eventKey;
  }
  const fileKey = JSON.stringify([run?.id, state.actionId, files]);
  if (fileSignature !== fileKey) {
    replace('file-list', ...(files.length ? files.map(file => {
      const row = el('article', 'file-item');
      const fileName = file.path.split('/').pop();
      const title = el('button', 'file-open', fileName);
      title.type = 'button'; title.title = file.path;
      const link = el('a', 'file-download', '↓ 下载');
      link.href = evidenceUrl(run.id, file.id); link.download = fileName;
      if (/\.(json|log|txt|diff|xml)$/i.test(fileName)) title.addEventListener('click', () => showFile(run.id, file));
      else title.addEventListener('click', () => link.click());
      const meta = el('p', 'file-meta mono', `${file.size.toLocaleString()} B · SHA256 ${file.sha256.slice(0, 12)}…`);
      row.append(title, link, meta, detail('路径与完整 SHA256', `${file.path}\n\n${file.sha256}`));
      return row;
    }) : [empty('步骤完成后，执行器会登记可读取和下载的真实证据。')]));
    if (fileSignature && JSON.parse(fileSignature)[0] !== run?.id) closePreview();
    fileSignature = fileKey;
  }
}

async function showFile(runId, file) {
  const serial = ++previewSerial;
  $('file-preview').hidden = false;
  $('file-title').textContent = file.path.split('/').pop();
  $('file-content').textContent = '正在读取实际文件…';
  try {
    const content = await readEvidence(runId, file.id);
    if (serial !== previewSerial || state.run?.id !== runId) return;
    let text = content;
    if (file.path.endsWith('.json')) { try { text = JSON.stringify(JSON.parse(content), null, 2); } catch { /* Preserve raw malformed evidence. */ } }
    $('file-content').textContent = text || '（空文件）';
  } catch (error) { if (serial === previewSerial) $('file-content').textContent = error.message; }
}
export function closePreview() { previewSerial++; $('file-preview').hidden = true; }
