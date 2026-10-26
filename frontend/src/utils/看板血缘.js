/**
 * 阶段 六十 · 看板血缘关系视图：纯函数层。
 *
 * 做了什么：把三个既有接口的响应拼成一张有向图
 *          数据集(左) → 报表(中) → 字段(右)，供 ECharts graph 渲染。
 * 为什么这样设计：
 *   - 看板只显示"这几张图并排"，看不出这些图共用哪份数据、哪几列；
 *     血缘图回答"这个数字是从哪来、还被谁用了"，是分析的溯源需求；
 *   - 字段层规则借鉴开源项目 neural-creator-dashboard 的图谱思路
 *     （PolyForm Noncommercial 许可，只借规则不抄代码）：
 *     "同一概念被 ≥2 条内容提及才成为概念节点"
 *     → 等价为 "同一字段被 ≥2 张报表引用才成为字段节点"，即高价值字段。
 *
 * 纯函数、无副作用、数据缺失一律降级不抛异常（可直接单测）。
 */

import { COLORS, CHART_TOOLTIP, 转义HTML } from './图表主题';

const 未知数据集ID = '__未知数据集__';
const 复用阈值 = 2;          // 被 ≥2 张报表引用才算高价值字段

/**
 * 角色占位名：聚合类图把原始列重塑掉之后，`名称`/`值` 里写的是角色名而不是数据列名。
 * 证据 `后端_核心/report_generator.py:977-997`：
 *   wordcloud/boxplot/waterfall/candlestick 写 `名称:"name"`、`值:"value"`；
 *   sunburst 写 `名称:"名称"`、`值:"value"`；sankey 写 `名称:"源"`、`值:"value"`。
 * 这些字面量恰好也是 `数据[0]` 的键（`:489`、`:531-532`、`:544`、`:557`、`:586-588`），
 * 所以"列名白名单"对它们完全失效——必须按类型显式黑名单挡。
 */
const 角色占位名 = new Set(['name', 'value', '名称', '值', '源', '目标', '层级']);
const 角色占位类型 = new Set(['wordcloud', 'sankey', 'boxplot', 'waterfall', 'sunburst', 'candlestick']);

/** 抽字段并记角色；两道校验：黑名单挡角色占位名，白名单挡数据里不存在的列名（数据行被重塑时两道都按形状让路） */
export function 提取图表字段(图表配置) {
  const cfg = 图表配置 || {};
  const 类型 = typeof cfg.类型 === 'string' ? cfg.类型.trim().toLowerCase() : '';
  const 数据键 = new Set(
    Array.isArray(cfg.数据) && cfg.数据[0] && typeof cfg.数据[0] === 'object'
      // 键也 trim：Excel 导出表头带首尾空格很常见，与下面候选的 trim 对齐才匹配得上
      ? Object.keys(cfg.数据[0]).map((k) => String(k).trim())
      : [],
  );
  // 数据行密钥本身就是角色名 → 这张图已把原始列重塑掉，白名单里没有真实列名可比，
  // 此时【跳过】白名单，而不是拿角色名去卡真实字段（否则 X轴/颜色 这类用户真实选择会被整片清空）
  const 数据键是角色名 = 数据键.size > 0
    && [...数据键].every((k) => 角色占位名.has(String(k).trim().toLowerCase()));
  // 已知取舍：混合形状（数据行既有角色名又有真实列）会让 every 判 false、白名单恢复生效，
  // 角色名又会被当成字段留下。事实是配置与数据行**可能不同源**：`report_generator.py:962-967`
  // 的配置取自请求参数，wordcloud/waterfall 不校验 Y轴/颜色，`reports.py:1084` 的历史重放
  // 还会把旧配置打到新数据集上。所以本函数只保证"不把角色占位名当字段"，
  // 无法保证列名与数据集真实列一致——列名真实性由后端校验负责，这里不做防御。
  // 老报表没有数据行时同样跳过白名单：宁可多列，也不要凭空捏造
  const 需校验 = 数据键.size > 0 && !数据键是角色名 && !角色占位类型.has(类型);
  // 黑名单闸门：类型是聚合类【或】数据行形状本身就是角色名（脏数据/旧配置）
  const 挡角色名 = 角色占位类型.has(类型) || 数据键是角色名;

  const 角色表 = new Map();
  const 记 = (候选, 角色) => {
    if (typeof 候选 !== 'string') return;
    const 名 = 候选.trim();
    if (!名) return;
    // 第一道（黑名单）：字段名本身是角色占位名 → 丢弃（toLowerCase 兼容 Name/Value 这类大写写法）
    if (挡角色名 && 角色占位名.has(名.toLowerCase())) return;
    // 第二道（白名单）：配置里写了数据里没有的列名（脏配置 / 列被改过）→ 丢弃；
    // 数据行是角色名形状或类型是聚合类时这道失效（见 上面的 需校验）
    if (需校验 && !数据键.has(名)) return;
    if (!角色表.has(名)) 角色表.set(名, new Set());
    角色表.get(名).add(角色);
  };

  记(cfg.X轴, 'X轴');
  (Array.isArray(cfg.Y轴) ? cfg.Y轴 : []).forEach((f) => 记(f, 'Y轴'));
  记(cfg.颜色 ?? cfg.分组字段, '分组');
  记(cfg.名称, '名称');
  记(cfg.值, '数值');

  return [...角色表.entries()].map(([字段名, 角色集]) => ({ 字段名, 角色: [...角色集] }));
}

/** 结论摘要：折空白 + 截断（抽屉里一行放得下） */
function 结论摘要(文本, 上限 = 80) {
  const s = String(文本 ?? '').replace(/\s+/g, ' ').trim();
  return s.length > 上限 ? `${s.slice(0, 上限)}…` : s;
}

/**
 * 构建血缘图。
 * @param {Array} 入参.报表列表   getDashboard(id).报表列表（不含数据集ID）
 * @param {Map}   入参.报表索引   报表ID → listReports 列表项（含数据集ID）
 * @param {Map}   入参.数据集索引 数据集ID → listDatasets 列表项（含文件名/行数/列数）
 * @param {Map}   入参.报表源列表索引 报表ID → 数据集ID列表（仅对比报表有；单报表回落到 [数据集ID]）
 * @returns {{节点: Array, 连线: Array, 节点索引: Object, 统计: Object}}
 */
export function 构建血缘图({
  报表列表 = [], 报表索引 = new Map(), 数据集索引 = new Map(), 报表源列表索引 = new Map(),
} = {}) {
  const 节点 = [];
  const 连线 = [];
  const 数据集节点表 = new Map();   // 数据集ID → 节点
  const 报表节点表 = new Map();     // 报表ID → 节点
  const 字段累计 = new Map();       // `数据集ID::字段名` → { 字段名, 数据集ID, 角色:Set, 报表:[] }

  (Array.isArray(报表列表) ? 报表列表 : []).filter((项, i, 全体) => {
    // 入口按 报表ID 去重（保留首次出现）：后端 listReports 只限长不去重（api/contracts.py:171），
    // 重复项若照单全收，度累加/明细/归属连线/字段复用计数都会翻倍，
    // 只被 1 张报表引用的字段也能凑到阈值 2，凭空造出假「高价值字段」。
    const id = 项?.报表ID;
    return Boolean(id) && 全体.findIndex((x) => x?.报表ID === id) === i;
  }).forEach((项) => {
    const 报表ID = 项?.报表ID;
    if (!报表ID) return;
    const 元 = 报表索引.get(报表ID) || {};
    const 首数据集ID = 元.数据集ID || 未知数据集ID;   // listReports 截断/旧报表 → 未知数据集
    // 对比报表在 listReports 只回首来源；看板详情的 报表.数据集ID列表 才是完整来源。
    // 取不到（单报表/旧报表）就回落成 [首数据集ID]，行为和改造前完全一致。
    const 源列表 = (报表源列表索引.get(报表ID) && 报表源列表索引.get(报表ID).length)
      ? 报表源列表索引.get(报表ID)
      : [首数据集ID];
    const 标题 = 项.标题 || 元.标题 || '未命名报表';
    const 图表类型 = 项.图表类型 || 元.图表类型 || '';

    // 层 2：报表节点（每张报表只建一个，但「归到哪些数据集」按源列表展开）
    const 字段明细 = 提取图表字段(项?.报表?.图表配置);
    const 报表节点 = {
      节点ID: `rp:${报表ID}`,
      名称: 标题,
      类型: '报表',
      层: 1,
      报表ID,
      数据集ID: 首数据集ID,
      图表类型,
      度: 字段明细.length + 源列表.length,
      明细: {
        标题,
        图表类型,
        创建时间: 项.创建时间 || 元.创建时间 || '',
        数据集ID: 首数据集ID,
        数据集名: 首数据集ID === 未知数据集ID
          ? '未知数据集'
          : ((数据集索引.get(首数据集ID) || {}).文件名 || 首数据集ID),
        结论: 结论摘要(项?.报表?.结论),
        字段: 字段明细,
      },
    };
    if (!报表节点表.has(报表ID)) {
      报表节点表.set(报表ID, 报表节点);
      节点.push(报表节点);
    }

    // 层 1：数据集节点（同一数据集只建一次）+ 报表→每个来源数据集的归属连线
    源列表.forEach((数据集ID) => {
      if (!数据集节点表.has(数据集ID)) {
        const ds = 数据集索引.get(数据集ID) || {};
        const 新数据集节点 = {
          节点ID: `ds:${数据集ID}`,
          名称: 数据集ID === 未知数据集ID ? '未知数据集' : (ds.文件名 || 数据集ID),
          类型: '数据集',
          层: 0,
          数据集ID,
          度: 0,
          明细: {
            文件名: ds.文件名 || '',
            行数: ds.行数 ?? null,
            列数: ds.列数 ?? null,
            来源数据集ID: ds.来源数据集ID || '',
            本看板报表: [],
            其他报表: [],   // 同数据集但没进本看板的历史报表（反链发现）
          },
        };
        数据集节点表.set(数据集ID, 新数据集节点);
        节点.push(新数据集节点);
      }
      const 数据集节点 = 数据集节点表.get(数据集ID);
      数据集节点.明细.本看板报表.push({ 报表ID, 标题, 图表类型 });
      数据集节点.度 += 1;
      连线.push({
        连线ID: `ds:${数据集ID}->rp:${报表ID}`,
        起点: 数据集节点.节点ID,
        终点: 报表节点.节点ID,
        类型: '归属',
      });
    });

    // 字段累计：按 数据集::字段 归并（同名不同数据集不合并，否则会算出假的复用度）
    // 对比报表跨多个源数据集时，每个源都累计一遍——否则「甲.销售额」「乙.销售额」会并成一条假复用
    源列表.forEach((数据集ID) => {
      字段明细.forEach(({ 字段名, 角色 }) => {
        const 键 = `${数据集ID}::${字段名}`;
        if (!字段累计.has(键)) 字段累计.set(键, { 字段名, 数据集ID, 角色: new Set(), 报表: [] });
        const 累计 = 字段累计.get(键);
        角色.forEach((r) => 累计.角色.add(r));
        累计.报表.push({ 报表ID, 标题, 图表类型 });
      });
    });
  });

  // 层 3：只收被 ≥阈值 张报表引用的字段（高价值字段）；其余字段留在报表节点明细里
  const 高价值字段 = [];
  [...字段累计.entries()]
    .sort((a, b) => b[1].报表.length - a[1].报表.length || a[1].字段名.localeCompare(b[1].字段名, 'zh-CN'))
    .forEach(([键, 累计]) => {
      if (累计.报表.length < 复用阈值) return;
      const 数据集节点 = 数据集节点表.get(累计.数据集ID);
      const 字段节点 = {
        节点ID: `fd:${键}`,
        名称: 累计.字段名,
        类型: '字段',
        层: 2,
        字段名: 累计.字段名,
        数据集ID: 累计.数据集ID,
        度: 累计.报表.length,
        明细: {
          字段名: 累计.字段名,
          数据集名: 数据集节点?.名称 || '',
          角色: [...累计.角色],
          报表: 累计.报表,
        },
      };
      节点.push(字段节点);
      高价值字段.push(字段节点);
      累计.报表.forEach((r) => {
        连线.push({
          连线ID: `rp:${r.报表ID}->fd:${键}`,
          起点: `rp:${r.报表ID}`,
          终点: 字段节点.节点ID,
          类型: '引用',
        });
      });
    });

  // 反链：同数据集、但没进本看板的历史报表
  数据集节点表.forEach((数据集节点) => {
    const 已有 = new Set(数据集节点.明细.本看板报表.map((r) => r.报表ID));
    数据集节点.明细.其他报表 = [...报表索引.values()]
      .filter((r) => r?.数据集ID === 数据集节点.数据集ID && !已有.has(r.报表ID))
      .map((r) => ({ 报表ID: r.报表ID, 标题: r.标题, 图表类型: r.图表类型 }));
  });

  return {
    节点,
    连线,
    节点索引: Object.fromEntries(节点.map((n) => [n.节点ID, n])),
    统计: {
      数据集数: 数据集节点表.size,
      报表数: 报表节点表.size,
      字段总数: 字段累计.size,
      高价值字段: 高价值字段.map((n) => ({
        节点ID: n.节点ID,
        字段名: n.字段名,
        数据集名: n.明细.数据集名,
        报表数: n.度,
        角色: n.明细.角色,
        报表: n.明细.报表,
      })),
    },
  };
}

// ---- option 生成（也是纯函数，单测直接断言结构）----

const 层X = { 0: 16, 1: 50, 2: 84 };   // 归一化 0-100 坐标，ECharts graph layout:'none' 会自适应视口
const 类别索引 = { 数据集: 0, 报表: 1, 字段: 2 };
const 基础底色 = { 数据集: COLORS[0], 报表: COLORS[1], 字段: COLORS[5] };

/**
 * 生成关系图 option。
 * @param {Object} 图数据 构建血缘图 的返回值
 * @param {Object} 配置   高亮节点ID（点击后持久高亮自己算，ECharts 的 emphasis.focus 只管 hover）
 */
export function 构建血缘Option(图数据, { 高亮节点ID = '' } = {}) {
  const 节点们 = 图数据?.节点 || [];
  const 连线们 = 图数据?.连线 || [];
  const 索引 = 图数据?.节点索引 || {};

  // 分层铺 y：同层均匀分布，避免节点重叠在同一条线上
  const 分层 = { 0: [], 1: [], 2: [] };
  节点们.forEach((n) => { (分层[n.层] || 分层[1]).push(n); });
  const 坐标 = new Map();
  Object.entries(分层).forEach(([层, 组]) => {
    组.forEach((n, i) => 坐标.set(n.节点ID, { x: 层X[层], y: (100 * (i + 1)) / (组.length + 1) }));
  });

  // 邻接集合：选中节点自身 + 上下游
  const 邻接 = new Set();
  if (高亮节点ID) {
    邻接.add(高亮节点ID);
    连线们.forEach((l) => {
      if (l.起点 === 高亮节点ID) 邻接.add(l.终点);
      if (l.终点 === 高亮节点ID) 邻接.add(l.起点);
    });
  }
  const 淡 = (id) => (高亮节点ID && !邻接.has(id) ? 0.18 : 1);

  return {
    animationDuration: 600,
    legend: {
      data: ['数据集', '报表', '字段（≥2 张报表复用）'],
      top: 0,
      left: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 11, color: '#64748b' },
    },
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'item',
      confine: true,   // 图在页面中间，弹层不越出容器
      formatter: (p) => {
        if (p?.dataType === 'edge') return 转义HTML(p.data?.提示 || '引用');
        const n = p?.data?.节点ID ? 索引[p.data.节点ID] : null;
        if (!n) return 转义HTML(p?.name || '');
        const 行 = [`<b>${转义HTML(n.名称)}</b>`, `类型：${n.类型}`];
        if (n.类型 === '数据集') 行.push(`本看板引用 ${n.度} 张报表`);
        if (n.类型 === '报表') 行.push(`图表：${转义HTML(n.图表类型 || '未知')}`);
        if (n.类型 === '字段') 行.push(`被 ${n.度} 张报表引用`);
        行.push('<span style="color:#94a3b8">单击查看详情</span>');
        return 行.join('<br/>');
      },
    },
    series: [{
      type: 'graph',
      layout: 'none',        // 坐标在上面算好：确定性 → 可单测、截图稳定
      roam: true,            // 滚轮缩放 + 拖拽平移
      draggable: true,
      symbol: 'roundRect',
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 6],
      label: { show: true, position: 'bottom', distance: 4, fontSize: 11, color: '#475569' },
      lineStyle: { color: '#cbd5e1', width: 1.2, curveness: 0.08 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 2.4 } },
      categories: [
        { name: '数据集', itemStyle: { color: 基础底色.数据集 } },
        { name: '报表', itemStyle: { color: 基础底色.报表 } },
        { name: '字段（≥2 张报表复用）', itemStyle: { color: 基础底色.字段 } },
      ],
      data: 节点们.map((n) => {
        const 底色 = n.类型 === '字段' && n.度 >= 3 ? COLORS[4] : 基础底色[n.类型];  // 3 张以上复用 → 琥珀色警示
        const 基数 = n.类型 === '数据集' ? [26, 30] : n.类型 === '报表' ? [22, 26] : [18, 22];
        const 增量 = n.类型 === '字段' ? Math.min(n.度, 5) * 3 : 0;   // 复用度越高字段越大
        return {
          id: n.节点ID,
          节点ID: n.节点ID,
          name: n.名称,
          category: 类别索引[n.类型] ?? 1,
          x: 坐标.get(n.节点ID)?.x ?? 50,
          y: 坐标.get(n.节点ID)?.y ?? 50,
          symbolSize: [基数[0] + 增量, 基数[1] + Math.round(增量 * 0.7)],
          itemStyle: { color: 底色, opacity: 淡(n.节点ID), borderColor: '#ffffff', borderWidth: 1.5 },
          label: { opacity: 淡(n.节点ID) },
        };
      }),
      links: 连线们.map((l) => ({
        source: l.起点,
        target: l.终点,
        提示: l.类型,
        lineStyle: { type: l.类型 === '引用' ? 'dashed' : 'solid', opacity: 淡(l.起点) * 淡(l.终点) },
      })),
    }],
  };
}
