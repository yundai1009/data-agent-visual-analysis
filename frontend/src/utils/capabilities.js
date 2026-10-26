/* =============================================================================
 * 文件：frontend/src/utils/capabilities.js —— 产品模式（基础版 / 专业版）能力表
 * 层级：纯逻辑，不 import React、不碰 DOM 之外的东西（便于单测）
 * 背景（阶段七十四 · C）：
 *   用户反馈「产品偏离初始定位——目标用户是 0 基础、没有数据分析基础的普通人，
 *   现在整体复杂度偏高」，诉求是拆【基础版 / 专业版】做能力隔离。
 *   我没有拆成两个仓库/两份前端：双份维护、双份 bug、修一处要修两遍，
 *   对单人项目来说这正是会把进度拖死的做法。做法改成：
 *     **一个构建 + 一份能力表 + 一个模式开关**（feature gating）。
 * 取舍：
 *   - 能力表是唯一真相源，页面只问「我有这个能力吗」，不各自判断模式；
 *   - 默认给「基础版」：新用户第一眼只看到 上传 → 说一句 → 看报表 三步，
 *     这正是产品定位（面向 0 基础的人）。专业版是主动选择、或 ?mode=pro 打开。
 *     改这一行即可整体翻转默认界面（相关断言见 capabilities.test.js / Account.test.jsx）。
 * ============================================================================= */

/** 两种模式。值写进 localStorage，稳定字符串不要随意改。 */
export const 模式 = {
  基础版: 'basic',
  专业版: 'pro',
};

/** 默认模式：基础版 = 新用户第一眼就是「上传 → 分析 → 看报表」三步。
 *  专业能力不删，收在账号设置里自己开；?mode=pro 也能直接进。 */
export const 默认模式 = 模式.基础版;

const 存储键 = 'daa_mode';

/**
 * 能力表：能力名 → { basic: 值, pro: 值 }
 * 用布尔值表示「这个模式里显不显示这个功能」；侧栏项用字符串数组（能进哪些路由）。
 */
export const 能力表 = {
  侧栏项: {
    basic: ['/data', '/analysis', '/compare', '/report', '/dashboard', '/account'],
    pro: ['/data', '/analysis', '/compare', '/report', '/dashboard', '/account'],
  },
  模型选择: { basic: false, pro: true },
  智能体模式: { basic: false, pro: true },
  模板: { basic: false, pro: true },
  定时任务: { basic: false, pro: true },
  高级清洗: { basic: false, pro: true },
  血缘图: { basic: false, pro: true },
  // 对比分析在基础版**保留侧栏入口**（阶段七十六按用户要求加回）：
  // 早先的取舍是"基础版收起术语入口，只走数据管理页勾 ≥2 份 → 对比这几份"，
  // 但用户实测后明确要求加回——能力可以渐进披露，入口不能藏。
  // 两条路并存：侧栏直接进 / 数据管理页上下文进，用户从哪条进都能到。
  对比分析入口: { basic: true, pro: true },
};

/**
 * 读当前模式。
 * 优先级：URL 参数 ?mode=basic|pro > localStorage > 默认模式。
 * URL 参数存在的意义是分享出去的链接能带上场景（比如给新手的总览链接）。
 */
export function 取模式() {
  try {
    const 参 = new URLSearchParams(window.location.search).get('mode');
    if (参 === 模式.基础版 || 参 === 模式.专业版) return 参;
  } catch { /* window 不存在（极端环境）时走下面 */ }
  try {
    const 存 = localStorage.getItem(存储键);
    if (存 === 模式.基础版 || 存 === 模式.专业版) return 存;
  } catch { /* 隐私模式禁 localStorage → 回落默认 */ }
  return 默认模式;
}

/** 写当前模式；非法的值直接忽略（不写脏数据）。 */
export function 设模式(值) {
  if (值 !== 模式.基础版 && 值 !== 模式.专业版) return false;
  try {
    localStorage.setItem(存储键, 值);
    return true;
  } catch {
    return false;
  }
}

/**
 * 问「当前模式有这个能力吗」。
 * @param {string} 能力名 能力表里的键
 * @param {string} [模式值] 显式指定模式（默认取 取模式()），单测用
 */
export function 有能力(能力名, 模式值) {
  const 当前 = 模式值 || 取模式();
  const 条目 = 能力表[能力名];
  if (!条目) return false; // 能力表里没写的能力一律不给，避免"以为有其实没有"
  return Boolean(条目[当前]);
}

/** 按能力表过滤侧栏项；不传模式值时用当前模式。 */
export function 过滤侧栏项(全部项, 模式值) {
  const 当前 = 模式值 || 取模式();
  const 允许 = 能力表.侧栏项[当前] || 能力表.侧栏项[默认模式];
  return 全部项.filter((项) => 允许.includes(项.to));
}
