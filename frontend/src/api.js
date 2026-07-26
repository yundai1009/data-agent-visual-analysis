const BASE = '';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/datasets/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function loadExample() {
  return request('/datasets/load-example', { method: 'POST' });
}

export async function getDataset(id) {
  return request(`/datasets/${id}`);
}

export async function listDatasets(limit = 50) {
  return request(`/datasets/?limit=${limit}`);
}

export async function cleanDataset(id, ops) {
  const params = new URLSearchParams();
  if (ops.deduplicate) params.set('deduplicate', 'true');
  if (ops.fill_missing) params.set('fill_missing', 'true');
  if (ops.fill_strategy) params.set('fill_strategy', ops.fill_strategy);
  if (ops.drop_empty_rows) params.set('drop_empty_rows', 'true');
  return request(`/datasets/${id}/clean?${params}`, { method: 'POST' });
}

export async function generateReport(payload) {
  return request('/reports/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function healthCheck() {
  return request('/health');
}
