const base = '/lab/api';

export async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(base + path, { credentials: 'same-origin', cache: 'no-store', ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers } });
  } catch {
    throw new Error('无法连接本机实验服务。请检查服务是否仍在运行，然后重试。');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json();
}

export const api = {
  evaluation: () => request('/evaluation'),
  cases: () => request('/cases'),
  history: () => request('/runs'),
  create: (case_id, variant) => request('/runs', { method: 'POST', body: JSON.stringify({ case_id, variant }) }),
  run: id => request(`/runs/${encodeURIComponent(id)}`),
  action: (id, kind, request_key) => request(`/runs/${encodeURIComponent(id)}/actions`, {
    method: 'POST', body: JSON.stringify({ kind, request_key }) }),
  cancel: id => request(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: '{}' }),
};

export function evidenceUrl(rid, eid) {
  return `${base}/runs/${encodeURIComponent(rid)}/evidence/${encodeURIComponent(eid)}`;
}

export async function readEvidence(rid, eid) {
  const response = await fetch(evidenceUrl(rid, eid), { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error(`证据读取失败（HTTP ${response.status}）`);
  return response.text();
}
