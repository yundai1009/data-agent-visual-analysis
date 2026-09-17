/**
 * api/endpoints.js — 全部业务 API 函数（认证/数据集/报表/分享/看板/管理/反馈/合规）
 *
 * 从 api.js 拆分，职责：所有 REST 业务接口调用。
 * 统一走 api/request.js 的 request()（token 注入 + 超时 + 401 + 错误解析）。
 * 传输层（上传/SSE）在 api/upload.js；本模块只依赖 request。
 */
import { request, getStoredToken } from './request';

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

// 优化⑨：数据集原始数据分页预览

export async function getDatasetRows(id, offset = 0, limit = 20) {
  return request(`/datasets/${id}/rows?offset=${offset}&limit=${limit}`);
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

// 优化③：合并多个数据集为一份（列对齐 + 行追加），返回新数据集

export async function mergeDatasets(ids, 文件名 = '') {
  return request('/datasets/merge', {
    method: 'POST',
    body: JSON.stringify({ 数据集ID列表: ids, 文件名 }),
  });
}

export async function cleanDataset(id, ops) {
  const params = new URLSearchParams();
  if (ops.deduplicate) params.set('deduplicate', 'true');
  if (ops.fill_missing) params.set('fill_missing', 'true');
  if (ops.fill_strategy) params.set('fill_strategy', ops.fill_strategy);
  if (ops.drop_empty_rows) params.set('drop_empty_rows', 'true');
  // 优化②：另存为新数据集（保留原始数据）
  if (ops.新文件名) params.set('新文件名', ops.新文件名);
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
// 【Bug29 修复】模板执行走完整 LLM Agent 链路（多轮推理+工具调用），30s 默认超时
// 很容易被掐断导致"模板执行失败：请求超时"——显式传 180s 超时覆盖。

export async function runTemplate(templateId) {
  return request(`/templates/${templateId}/run`, {
    method: 'POST',
    _customTimeout: 180000, // 3 分钟：与 SSE 分析超时对齐
  });
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

// 优化①：最近失败的定时任务（全局通知条）
// 优化⑧：全局搜索（数据集/报表/模板）

export async function globalSearch(q, options) {
  // 【Bug8 修复】支持 AbortController signal（Sidebar 搜索取消）
  return request(`/search?q=${encodeURIComponent(q)}`, options);
}

export async function fetchFailedSchedules() {
  return request('/schedules/failed');
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
// 优化：并入统一超时保护（fetch 无默认超时，后端挂起时按钮永久 loading）

export async function exportReport(reportId, format) {
  const token = getStoredToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`/reports/${reportId}/export?format=${format}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
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
  } catch (e) {
    if (e?.name === 'AbortError') {
      const err = new Error('导出超时了，请重试');
      err.status = 0;
      throw err;
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// 阶段 30：完整 PDF 报告导出（图表 PNG + 结论 + 数据表 + Trace）
// 前端把 ECharts 渲染的图表 base64 dataURL 传上来，后端 reportlab 排版成单文件 PDF

export async function exportFullReport(reportId, chartPng = '') {
  const token = getStoredToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`/reports/${reportId}/export-report`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ chart_png: chartPng }),
      signal: controller.signal,
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
  } catch (e) {
    if (e?.name === 'AbortError') {
      const err = new Error('导出超时了，请重试');
      err.status = 0;
      throw err;
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
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
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`/share-data/${shareId}`, {
      // M16：密码走请求头 X-Share-Password（此前拼进 URL query，会进浏览器
      // 历史/服务器日志明文泄露）
      headers: password ? { 'X-Share-Password': password } : {},
      signal: controller.signal,
    });
    if (!res.ok) {
      const err = new Error(
        res.status === 404 ? '分享链接不存在或已过期'
          : res.status === 401 ? '需要访问密码'
            : res.status === 429 ? '尝试次数过多，请稍后再试'
              : `访问失败（HTTP ${res.status}）`,
      );
      err.status = res.status;
      throw err;
    }
    return res.json();
  } catch (e) {
    if (e?.name === 'AbortError') {
      const err = new Error('加载超时了，请重试');
      err.status = 0;
      throw err;
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
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

// 优化⑦：看板分享（创建只读分享链接）

export async function shareDashboard(dashboardId, hours = 24, password = '') {
  const q = new URLSearchParams({ 有效小时数: String(hours) });
  if (password) q.set('密码', password);
  return request(`/dashboards/${dashboardId}/share?${q.toString()}`, { method: 'POST' });
}

// ---- 管理后台（管理员专用）----

export async function fetchStatistics() {
  return request('/admin/statistics');
}

export async function fetchAdminUsers() {
  return request('/admin/users');
}

// 优化⑦：管理后台——审计日志 / 平台用量 / 监控指标 / 预测事件导出

export async function fetchAuditLog(limit = 50, offset = 0, userId = '') {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (userId) p.set('user_id', userId);
  return request(`/admin/audit?${p.toString()}`);
}

export async function fetchUsage(days = 7) {
  return request(`/admin/usage?days=${days}`);
}

export async function fetchMetrics() {
  return request('/admin/metrics');
}

export async function exportEvents() {
  return request('/admin/export-events');
}

export async function banUser(userId, reason = '') {
  return request(`/admin/users/${userId}/ban`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function unbanUser(userId) {
  return request(`/admin/users/${userId}/unban`, { method: 'POST' });
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
  const token = getStoredToken();
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

