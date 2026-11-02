// 阶段八十九 · B6：看板联动/下钻 的纯逻辑层（无 DOM，可直接单测）。
//
// 做了什么：
// - 取点击维度(图表配置, params)：把 ECharts click 的 params 翻译成 {维度, 值}，
//   供 Dashboard 做「点图 → 联动筛选 / 下钻」。
// - 按条件过滤数据(数据, 条件)：按一组 {维度, 值} 逐条 AND 过滤行。
// - 取下一维度(图表配置, 条件)：从数据行里找第一个「未被指标/已下钻字段占用、且有两个以上不同值」
//   的分类列，作为下钻后的新 X 轴（没有就返回 null = 已到底）。
// - 应用下钻(图表配置, 条件)：过滤数据 + 若有下一维度则把 X 轴切过去，返回新配置（不改原对象）。
//
// 为什么单独成层：下钻的「点哪个维度、切到哪个维度、返回后还原」是全套最容易被手点改乱的状态机，
// 抽成纯函数后 vitest 不渲染图表也能锁住行为；Dashboard 只负责把 params 喂进来、把新配置喂回图表。

/** ECharts click params → {维度, 值}。X轴 缺失时取数据第一列；无名/空名视为未点中。 */
export function 取点击维度(图表配置, params) {
  const cfg = 图表配置 || {};
  const 数据 = Array.isArray(cfg.数据) ? cfg.数据 : [];
  const 维度 = cfg.X轴 || (数据[0] ? Object.keys(数据[0])[0] : '');
  const 值 = params?.name;
  if (!维度 || 值 == null || 值 === '') return null;
  return { 维度, 值: String(值) };
}

/** 按 {维度, 值} 条件逐条 AND 过滤。条件为空 = 原样返回。 */
export function 按条件过滤数据(数据, 条件) {
  const 列表 = (条件 || []).filter(c => c && c.维度 && c.值 != null);
  if (列表.length === 0) return (数据 || []).slice();
  return (数据 || []).filter(row => 列表.every(c => String(row?.[c.维度] ?? '') === c.值));
}

/** 找下一个可下钻的分类维度：数据第一列满足「非指标、非已下钻、取值 ≥2 种」。 */
export function 取下一维度(图表配置, 条件) {
  const cfg = 图表配置 || {};
  const 数据 = Array.isArray(cfg.数据) ? cfg.数据 : [];
  if (数据.length === 0) return null;
  const 已排除 = new Set([
    ...(cfg.Y轴 || []), cfg.值, cfg.X轴,
    ...(条件 || []).map(c => c.维度),
  ]);
  for (const k of Object.keys(数据[0])) {
    if (已排除.has(k)) continue;
    const 值集 = new Set(数据.map(r => String(r?.[k] ?? '')));
    if (值集.size > 1) return k;
  }
  return null;
}

/** 应用下钻：过滤数据，若存在下一维度则切换 X 轴。返回新配置（不改原对象）。 */
export function 应用下钻(图表配置, 条件) {
  const cfg = 图表配置 || {};
  const 数据 = 按条件过滤数据(cfg.数据, 条件);
  const 下一 = 取下一维度(cfg, 条件);
  const 新X轴 = 下一 || cfg.X轴 || '';
  if (新X轴 === cfg.X轴) return { ...cfg, 数据 };
  return { ...cfg, 数据, X轴: 新X轴 };
}
