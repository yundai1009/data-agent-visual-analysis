/**
 * 阶段 六十：图表视觉常量的单一来源。
 *
 * 动机：看板"关系视图"的血缘节点必须和报表图共用同一套藏青色板与字体，
 * 否则同一页出现两种蓝，看上去像两个半成品拼起来的。
 * 这些常量原来内联在 EChartsChart.jsx，抽出来后由 EChartsChart 与 LineageGraph 共用。
 */

/** 藏青系协调色板（阶段 13 重设计：与 UI 主色统一） */
export const COLORS = ['#0f4c81', '#3d7bb8', '#5b8cb8', '#8aa9c4', '#b45309', '#0f766e', '#64748b', '#334155'];

export const CHART_TEXT_STYLE = {
  fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif',
  fontSize: 12,
  color: '#475569',
};

export const CHART_TOOLTIP = {
  backgroundColor: '#ffffff',
  borderColor: '#e2e8f0',
  borderWidth: 1,
  textStyle: { fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif', fontSize: 12, color: '#1e293b' },
  extraCssText: 'box-shadow: 0 8px 16px -8px rgba(15,76,129,.15); border-radius: 8px;',
};

/**
 * HTML 转义（P0 加固，审计实测 P0-6）。
 * echarts tooltip 内容按 HTML 渲染，自定义 formatter 返回值必须自行转义，
 * 否则上传数据里的 <img onerror=...> 可触发存储型 XSS。字段名/文件名都来自用户上传数据，必转。
 */
export function 转义HTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
