/* =============================================================================
 * 文件：frontend/src/api.js —— 前端 API 请求封装层（唯一的 HTTP 出口）
 * 功能：
 *   1. 统一 request()：自动注入 token（Authorization: Bearer）+ LLM 配置头，
 *      30s 超时、非 2xx 统一抛错、401 自动触发全局登出（auth:expired 事件）
 *   2. parseError()：把后端 {code, message, request_id} 解析成带 status 的 Error
 *   3. generateReportStream()：SSE 流式解析 Agent 决策事件（fetch + ReadableStream）
 *   4. 全部业务接口：认证 / 数据集 / 报表 / 分享 / 看板 / 管理后台 / 反馈 / 合规导出
 * 依赖：
 *   - localStorage：access_token（token 注入）、llm_config（BYOK 配置）
 *   - validators/exportFilename.js：解析 Content-Disposition 导出文件名
 *   - 被所有页面 import（Analysis/Report/Account/Data/Login/…）
 * 配合：AppContext.jsx 监听本文件广播的 'auth:expired' 事件做全局登出
 * ============================================================================= */
import parseContentDispositionFilename from './validators/exportFilename';

const BASE = '';

// 从 localStorage 加载用户选择的 LLM provider + model + 可选自带 Key（BYOK）
// URL/Base-URL 永不从前端传；Key 仅用于服务端 Authorization 头（防止 Key 明文出现在网络面板）
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

// 从 localStorage 读取登录 token，拼成 Authorization 请求头
function getAuthHeaders() {
  try {
    const token = localStorage.getItem('access_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch { return {}; }
}

// 请求超时：LLM 分析链路可能挂起，默认 30s 中止（上传单独 60s）
const REQUEST_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 60000;

// 401 全局登出：token 失效/残留时清空本地认证状态并广播事件通知应用跳转登录页，
// 避免用户卡在受保护页面反复报 401（旧 token 残留问题）
// 入参 url：触发 401 的接口路径，用于排除登录/注册接口（它们的 401 是“密码错误”）
function handleAuthExpired(url) {
  const isAuthApi = url.includes('/auth/login') || url.includes('/auth/register');
  if (isAuthApi) return; // 登录/注册本身的 401 是"密码错误"，不登出
  // 【关键行】清空本地全部认证与业务缓存。
  // 为什么：token 已失效，继续留着只会让每次请求都 401；user_cache/dataset_cache
  //   是登录态附属信息，一并清掉避免界面展示过期数据。
  // 删除后果：401 后 token 残留，用户反复请求反复报错，且永远不会被踢回登录页。
  // 替代方案：只清 token 不清 user_cache（少两行），但会留下“已登出却显示用户名”的
  //   残留状态；一次清干净更彻底。
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_cache');
    localStorage.removeItem('dataset_cache');
    localStorage.removeItem('reports_cache');
  } catch { /* ignore */ }
  // 【关键行】广播全局登出事件，AppContext 监听后把 isAuthed 置 false，触发路由跳转。
  // 为什么：请求层拿不到 React 状态，必须通过事件让状态层“知道”认证失效。
  // 删除后果：缓存清了但 isAuthed 仍为 true，页面不跳转，用户以为还登录着。
  // 替代方案：请求层直接 import AppContext 调 setState（循环依赖 api.js ↔ AppContext）；
  //   或用状态管理库（Redux/Zustand）把请求层和状态层打通，本项目用事件解耦更轻。
  window.dispatchEvent(new Event('auth:expired'));
}

// 通用请求封装：任何业务接口都走这里，自动获得 token 注入 + 超时 + 401 处理 + 错误解析
// 入参：url（接口路径）、options（fetch 选项：method/body/headers 等）
// 返回：解析后的 JSON 对象；非 2xx 抛出带 status 的 Error（调用方 catch 展示 message）
async function request(url, options = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = new AbortController();
  // 超时兜底：LLM 分析链路可能挂起，30s 强制中止，避免按钮永远 loading
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    // 【关键行】fetch 时把 token 注入 Authorization 头 —— 后端唯一身份凭证。
    // 为什么：接口鉴权靠 header 而非 cookie，因为本项目是前后端分离部署，
    //   cookie 跨域携带麻烦且易受 CSRF 攻击；Bearer token 由前端显式携带更可控。
    // 删除后果：所有接口返回 401，用户连登录外的任何页面都进不去（或界面全报错）。
    // 替代方案：用 axios 拦截器统一加（代码更少），但会多一个依赖；原生 fetch 封装
    //   已足够，且保持与 SSE 流式请求同一套 header 拼装逻辑。
    const res = await fetch(`${BASE}${url}`, {
      headers: { 'Content-Type': 'application/json', ...authHeaders, ...llmHeaders, ...options.headers },
      signal: controller.signal,
      ...options,
    });
    if (!res.ok) {
      // 401 专线处理：先全局登出，再抛错误给调用方展示（不重复走 parseError 的通用路径）
      if (res.status === 401) handleAuthExpired(url);
      throw await parseError(res);
    }
    try {
      return await res.json();
    } catch {
      return {}; // 响应体不是 JSON（如空 204）时返回空对象，调用方统一处理
    }
  } finally {
    clearTimeout(timer);
  }
}

// 统一错误解析：后端返回 {code, message, request_id}，前端只需展示 message 即可
// 入参 res：fetch 的 Response 对象；返回：带 status/requestId 的 Error（便于调用方分类处理）
async function parseError(res) {
  let message = `请求失败（HTTP ${res.status}）`;
  let requestId = '';
  try {
    const body = await res.json();
    // 优先用后端给的业务文案（如“用户名已存在”），比 HTTP 状态码更友好
    if (body && body.message) message = body.message;
    if (body && body.request_id) requestId = body.request_id; // 排查问题时按 request_id 查后端日志
  } catch { /* 非 JSON 响应，用默认信息 */ }
  const err = new Error(message);
  err.status = res.status;       // 调用方可用 e.status 分类处理（401/413/400）
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

export async function changePassword(oldPassword, newPassword) {
  return request('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

export async function changeUsername(username) {
  return request('/auth/change-username', {
    method: 'POST',
    body: JSON.stringify({ username }),
  });
}

export async function sendCode(email) {
  return request('/auth/send-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

// P2 加固：密码重置（重置验证码 + 重置密码）
export async function sendResetCode(email) {
  return request('/auth/reset-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(email, code, password) {
  return request('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ email, code, password }),
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

// ---- 账号级 LLM Key（BYOK 后端存储，登录后任意设备自动生效）----

export async function getAccountLLMKey() {
  return request('/auth/llm-key');
}

export async function fetchLLMProviders() {
  return request('/auth/llm-providers');
}

export async function saveCustomProvider(payload) {
  return request('/auth/llm-providers/custom', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function deleteCustomProvider(name) {
  return request(`/auth/llm-providers/custom/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export async function testCustomProvider(baseUrl, apiKey) {
  return request('/auth/llm-providers/test', {
    method: 'POST',
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
  });
}

export async function saveAccountLLMKey(apiKey) {
  return request('/auth/llm-key', {
    method: 'PUT',
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function clearAccountLLMKey() {
  return request('/auth/llm-key', { method: 'DELETE' });
}

export async function loadExample() {
  return request('/datasets/load-example', { method: 'POST' });
}

export async function getDataset(id) {
  return request(`/datasets/${id}`);
}

export async function listDatasets(limit = 200, q = '', sort = 'created_at_desc') {
  const p = new URLSearchParams({ limit: String(limit) });
  if (q) p.set('q', q);
  p.set('sort', sort);
  return request(`/datasets/?${p.toString()}`);
}

export async function deleteDataset(id) {
  return request(`/datasets/${id}`, { method: 'DELETE' });
}

export async function renameDataset(id, 文件名) {
  return request(`/datasets/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ 文件名 }),
  });
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
// 分析直播：SSE 流式获取 Agent 实时决策事件（fetch + ReadableStream 解析）
// 入参：payload（分析请求体）；options.onEvent(ev)：每个 SSE 事件回调，返回 'stop' 中断消费；options.signal：AbortController
// 业务定位：Analysis.jsx 调用本函数，拿到 step/done/error 三类事件驱动决策流 UI
export async function generateReportStream(payload, { onEvent, signal } = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  // 【关键行】fetch 发起 POST 请求，Accept: text/event-stream 告诉后端走 SSE 长连接。
  // 为什么：普通 REST 接口是请求-响应一次返回，Agent 分析可能耗时数分钟，
  //   用 SSE 让后端逐步推送每一步的决策结果，前端实时渲染"决策流"，
  //   用户不用盯着空白页等几分钟。
  // 删除后果：后端仍会生成报表，但前端只有最后结果，中间过程是空白等待，
  //   体验退化成"黑盒等结果"，用户不知道 Agent 在干什么。
  // 替代方案：WebSocket（全双工但更重，需要服务端升级协议）；轮询（高频
  //   request 消耗带宽且延迟大）；SSE 单向流最契合"服务端推送、客户端消费"场景。
  const res = await fetch(`${BASE}/reports/generate-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders, ...llmHeaders },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    if (res.status === 401) handleAuthExpired('/reports/generate-stream');
    throw await parseError(res);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = ''; // 帧缓冲：SSE 帧以双换行 \n\n 结束，需要攒够再解析，避免截断
  // B20 修复：SSE 总超时兜底 —— 后端挂起时不再"分析中..."永久等待
  // 3 分钟超时足够覆盖绝大多数分析任务；超时后 cancel reader 触发 onEvent 错误事件
  const SSE_TIMEOUT_MS = 180000;
  const sseTimer = setTimeout(async () => {
    try { await reader.cancel(); } catch { /* ignore */ }
    if (onEvent) onEvent({ type: 'error', message: '分析超时，请稍后重试' });
  }, SSE_TIMEOUT_MS);
  try {
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break; // 服务端关闭连接，所有数据已推送完毕
    buf += decoder.decode(value, { stream: true }); // stream: true 允许分段解码多字节字符（中文）
    let idx;
    // 【关键行】按 SSE 协议用双换行 \n\n 切分完整帧（\n\n 之前是一个事件的完整载荷）。
    // 为什么：网络包是分块到达的，一帧可能被拆成多次 read；也可能一次 read 含多帧，
    //   所以先攒进 buf 再按分隔符循环切帧，保证每次切出来的 chunk 都是完整事件。
    // 删除后果：一次收到多帧时只解析第一帧，后续事件全部丢失，决策流"卡住不动"。
    // 替代方案：用 EventSource 原生对象（自动处理帧协议），但它只支持 GET、无法
    //   携带自定义请求头与 body；fetch 流式解析灵活度更高，代价是自己实现帧切分。
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      // 一帧内可能有多行：只认 data: 前缀的行（SSE 标准字段），其余忽略
      for (const raw of chunk.split('\n')) {
        if (raw.startsWith('data: ')) {
          try {
            // 【关键行】剥掉 "data: " 前缀后 JSON.parse，还原事件对象 {type, data}。
            // 为什么：SSE 传输层是文本协议，结构化信息必须序列化成 JSON；
            //   解析成功才交给 onEvent，畸形帧直接跳过不让它弄崩整个分析流程。
            // 删除后果：前端拿不到 step/done/error 事件，决策流永远停在"唤醒中"。
            // 替代方案：不用 JSON 用自定义分隔符协议（解析更脆弱），JSON 是标准做法。
            const ev = JSON.parse(raw.slice(6));
            // onEvent 返回 'stop'（done/error 事件）时主动取消读取，提前结束流
            if (onEvent && onEvent(ev) === 'stop') {
              await reader.cancel();
              return;
            }
          } catch { /* 忽略畸形帧 */ }
        }
      }
    }
  }
  } finally {
    clearTimeout(sseTimer); // B20：正常结束/出错/超时均清除定时器，防止悬挂
  }
}

// ---- 报表模板（阶段 30：分析配置收藏 + 一键复用）----

export async function listTemplates() {
  return request('/templates');
}

export async function saveTemplate(name, payload) {
  return request('/templates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 名称: name, payload }),
  });
}

export async function deleteTemplate(templateId) {
  return request(`/templates/${templateId}`, { method: 'DELETE' });
}

// 立即用模板配置生成报表（返回 ReportGenerateResponse，前端跳转到新报表）
export async function runTemplate(templateId) {
  return request(`/templates/${templateId}/run`, { method: 'POST' });
}

// ---- 定时任务（阶段 30：模板 + cron 自动生成）----

export async function listSchedules() {
  return request('/schedules');
}

export async function createSchedule(templateId, cron) {
  return request('/schedules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 模板ID: templateId, cron }),
  });
}

export async function deleteSchedule(jobId) {
  return request(`/schedules/${jobId}`, { method: 'DELETE' });
}

// ---- 报表历史（阶段 6：后端持久化）----

export async function listReports(limit = 50, offset = 0, { favorites = 0, q = '', chart_type = '' } = {}) {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset), favorites: String(favorites) });
  if (q) p.set('q', q);
  if (chart_type) p.set('chart_type', chart_type);
  return request(`/reports/?${p.toString()}`);
}

export async function getReport(reportId) {
  return request(`/reports/${reportId}`);
}

// 导出报表（带 token 下载，返回 { blob, filename }）
export async function exportReport(reportId, format) {
  const token = localStorage.getItem('access_token') || '';
  const res = await fetch(`/reports/${reportId}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401) handleAuthExpired(`/reports/${reportId}/export`); // 批次3：走全局登出
    const err = new Error(`导出失败（HTTP ${res.status}）`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  // 从 Content-Disposition 解析文件名（UTF-8 中文走 RFC 5987 编码）
  return {
    blob,
    filename: parseContentDispositionFilename(res.headers.get('Content-Disposition'), `report.${format}`),
  };
}

// 阶段 30：完整 PDF 报告导出（图表 PNG + 结论 + 数据表 + Trace）
// 前端把 ECharts 渲染的图表 base64 dataURL 传上来，后端 reportlab 排版成单文件 PDF
export async function exportFullReport(reportId, chartPng = '') {
  const token = localStorage.getItem('access_token') || '';
  const res = await fetch(`/reports/${reportId}/export-report`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ chart_png: chartPng }),
  });
  if (!res.ok) {
    if (res.status === 401) handleAuthExpired(`/reports/${reportId}/export-report`);
    const err = new Error(`导出失败（HTTP ${res.status}）`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  return {
    blob,
    filename: parseContentDispositionFilename(res.headers.get('Content-Disposition'), 'report.pdf'),
  };
}

export async function deleteReport(reportId) {
  return request(`/reports/${reportId}`, { method: 'DELETE' });
}

// ---- 报表分享（批次 6：带权限的只读链接；批次 C3：可选访问密码）----

export async function createShare(reportId, hours = 24, password = '', collaborators = '') {
  const q = new URLSearchParams({ 有效小时数: String(hours) });
  if (password) q.set('密码', password);
  if (collaborators) q.set('协作者', collaborators);
  return request(`/reports/${reportId}/share?${q.toString()}`, { method: 'POST' });
}

// 阶段 31：收藏切换（返回 { is_favorited }）
export async function toggleFavorite(reportId) {
  return request(`/reports/${reportId}/favorite`, { method: 'PUT' });
}

export async function listShares(reportId) {
  return request(`/reports/${reportId}/shares`);
}

export async function revokeShare(reportId, shareId) {
  return request(`/reports/${reportId}/share/${shareId}`, { method: 'DELETE' });
}

// 公开只读访问（无 token；可选密码）
export async function getSharedReport(shareId, password = '') {
  const q = password ? `?password=${encodeURIComponent(password)}` : '';
  const res = await fetch(`/share-data/${shareId}${q}`);
  if (!res.ok) {
    const err = new Error(
      res.status === 404 ? '分享链接不存在或已过期'
        : res.status === 401 ? '需要访问密码'
          : `访问失败（HTTP ${res.status}）`,
    );
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// 分析历史重放：用原报表参数重新生成（返回新报表）
export async function replayReport(reportId) {
  return request(`/reports/${reportId}/replay`, { method: 'POST' });
}

// ---- 图表看板（批次 4：多报表并排对比）----

export async function listDashboards() {
  return request('/dashboards/');
}

export async function getDashboard(dashboardId) {
  return request(`/dashboards/${dashboardId}`);
}

export async function createDashboard(name, reportIds) {
  return request('/dashboards/', {
    method: 'POST',
    body: JSON.stringify({ 名称: name, 报表ID列表: reportIds }),
  });
}

export async function updateDashboard(dashboardId, name, reportIds) {
  return request(`/dashboards/${dashboardId}`, {
    method: 'PUT',
    body: JSON.stringify({ 名称: name, 报表ID列表: reportIds }),
  });
}

export async function deleteDashboard(dashboardId) {
  return request(`/dashboards/${dashboardId}`, { method: 'DELETE' });
}

// ---- 管理后台（管理员专用）----

export async function fetchStatistics() {
  return request('/admin/statistics');
}

export async function fetchAdminUsers() {
  return request('/admin/users');
}

export async function healthCheck() {
  return request('/health');
}

// C 修复：提交用户反馈（后端 /feedback 已落库，补齐前端入口）
export async function submitFeedback({ taskId = '', score, correction = '', syncKb = false } = {}) {
  return request('/feedback', {
    method: 'POST',
    body: JSON.stringify({ 任务ID: taskId, 评分: score, 纠错内容: correction, 同步知识库: syncKb }),
  });
}

// D 合规：导出我的全部数据（JSON 下载）
export async function exportUserData() {
  const token = localStorage.getItem('access_token') || '';
  const res = await fetch('/auth/export', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const err = new Error(`导出失败（HTTP ${res.status}）`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  return { blob, filename: parseContentDispositionFilename(res.headers.get('Content-Disposition'), '我的数据.json') };
}

// D 合规：注销账号（验证密码，删除全部数据）
export async function deleteAccount(password) {
  return request('/auth/delete-account', {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
}
