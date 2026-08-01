const BASE = '';

// 从 localStorage 加载用户选择的 LLM provider + model（不含 Key / Base-URL）
function getLLMHeaders() {
  try {
    const raw = localStorage.getItem('llm_config');
    if (!raw) return {};
    const config = JSON.parse(raw);
    const headers = {};
    if (config.provider) headers['X-LLM-Provider'] = config.provider;
    if (config.model) headers['X-LLM-Model'] = config.model;
    return headers;
  } catch { return {}; }
}

// 从 localStorage 读取登录 token
function getAuthHeaders() {
  try {
    const token = localStorage.getItem('access_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch { return {}; }
}

async function request(url, options = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...llmHeaders, ...options.headers },
    ...options,
  });
  if (!res.ok) {
    throw await parseError(res);
  }
  return res.json();
}

// 统一错误解析：后端返回 {code, message, request_id}，前端展示 message
async function parseError(res) {
  let message = `请求失败（HTTP ${res.status}）`;
  let requestId = '';
  try {
    const body = await res.json();
    if (body && body.message) message = body.message;
    if (body && body.request_id) requestId = body.request_id;
  } catch { /* 非 JSON 响应，用默认信息 */ }
  const err = new Error(message);
  err.status = res.status;
  err.requestId = requestId;
  err.code = null;
  return err;
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const res = await fetch(`${BASE}/datasets/upload`, { method: 'POST', body: form, headers: { ...authHeaders, ...llmHeaders } });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// ---- 认证 ----

export async function login(username, password) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export async function sendCode(email) {
  return request('/auth/send-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function register(username, email, code, password) {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, email, code, password }),
  });
}

export async function fetchMe() {
  return request('/auth/me');
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

// ---- 报表历史（阶段 6：后端持久化）----

export async function listReports(limit = 50) {
  return request(`/reports/?limit=${limit}`);
}

export async function getReport(reportId) {
  return request(`/reports/${reportId}`);
}

export async function deleteReport(reportId) {
  return request(`/reports/${reportId}`, { method: 'DELETE' });
}

export async function healthCheck() {
  return request('/health');
}
