const BASE = '';

// 从 localStorage 加载用户选择的 LLM provider + model + 可选自带 Key（BYOK）
// URL/Base-URL 永不从前端传；Key 仅用于服务端 Authorization 头
function getLLMHeaders() {
  try {
    const raw = localStorage.getItem('llm_config');
    if (!raw) return {};
    const config = JSON.parse(raw);
    const headers = {};
    if (config.provider) headers['X-LLM-Provider'] = config.provider;
    if (config.model) headers['X-LLM-Model'] = config.model;
    if (config.apiKey) headers['X-LLM-API-Key'] = config.apiKey;
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

// 请求超时：LLM 分析链路可能挂起，默认 30s 中止（上传单独 60s）
const REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 60000;

// 401 全局登出：token 失效/残留时清空本地认证状态并通知应用跳转登录页，
// 避免用户卡在受保护页面反复报 401（旧 token 残留问题）
function handleAuthExpired(url) {
  const isAuthApi = url.includes('/auth/login') || url.includes('/auth/register');
  if (isAuthApi) return; // 登录/注册本身的 401 是"密码错误"，不登出
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_cache');
    localStorage.removeItem('dataset_cache');
    localStorage.removeItem('reports_cache');
  } catch { /* ignore */ }
  window.dispatchEvent(new Event('auth:expired'));
}

async function request(url, options = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}${url}`, {
      headers: { 'Content-Type': 'application/json', ...authHeaders, ...llmHeaders, ...options.headers },
      signal: controller.signal,
      ...options,
    });
    if (!res.ok) {
      if (res.status === 401) handleAuthExpired(url);
      throw await parseError(res);
    }
    try {
      return await res.json();
    } catch {
      return {};
    }
  } finally {
    clearTimeout(timer);
  }
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
  return err;
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}/datasets/upload`, {
      method: 'POST', body: form, headers: { ...authHeaders, ...llmHeaders }, signal: controller.signal,
    });
    if (!res.ok) {
      if (res.status === 401) handleAuthExpired('/datasets/upload');
      throw await parseError(res);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
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

// 分析直播：SSE 流式获取 Agent 实时决策事件（fetch + ReadableStream 解析）
// options.onEvent(ev)：每个 "data: {json}" 事件回调；返回 'stop' 可中断消费
// options.signal：AbortSignal（用户取消）
export async function generateReportStream(payload, { onEvent, signal } = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const res = await fetch(`${BASE}/reports/generate-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders, ...llmHeaders },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const raw of chunk.split('\n')) {
        if (raw.startsWith('data: ')) {
          try {
            const ev = JSON.parse(raw.slice(6));
            if (onEvent && onEvent(ev) === 'stop') {
              await reader.cancel();
              return;
            }
          } catch { /* 忽略畸形帧 */ }
        }
      }
    }
  }
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
