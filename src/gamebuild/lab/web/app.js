import { api } from './api.js';
import { $, } from './dom.js';
import { state, update, subscribe, currentCase, busy } from './model.js';
import { buildSteps, render } from './view.js';
import { closePreview } from './evidence.js';
import { renderTrust } from './incident.js';

let selection = 0;
let monitor = 0;
let automation = null;
const pendingKeys = new Map();
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function writeHash() {
  const params = new URLSearchParams({ case: state.caseId });
  if (state.run) params.set('run', state.run.id);
  history.replaceState(null, '', `#${params}`);
}

function acceptRun(run, epoch, changes = {}) {
  if (epoch !== selection || run.case_id !== state.caseId) return false;
  update({ run, variant: run.variant, ...changes }); writeHash(); return true;
}

async function refreshHistory() {
  const histories = await api.history(); update({ histories });
}

async function poll(runId, epoch, actionId = null) {
  for (;;) {
    const run = await api.run(runId);
    if (epoch !== selection || state.run?.id !== runId) return null;
    acceptRun(run, epoch);
    if (!run.busy_action) {
      await refreshHistory();
      const action = actionId && run.actions.find(a => a.id === actionId);
      if (action && !['SUCCEEDED', 'CANCELLED'].includes(action.state)) throw new Error(action.error || '执行异常，请查看本步骤证据。');
      return run;
    }
    await delay(500);
  }
}

function watchRestored(runId, epoch) {
  const id = ++monitor;
  poll(runId, epoch).catch(error => { if (id === monitor && epoch === selection) update({ error: error.message }); });
}

async function chooseCase(id, requestedRun = '') {
  if (!state.cases.some(c => c.id === id)) id = state.cases[0]?.id || '01';
  if (automation) automation.cancelled = true;
  automation = null;
  const epoch = ++selection; monitor++;
  const selected = state.cases.find(c => c.id === id);
  closePreview();
  update({ caseId: id, run: null, variant: selected?.variants[0]?.id || '', loading: true, submitting: false, autoRunning: false, cancelRequested: false, actionId: '', error: '' });
  try {
    await refreshHistory();
    if (epoch !== selection) return;
    const candidate = requestedRun || state.histories.find(r => r.case_id === id)?.id;
    if (candidate) {
      const run = await api.run(candidate);
      if (epoch !== selection) return;
      if (run.case_id !== id) throw new Error('该实验不属于当前场景，请从实验历史重新选择。');
      acceptRun(run, epoch);
      update({ actionId: run.actions.at(-1)?.id || '' });
      if (run.busy_action) watchRestored(run.id, epoch);
    }
    writeHash();
  } catch (error) { if (epoch === selection) update({ error: error.message }); }
  finally { if (epoch === selection) update({ loading: false }); }
}

async function createRun(epoch) {
  // The previous experiment's verified phase must not survive the start of a
  // fresh request: it would present old success as the new experiment's state.
  update({ run: null, actionId: '' }); writeHash();
  const run = await api.create(state.caseId, state.variant || currentCase().variants[0].id);
  // Publish a ready backend snapshot and its enabled next control atomically.
  // A secondary history request must never keep the valid next action disabled.
  if (!acceptRun(run, epoch, { submitting: false, actionId: '', cancelRequested: false,
    histories: [run, ...state.histories.filter(item => item.id !== run.id)] })) return null;
  return run;
}

async function newRun(event) {
  if (busy()) return;
  const epoch = selection;
  const keyboardStarted = event?.detail === 0;
  update({ submitting: true, error: '', cancelRequested: false });
  try {
    const run = await createRun(epoch);
    if (run && keyboardStarted && [document.body, $('new-run')].includes(document.activeElement)) $('step-prepare').focus();
  }
  catch (error) { if (epoch === selection) update({ error: error.message }); }
  finally { if (epoch === selection) update({ submitting: false }); }
}

async function executeStep(kind, epoch, sequence = null) {
  const runId = state.run?.id;
  if (!runId || epoch !== selection || sequence?.cancelled) return null;
  const keyId = `${runId}:${kind}`;
  const requestKey = pendingKeys.get(keyId) || crypto.randomUUID();
  pendingKeys.set(keyId, requestKey);
  update({ submitting: true, error: '', ...(sequence ? {} : { cancelRequested: false }) });
  try {
    const action = await api.action(runId, kind, requestKey);
    pendingKeys.delete(keyId);
    if (epoch !== selection) return null;
    update({ actionId: action.id, tab: 'events' });
    // A stop can arrive while the POST response is still in flight.
    if (state.cancelRequested || sequence?.cancelled) await api.cancel(runId);
    return await poll(runId, epoch, action.id);
  } finally { if (epoch === selection) update({ submitting: false }); }
}

async function step(kind) {
  if (busy() || !state.run?.allowed_actions.includes(kind)) return;
  const epoch = selection;
  try { await executeStep(kind, epoch); }
  catch (error) { if (epoch === selection) update({ error: error.message }); }
}

async function runAll() {
  if (busy()) return;
  const epoch = selection;
  const sequence = { cancelled: false };
  automation = sequence;
  update({ autoRunning: true, cancelRequested: false, error: '' });
  try {
    if (!state.run || state.run.phase === 'verified' || state.run.variant !== state.variant) await createRun(epoch);
    while (!sequence.cancelled && epoch === selection && state.run) {
      if (state.run.status === 'CANCELLED' && state.cancelRequested) break;
      const kind = state.run.allowed_actions[0];
      if (!kind) break;
      const run = await executeStep(kind, epoch, sequence);
      if (!run || run.status === 'CANCELLED') break;
    }
  } catch (error) { if (epoch === selection) update({ error: error.message }); }
  finally {
    if (automation === sequence) automation = null;
    if (epoch === selection) update({ autoRunning: false, submitting: false });
  }
}

async function cancel() {
  if (state.cancelRequested) return;
  const epoch = selection;
  if (automation) automation.cancelled = true;
  update({ cancelRequested: true, error: '' });
  try {
    const run = state.run;
    if (run) {
      await api.cancel(run.id);
      if (!state.submitting && !run.busy_action) {
        // In the gap between steps the sequence stops here; no backend phase is invented.
        if (epoch === selection) update({ autoRunning: false, cancelRequested: false });
      } else if (!state.submitting) watchRestored(run.id, epoch);
    }
  } catch (error) { if (epoch === selection) update({ error: error.message, cancelRequested: false }); }
}

function selectAction(id) { update({ actionId: id, tab: 'events' }); $('audit').open = true; }

async function retry() {
  const epoch = selection;
  update({ error: '', loading: true });
  try {
    const cases = await api.cases(); update({ cases });
    await refreshHistory();
    if (state.run) {
      const run = await api.run(state.run.id);
      if (acceptRun(run, epoch) && run.busy_action) watchRestored(run.id, epoch);
    } else await chooseCase(state.caseId);
  } catch (error) { update({ error: error.message }); }
  finally { if (epoch === selection) update({ loading: false }); }
}

buildSteps(step, selectAction);
subscribe(() => render(chooseCase, selectAction));
$('new-run').addEventListener('click', newRun);
$('run-all').addEventListener('click', runAll);
$('cancel-run').addEventListener('click', cancel);
$('retry').addEventListener('click', retry);
$('case-search').addEventListener('input', event => update({ search: event.target.value }));
$('role-filter').addEventListener('change', event => update({ role: event.target.value }));
$('fault-variant').addEventListener('change', event => update({ variant: event.target.value }));
$('history-select').addEventListener('change', event => chooseCase(state.caseId, event.target.value));
$('evidence-action').addEventListener('change', event => update({ actionId: event.target.value }));
$('tab-events').addEventListener('click', () => update({ tab: 'events' }));
$('tab-files').addEventListener('click', () => update({ tab: 'files' }));
for (const [index, id] of ['tab-events', 'tab-files'].entries()) {
  $(id).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'events' : event.key === 'End' ? 'files' : index ? 'events' : 'files';
    update({ tab: next }); $(`tab-${next}`).focus();
  });
}
$('close-preview').addEventListener('click', closePreview);
window.addEventListener('hashchange', () => {
  const hash = new URLSearchParams(location.hash.slice(1));
  // In-page accessibility anchors are not application routes.
  if (!hash.has('case')) return;
  chooseCase(hash.get('case') || '01', hash.get('run') || '');
});

async function init() {
  renderTrust(null);
  api.evaluation().then(renderTrust).catch(error => renderTrust(null, error.message));
  render(chooseCase, selectAction);
  try {
    const cases = await api.cases(); update({ cases });
    const hash = new URLSearchParams(location.hash.slice(1));
    await chooseCase(hash.get('case') || '01', hash.get('run') || '');
  } catch (error) { update({ loading: false, error: error.message }); }
}
init();
