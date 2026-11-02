// 阶段八十九 · B5：看板导出 PDF/图片 的纯逻辑层（无 DOM 依赖，可直接单测）。
//
// 做了什么：
// - 计算拼接尺寸(尺寸列表, 每行宽)：把每张图按 2 列网格排布，返回画布总宽/总高与每格坐标，
//   供 Dashboard 用 canvas 把各图 dataURL 竖排/网格拼成一张 PNG。
// - 构建打印HTML({看板名, 卡片, 生成时间})：生成一张打印友好页面（标题 + 每张图 + 结论），
//   供 Dashboard 用 window.open + print() 让浏览器/Electron 存成 PDF。
//
// 为什么单独成层：canvas 拼接与 window.open 都得在浏览器里跑，把「布局数学」与「HTML 模板」
// 抽成纯函数后 vitest 不用起 DOM 就能断言，改版式不必手点验证。
//
// 关键约定与坑：
// - 每张图默认宽 640px、高 400px（与 EChartsChart 默认 320 高 + 头部留白对齐）；拼接时不缩放，
//   只在图上留 12px 间隔，保证「导出图片 = 屏上所见」不被二次压缩糊掉。
// - 打印 HTML 内联了白底样式：ECharts getDataURL 已给 #ffffff 背景，浏览器深色打印模式也不会黑底。
// - 卡片里的 dataURL 必须是 PNG base64（ECharts getDataURL 产物），否则 <img> 不显示。

export const 每图宽 = 640;
export const 每图高 = 400;
export const 图间距 = 12;
export const 每行宽 = 2;

/** 计算拼接画布尺寸与每格坐标。
 * @param {Array<{w?:number,h?:number}>} 尺寸列表 每张图的宽高（缺省用 每图宽/每图高）
 * @param {number} [每行=每行宽] 每行放几张
 * @returns {{宽:number,高:number,格:[{x:number,y:number}]}} */
export function 计算拼接尺寸(尺寸列表, 每行 = 每行宽) {
  const 尺寸 = (尺寸列表 || []).map(d => ({
    w: Number(d?.w) || 每图宽,
    h: Number(d?.h) || 每图高,
  }));
  const 行数 = Math.ceil(尺寸.length / 每行) || 1;
  const 列数 = Math.min(尺寸.length, 每行) || 1;
  // 行高按「该行最高的那张」单独算：高低图混排时不给定行塞入多余空白，也不会把矮图压出白边。
  const 行高列表 = [];
  for (let r = 0; r < 行数; r += 1) {
    const 本行 = 尺寸.slice(r * 每行, r * 每行 + 每行);
    行高列表.push(本行.reduce((m, d) => Math.max(m, d.h), 每图高));
  }
  const 宽 = 列数 * 每图宽 + (列数 - 1) * 图间距;
  const 高 = 行高列表.reduce((s, h) => s + h, 0) + (行数 - 1) * 图间距;
  const 格 = 尺寸.map((d, i) => {
    const 行 = Math.floor(i / 每行);
    const 行前高 = 行高列表.slice(0, 行).reduce((s, h) => s + h, 0);
    return { x: (i % 每行) * (每图宽 + 图间距), y: 行前高 + 行 * 图间距 };
  });
  return { 宽, 高, 格 };
}

/** 转义 HTML（<img> 用不上，但标题/结论是用户文本，必须转义防注入）。 */
function 转义(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** 构建打印友好 HTML（供浏览器「打印→另存 PDF」）。
 * @param {{看板名?:string, 卡片?:Array<{标题?:string, 类型?:string, 结论?:string, dataURL?:string}>, 生成时间?:string}} 入参
 * @returns {string} 完整 HTML 文档 */
export function 构建打印HTML({ 看板名, 卡片, 生成时间 } = {}) {
  const 名 = 转义(看板名 || '看板');
  const 时间 = 转义(生成时间 || new Date().toLocaleString('zh-CN'));
  const 卡片HTML = (卡片 || [])
    .filter(c => c && c.dataURL)
    .map(c => `
      <section class="card">
        <header><h2>${转义(c.标题 || '未命名图表')}</h2><span class="tag">${转义(c.类型 || '')}</span></header>
        <img src="${c.dataURL}" alt="${转义(c.标题 || '')}">
        ${c.结论 ? `<p class="conclusion">结论：${转义(c.结论)}</p>` : ''}
      </section>`)
    .join('');
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>${名} · 看板导出</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: #fff; color: #1f2937;
    font: 14px/1.6 "Microsoft YaHei UI", "Microsoft YaHei", system-ui, sans-serif; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .meta { color: #6b7280; font-size: 12px; margin: 0 0 20px; }
  .card { border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; margin-bottom: 16px;
    break-inside: avoid; page-break-inside: avoid; }
  .card header { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: #f9fafb;
    border-bottom: 1px solid #e5e7eb; }
  .card h2 { font-size: 14px; margin: 0; flex: 1; }
  .tag { font-size: 11px; color: #2563eb; background: #eff6ff; padding: 1px 8px; border-radius: 6px; }
  .card img { display: block; width: 100%; height: auto; background: #fff; }
  .conclusion { margin: 0; padding: 10px 14px; font-size: 12px; color: #4b5563;
    border-top: 1px dashed #e5e7eb; }
  @media print { body { padding: 0; } }
</style></head>
<body>
  <h1>${名}</h1>
  <p class="meta">导出时间：${时间} · 共 ${(卡片 || []).filter(c => c && c.dataURL).length} 张图表</p>
  ${卡片HTML}
</body></html>`;
}
