export const STEPS = [
  { kind: 'prepare', phase: 'prepared', label: '准备实验', stage: '输入基线', note: '创建文件、版本与独立执行空间' },
  { kind: 'inject', phase: 'injected', label: '制造问题', stage: '故障注入', note: '对当前变体施加实际变更' },
  { kind: 'execute', phase: 'reproduced', label: '执行流程', stage: '构建与检查', note: '观测故障，保留失败断言' },
  { kind: 'diagnose', phase: 'diagnosed', label: '查看诊断', stage: '根因定位', note: '沿着日志与规则定位失败' },
  { kind: 'repair', phase: 'repaired', label: '应用修复', stage: '修复变更', note: '修改输入或系统状态，记录差异' },
  { kind: 'verify', phase: 'verified', label: '重新验证', stage: '复验与归档', note: '重新执行，用实际断言验收' },
];
export const PHASE_LABELS = { created: '实验已创建', prepared: '基线已准备', injected: '问题已制造', reproduced: '问题已复现', diagnosed: '已诊断', repaired: '已修复，待验证', verified: '复验通过' };
export function statusLabel(run) {
  if (!run) return '等待创建实验';
  if (run.status === 'CANCELLED') return '已取消';
  if (run.status === 'INTERRUPTED') return '服务中断，可重试当前步骤';
  if (run.status === 'FAILED') return '执行异常，查看证据后重试';
  if (run.busy_action) {
    const action = run.actions.find(a => a.id === run.busy_action);
    return `${STEPS.find(s => s.kind === action?.kind)?.label || '操作'}进行中`;
  }
  return PHASE_LABELS[run.phase] || run.status;
}
export const state = { cases: [], caseId: '01', run: null, histories: [], search: '', role: '', variant: '',
  loading: true, submitting: false, autoRunning: false, cancelRequested: false, error: '', actionId: '', tab: 'events' };
const listeners = new Set();
export function update(changes = {}) { Object.assign(state, changes); listeners.forEach(fn => fn(state)); }
export function subscribe(fn) { listeners.add(fn); }
export const currentCase = () => state.cases.find(c => c.id === state.caseId);
export const busy = () => state.loading || state.submitting || state.autoRunning || !!state.run?.busy_action;
export function formatValue(value) { return value === undefined || value === null ? '—' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
export function clock(value) { return new Date(value * 1000).toLocaleTimeString('zh-CN', { hour12: false }); }
export function duration(value) { return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ms`; }
