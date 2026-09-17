/**
 * api/request.js — 请求基础层（token 注入、超时、错误解析、全局登出）
 *
 * 从 api.js 拆分，职责：所有与 HTTP 请求本身相关的逻辑。
 * 被 api/upload.js、api/endpoints.js 及 api/index.js re-export。
 */

const BASE = '';

// --- 登录态存储（阶段 46：双存储层）---
// localStorage = 「记住我」（长期，关浏览器不丢）；sessionStorage = 不记住（会话级，关浏览器失效）。
// 读取：localStorage 优先（记住我的 token 更长期）；清除：两个都清，保证任何场景不残留。
export function getStoredToken() {
  try { return localStorage.getItem('access_token') || sessionStorage.getItem('access_token') || ''; } catch { return ''; }
}
export function setStoredToken(token, remember) {
  try {
    if (remember) { localStorage.setItem('access_token', token); sessionStorage.removeItem('access_token'); }
    else { sessionStorage.setItem('access_token', token); localStorage.removeItem('access_token'); }
  } catch { /* ignore */ }
}
export function clearStoredToken() {
  try { localStorage.removeItem('access_token'); sessionStorage.removeItem('access_token'); } catch { /* ignore */ }
}

// --- LLM / Auth 头构建 ---

function getLLMHeaders() {
  try {
    const config = {};
    const raw = localStorage.getItem('llm_config');
    const sessRaw = sessionStorage.getItem('llm_config');
    if (raw) Object.assign(config, JSON.parse(raw));
    if (sessRaw) Object.assign(config, JSON.parse(sessRaw));
    const headers = {};
    if (config.provider) headers['X-LLM-Provider'] = config.provider;
    if (config.model) headers['X-LLM-Model'] = config.model;
    if (config.apiKey) headers['X-LLM-API-Key'] = config.apiKey;
    return headers;
  } catch { return {}; }
}

function getAuthHeaders() {
  try {
    const token = getStoredToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch { return {}; }
}

// --- 常量 ---

const REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 60000;

// --- 401 全局登出 ---

function handleAuthExpired(url) {
  const isAuthApi = url.includes('/auth/login') || url.includes('/auth/register');
  if (isAuthApi) return;
  try {
    clearStoredToken();
    localStorage.removeItem('user_cache');
    localStorage.removeItem('dataset_cache');
    localStorage.removeItem('reports_cache');
  } catch { /* ignore */ }
  window.dispatchEvent(new Event('auth:expired'));
}

// --- 通用请求封装 ---

async function request(url, options = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options._customTimeout || REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}${url}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...llmHeaders,
        ...options.headers,
      },
      signal: options.signal || controller.signal,
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
  } catch (e) {
    if (e?.name === 'AbortError') {
      const err = new Error('请求超时了，请重试（分析类请求可能需要更长时间）');
      err.status = 0;
      throw err;
    }
    if (e instanceof TypeError) {
      const msg = e.message || '';
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('Load failed')) {
        const err = new Error('连不上服务器，请检查后端服务是否已启动');
        err.status = 0;
        throw err;
      }
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// --- 错误解析 ---

const STATUS_HINTS = {
  400: '请求参数不对，请检查后重试',
  401: '登录状态已失效，请重新登录',
  403: '没有权限执行这个操作',
  404: '内容不存在或已被删除',
  413: '文件太大了，请压缩后再试',
  422: '提交的内容不合法，请检查',
  429: '操作太频繁，请稍等一会儿再试',
  500: '服务器开小差了，请稍后重试',
  503: '服务暂时繁忙，请稍后重试',
};

async function parseError(res) {
  let message = STATUS_HINTS[res.status] || `请求失败（HTTP ${res.status}）`;
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

export {
  BASE, getLLMHeaders, getAuthHeaders,
  REQUEST_TIMEOUT_MS, UPLOAD_TIMEOUT_MS,
  handleAuthExpired, request, STATUS_HINTS, parseError,
};
