// 阶段 六十 · 单图表渲染组件：把后端下发的「图表配置」翻译成 ECharts option 并渲染。
//
// 做了什么：
// 1. 默认导出 <EChartsChart chartType chartConfig height>：懒加载 echarts（含 echarts-wordcloud 词云插件），
//    就绪后建实例 → setOption(notMerge) → resize，卸载时 dispose；工具条提供「下载图表 PNG」与「复制图片到剪贴板」。
// 2. 具名导出 buildOption(chartType, config)：纯函数，负责 18 种图表类型 → option 的翻译，供单测直接断言。
// 3. 色板 / 文本样式 / tooltip 主题 / HTML 转义统一从 ../utils/图表主题.js 取，本文件不再持有副本。
//
// 为什么这么做：
// - echarts 用动态 import 而非首屏静态引入：库 + 词云插件接近 1MB，进主 bundle 会拖慢首屏；代价是首帧要显示占位，
//   所以用 ready 状态把「加载中」和「已可渲染」隔开。
// - setOption 必须 notMerge：切换图表类型时配置变的是 series / 坐标轴，合并模式会把上一次的系列残留下来，
//   表现为「从折线图切到饼图后还挂着几条线」。
// - buildOption 单独导出而不埋在组件里：option 是纯数据，不用起浏览器就能断言，图表类型越多越省事。
//
// 关键约定与坑：
// - chartType 收的是英文短名（bar / line / pie / wordcloud / boxplot…），中文名（柱状图 / 词云图）是给人看的，
//   中英映射表在后端_核心/report_generator.py:52-72，前端不做转换。
// - chartConfig.数据 的键名由后端约定：X轴、Y轴[]、颜色/分组字段、名称、值（取值逻辑在本文件 :185-199 附近）。
// - 渲染异常不让整页崩：catch 之后把错误画成图内标题（#ef4444），空白图也比整页报错更好定位问题。
// - 阶段 六十 起主题常量搬到 utils/图表主题.js（血缘图与它共用单一来源），改色板只改那一个文件。

import { useRef, useState, useEffect } from 'react';
import { Download, Copy } from 'lucide-react';
// 阶段 六十：色板/主题/转义抽到 utils/图表主题.js，与 LineageGraph 共用单一来源
import { COLORS, CHART_TEXT_STYLE, CHART_TOOLTIP, 转义HTML as escapeHtml } from '../utils/图表主题';

export default function EChartsChart({ chartType, chartConfig, height = 320 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const echartsRef = useRef(null);
  const [ready, setReady] = useState(false);

  // echarts 懒加载：仅在报表页首次渲染图表时动态加载（约 1MB 独立 chunk），
  // 避免打入主 bundle 拖慢首屏；加载完成前显示占位
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mod = await import('echarts');
        // 【Bug14 修复】第一个 await 后就检查卸载标记（早退，省一次 wordcloud 导入）
        if (cancelled) return;
        // 词云插件需在 echarts 注册后导入（side-effect 自动注册）
        await import('echarts-wordcloud');
        if (cancelled) return;
        echartsRef.current = mod;
        setReady(true);
      } catch (e) {
        console.error('图表库加载失败:', e);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!ready || !containerRef.current) return;
    const echarts = echartsRef.current;
    if (!echarts) return;
    // 创建实例
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current, null, { renderer: 'canvas' });
    }
    const chart = chartRef.current;

    try {
      const option = buildOption(chartType, chartConfig);
      if (option) {
        chart.setOption(option, { notMerge: true });
        chart.resize();
      }
    } catch (e) {
      console.error('图表渲染异常:', chartType, e);
      chart.setOption({
        title: { text: `图表渲染异常: ${e.message}`, left: 'center', textStyle: { fontSize: 13, color: '#ef4444' } },
      });
    }

    return () => {
      // 组件卸载或参数变化时释放实例，避免内存泄漏
      if (chartRef.current) {
        chartRef.current.dispose();
        chartRef.current = null;
      }
    };
    // ready：echarts 懒加载完成后才初始化（首次 chartType/chartConfig 到来时可能还没加载完）
    // 优化：chartConfig 是对象引用，父组件每次渲染都传新对象——直接依赖会导致
    // dispose+重建循环；改用其内容签名（JSON.stringify），仅内容真正变化才重建。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, chartType, JSON.stringify(chartConfig)]);

  // resize 监听：handler 动态读取最新 chartRef，避免图表重建后调用已 dispose 的旧实例
  useEffect(() => {
    const handler = () => { if (chartRef.current) chartRef.current.resize(); };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  const hasData = Array.isArray(chartConfig?.数据) && chartConfig.数据.length > 0;

  const handleDownloadPng = () => {
    const chart = chartRef.current;
    if (!chart) return;
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
    const a = document.createElement('a');
    a.href = url;
    a.download = `${chartConfig?.标题 || 'chart'}.png`;
    a.click();
  };

  // 优化①：复制图表图片到剪贴板（贴进 PPT/聊天窗口）；部分浏览器不支持，
  // 失败时提示改用下载
  const [copyHint, setCopyHint] = useState('');
  const handleCopyImage = async () => {
    const chart = chartRef.current;
    if (!chart) return;
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
    try {
      const blob = await (await fetch(url)).blob();
      if (navigator.clipboard && window.ClipboardItem) {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        setCopyHint('已复制');
      } else {
        setCopyHint('当前浏览器不支持复制图片，请用下载');
      }
    } catch {
      setCopyHint('复制失败，请用下载');
    }
    setTimeout(() => setCopyHint(''), 2000);
  };

  return (
    <div style={{ position: 'relative', width: '100%', height, minHeight: 160 }}>
      {ready && hasData && (
        <>
          <button
            onClick={handleDownloadPng}
            title="下载图表 PNG"
            className="absolute top-1 right-1 z-[5] w-6 h-6 rounded-md bg-white/80 hover:bg-white border border-gray-200 flex items-center justify-center text-gray-400 hover:text-accent transition-all shadow-sm"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleCopyImage}
            title="复制图表图片到剪贴板"
            className="absolute top-1 right-8 z-[5] w-6 h-6 rounded-md bg-white/80 hover:bg-white border border-gray-200 flex items-center justify-center text-gray-400 hover:text-accent transition-all shadow-sm text-[10px] font-medium"
          >
            {copyHint ? '✓' : <Copy className="w-3 h-3" />}
          </button>
          {copyHint && (
            <div className="absolute top-8 right-8 z-[5] px-2 py-1 rounded bg-gray-800 text-white text-[10px] shadow">
              {copyHint}
            </div>
          )}
        </>
      )}
      {!ready && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: '#94a3b8', fontSize: 13, zIndex: 1,
        }}>
          图表加载中…
        </div>
      )}
      {ready && !hasData && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: '#94a3b8', fontSize: 13, zIndex: 1,
        }}>
          暂无图表数据
        </div>
      )}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}

// 阶段七十四 · A2：默认子标题——「这张图在比什么」。
// 标题是用户原话（可能是"那华南区呢"这种半个问句），子标题补上结构信息：
// 按哪个维度 + 哪个指标 + 什么图表。后端 chart_config.子标题 已给则优先用后端的。
function 默认子标题(type, xField, yFields, groupField) {
  const 指标 = (yFields || [])[0];
  const 维度 = xField || '分类';
  if (!指标) return '';
  const 动作 = {
    bar: '对比', stacked_bar: '分组成组对比', line: '趋势', area: '趋势',
    pie: '占比', donut: '占比', funnel: '转化', scatter: '相关关系',
    radar: '多维对比', heatmap: '分布',
  }[type] || '分布';
  const 分组 = groupField ? ` · 按${groupField}分组` : '';
  return `按${维度}的${指标}${动作}${分组}`;
}

// oxlint-disable-next-line react/only-export-components -- 导出 buildOption 供单测直接断言图表配置（防回归）
export function buildOption(chartType, config) {
  const rows = Array.isArray(config?.数据) ? config.数据 : [];
  if (!rows.length) return null;

  // 取值键回退：preferred 字段在数据中不存在时（旧报表/字段错配），
  // 自动用数据里第一个未被排除的列，避免所有图表显示 0
  function resolveKey(row, preferred, excludes = []) {
    if (row && preferred && row[preferred] !== undefined) return preferred;
    const exclude = new Set(excludes);
    return Object.keys(row || {}).find(k => !exclude.has(k) && row[k] !== undefined) || preferred;
  }

  const xField = config.X轴 || Object.keys(rows[0])[0] || '';
  const yFields = config.Y轴 || [];
  const groupField = config.颜色 || config.分组字段;
  const title = config.标题 || '';
  const nameField = config.名称;
  const valueField = config.值;
  // 阶段七十四 · A2：标题仍是用户意图（后端契约），子标题是「图里画的是什么」。
  // 默认给一个结构式子标题（图表类型 + 指标 + 分类维度），后端已给则用后端的。
  // 注意：这里必须用 chartType 参数而不是下面的 type 常量——type 在这一行之后才初始化
  // （TDZ 会抛 "Cannot access 'type' before initialization"，第一版就踩了这个）。
  const 子标题 = config.子标题 || 默认子标题(chartType || 'bar', xField, yFields, groupField);
  const 系列颜色 = config.系列颜色;
  const 显示标签 = config.显示数据标签;
  const 图例位置 = config.图例位置;
  const 图例名称映射 = config.图例名称;
  const 坐标范围 = Array.isArray(config.坐标范围) ? config.坐标范围 : null;
  const X轴别名 = config.X轴别名;
  const Y轴别名 = config.Y轴别名;

  // 轴配置工厂：别名 + 范围 + 数值轴公共设置（阶段55 键消费）
  function 轴(name, extra = {}) {
    return { ...extra, name, nameTextStyle: { color: '#475569' } };
  }
  // 阶段七十四 · A1（图表可读性）：标签默认开启
  // 背景：报表的图表配置里根本没有「显示数据标签」这个键（undefined），
  // 旧逻辑是 undefined → series.label ? series.label.show : false，
  // 于是所有类型默认都不标标签——饼图虽然写了 formatter 也没用（show 一直是 falsy），
  // 用户必须把鼠标悬浮到扇区上才知道这是哪个类别、占比多少。
  // 新策略：不传 = 默认显示；显式传 false 才关（精细化编辑里仍然能关掉）。
  const 标签默认开 = () => (显示标签 === undefined ? true : 显示标签);
  // 系列样式工厂：颜色 + 数据标签（阶段55 键消费；阶段74 默认开启）
  function 系列样式(series, labelOverride) {
    if (Array.isArray(系列颜色) && 系列颜色.length > 0) {
      series.itemStyle = { ...(series.itemStyle || {}), color: 系列颜色[0] };
    }
    const 开 = 标签默认开();
    series.label = { ...(series.label || {}), show: 开, ...(labelOverride || {}) };
    // 非饼图：标签密集时自动隐藏互相压住的那几个，否则柱状/折线会糊成一团墨
    if (开 && series.type !== 'pie') series.labelLayout = { hideOverlap: true };
    return series;
  }
  // 图例配置工厂：位置 + 名称映射（阶段55 键消费）
  function 图例(legend = {}) {
    const lg = { ...legend };
    if (图例位置) {
      delete lg.top;
      delete lg.bottom;
      if (图例位置 === 'top') lg.top = 0;
      else if (图例位置 === 'bottom') lg.bottom = 0;
      else lg[图例位置] = 0; // left/right 等直接按字符串键设位
    }
    if (图例名称映射 && lg.data) {
      lg.data = lg.data.map(d => 图例名称映射[d] || d);
    }
    return lg;
  }

  const base = {
    // 标题移出图形区顶部（top:0 固定），超长截断——避免长需求文本（如追问句子）
    // 居中覆盖在图形区上影响可读性
    title: {
      text: title.length > 30 ? `${title.slice(0, 30)}…` : title,
      left: 'center', top: 0,
      textStyle: { fontSize: 13, fontWeight: 600, color: '#1e293b' },
      ...(子标题 ? { subtext: 子标题, subtextStyle: { fontSize: 10, color: '#94a3b8' } } : {}),
    },
    color: COLORS,
    textStyle: CHART_TEXT_STYLE,
    // top: 6% 给标题留位，避免标题与图形/标签文字重叠
    grid: { left: '3%', right: '4%', top: '6%', bottom: '8%', containLabel: true },
    animationDuration: 600,
    animationEasing: 'cubicOut',
  };

  const type = chartType || 'bar';

  if (type === 'pie' || type === 'donut') {
    const nk = nameField || xField;
    const vk = valueField || (yFields[0] || Object.keys(rows[0]).find(k => k !== nk) || '');
    // 取值回退：值字段与数据列不匹配时（如旧报表"值=职位ID"但数据只有"记录数"），
    // 自动用数据里第一个非名称列，避免全部显示 0%
    const fallbackVk = (rows[0] && rows[0][vk] !== undefined) ? vk
      : (Object.keys(rows[0] || {}).find(k => k !== nk) || vk);
    // 阶段 33 修复（饼图全 0.0% bug）：值列数值全部无效（0/NaN/文本，如历史"明细饼图"
    // 把原始数据行当报表数据）时，兜底为"按名称计数"——图例自动合并重复分类，
    // 占比正常展示，而不是画一个全 0.0% 的实心圆。
    let pieData = rows.map(r => ({ name: String(r[nk] ?? ''), value: Number(r[fallbackVk]) || 0 }));
    if (pieData.reduce((s, d) => s + d.value, 0) <= 0) {
      const countMap = new Map();
      for (const r of rows) {
        const n = String(r[nk] ?? '');
        countMap.set(n, (countMap.get(n) || 0) + 1);
      }
      pieData = [...countMap.entries()].map(([name, value]) => ({ name, value }));
    }
    const pieSeries = {
      type: 'pie', radius: type === 'donut' ? ['45%', '70%'] : ['0%', '60%'],
      data: pieData,
      // 优化：label 同样转义 p.name（名称来自上传数据，统一走 escapeHtml）
      label: { formatter: (p) => `${escapeHtml(p.name)}\n${(p.percent ?? 0).toFixed(1)}%` },
    };
    const styledPie = 系列样式(pieSeries);
    return {
      ...base,
      // 用 formatter 函数手动算百分比（不依赖 {d} 占位符，避免显示 0%）
      tooltip: {
        ...CHART_TOOLTIP, trigger: 'item',
        // P0 加固：p.name 来自上传数据，转义防存储型 XSS
        formatter: (p) => `${escapeHtml(p.name)}: ${p.value} (${(p.percent ?? 0).toFixed(1)}%)`,
      },
      series: [styledPie],
    };
  }

  if (type === 'line' || type === 'area') {
    const yf = resolveKey(rows[0], yFields[0], [xField]);
    const lineOpt = {
      ...base, tooltip: { trigger: 'axis' },
      xAxis: 轴(X轴别名 || '', { type: 'category', data: rows.map(r => String(r[xField] ?? '')) }),
      yAxis: 轴(Y轴别名 || '', { type: 'value', ...(坐标范围 ? { min: 坐标范围[0], max: 坐标范围[1] } : {}) }),
      series: [系列样式({
        type: 'line', data: rows.map(r => Number(r[yf]) || 0),
        smooth: true, areaStyle: type === 'area' ? { opacity: 0.4 } : undefined,
      })],
    };
    return lineOpt;
  }

  if (type === 'scatter') {
    const yf = resolveKey(rows[0], yFields[0], [xField]);
    return {
      ...base,
      xAxis: { type: 'value', name: X轴别名 || xField, ...(坐标范围 ? { min: 坐标范围[0], max: 坐标范围[1] } : {}) },
      yAxis: { type: 'value', name: Y轴别名 || yf },
      series: [系列样式({ type: 'scatter', data: rows.map(r => [Number(r[xField]) || 0, Number(r[yf]) || 0]), symbolSize: 8 })],
    };
  }

  if (type === 'radar') {
    // 指标列必须是数据中真实存在的键（过滤旧报表/字段错配导致的不存在列）
    const indicatorKeys = (yFields.length >= 2 ? yFields : Object.keys(rows[0]).filter(k => k !== xField))
      .filter(k => rows[0] && rows[0][k] !== undefined);
    const indicators = indicatorKeys.map(f => ({ name: f }));
    return {
      ...base, tooltip: { trigger: 'item' },
      legend: { data: rows.map(r => String(r[xField] ?? '')), bottom: 0 },
      radar: { indicator: indicators, radius: '60%' },
      series: [{
        type: 'radar',
        data: rows.map(r => ({ name: String(r[xField] ?? ''), value: indicators.map(ind => Number(r[ind.name]) || 0) })),
      }],
    };
  }

  if (type === 'heatmap' && groupField) {
    const xVals = [...new Set(rows.map(r => String(r[xField] ?? '')))];
    const yVals = [...new Set(rows.map(r => String(r[groupField] ?? '')))];
    const vf = resolveKey(rows[0], yFields[0], [xField, groupField]);
    const hData = rows.map(r => [xVals.indexOf(String(r[xField] ?? '')), yVals.indexOf(String(r[groupField] ?? '')), Number(r[vf]) || 0]);
    return {
      ...base, tooltip: { position: 'top' },
      xAxis: { type: 'category', data: xVals, splitArea: { show: true } },
      yAxis: { type: 'category', data: yVals, splitArea: { show: true } },
      visualMap: { min: 0, max: Math.max(...hData.map(d => d[2]), 1), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
      series: [{ type: 'heatmap', data: hData, label: { show: true } }],
    };
  }

  if (groupField && (type === 'stacked_bar' || type === 'bar')) {
    const groups = [...new Set(rows.map(r => String(r[groupField] ?? '')))];
    const xVals = [...new Set(rows.map(r => String(r[xField] ?? '')))];
    const yf = resolveKey(rows[0], yFields[0], [xField, groupField]);
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: 图例({ data: groups, bottom: 0 }),
      xAxis: 轴(X轴别名 || '', {
        type: 'category', data: xVals,
        // X 轴标签过长时旋转 + 截断（如股票代码/长部门名），避免标签重叠覆盖图形
        axisLabel: { rotate: xVals.some(v => v.length > 6) ? 35 : 0, overflow: 'truncate', width: 80 },
      }),
      yAxis: 轴(Y轴别名 || '', { type: 'value', ...(坐标范围 ? { min: 坐标范围[0], max: 坐标范围[1] } : {}) }),
      series: groups.map((g, i) => ({
        name: (图例名称映射 && 图例名称映射[g]) || g, type: 'bar', stack: 'total',
        data: xVals.map(xv => { const m = rows.find(r => String(r[xField] ?? '') === xv && String(r[groupField] ?? '') === g); return m ? Number(m[yf]) || 0 : 0; }),
        itemStyle: { color: (Array.isArray(系列颜色) && 系列颜色[i % 系列颜色.length]) || COLORS[i % COLORS.length] },
        // 阶段七十四 · A1：分组/堆积柱状图此前完全没消费「显示数据标签」，
        // 每个色块只能靠悬浮才知道多高。默认开标签 + 重叠自动隐藏。
        label: { show: 标签默认开() },
        labelLayout: { hideOverlap: true },
        animationDelay: (idx) => idx * 50,
      })),
    };
  }

  if (type === 'histogram') {
    const yf = resolveKey(rows[0], yFields[0], [xField]);
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')), axisLabel: { rotate: 45 } },
      yAxis: 轴(Y轴别名 || '', { type: 'value', ...(坐标范围 ? { min: 坐标范围[0], max: 坐标范围[1] } : {}) }),
      series: [系列样式({
        type: 'bar', data: rows.map(r => Number(r[yf]) || 0), barWidth: '99%', itemStyle: { color: '#6366f1' }, animationDelay: (idx) => idx * 60,
      })],
    };
  }

  if (type === 'wordcloud') {
    const nk = nameField || 'name';
    const vk = resolveKey(rows[0], valueField || 'value', [nk]);
    return {
      ...base, tooltip: { show: true },
      series: [{
        type: 'wordCloud', shape: 'circle', width: '92%', height: '78%',
        gridSize: 6, sizeRange: [14, 56], rotationRange: [0, 0],
        textStyle: { fontFamily: 'Microsoft YaHei, sans-serif' },
        emphasis: { focus: 'self' },
        data: rows.map(r => ({ name: String(r[nk] ?? ''), value: Number(r[vk]) || 0 })),
      }],
    };
  }

  if (type === 'funnel') {
    const nk = nameField || xField || Object.keys(rows[0])[0];
    const vk = valueField || (yFields[0] || Object.keys(rows[0]).find(k => k !== nk) || '');
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'item', formatter: (p) => `${escapeHtml(p.name)}: ${p.value}` },
      series: [{
        type: 'funnel', left: '12%', width: '76%', top: 40, bottom: 20,
        label: { formatter: '{b} {c}' },
        data: rows.map(r => ({ name: String(r[nk] ?? ''), value: Number(r[vk]) || 0 })),
      }],
    };
  }

  if (type === 'sankey') {
    const links = rows.map(r => ({
      source: String(r.源 ?? r.source ?? ''),
      target: String(r.目标 ?? r.target ?? ''),
      value: Number(r.value ?? 0),
    }));
    const nodes = [...new Set([...links.map(l => l.source), ...links.map(l => l.target)])].map(name => ({ name }));
    return {
      ...base, tooltip: { trigger: 'item' },
      series: [{
        type: 'sankey', left: '4%', right: '12%', top: 40, bottom: 20,
        data: nodes, links, label: { fontSize: 11 },
        emphasis: { focus: 'adjacency' },
      }],
    };
  }

  if (type === 'boxplot') {
    const nk = nameField || 'name';
    return {
      ...base, tooltip: { trigger: 'item' },
      xAxis: { type: 'category', data: rows.map(r => String(r[nk] ?? '')) },
      yAxis: { type: 'value' },
      series: [{
        type: 'boxplot', data: rows.map(r => Array.isArray(r.value) ? r.value : []),
        itemStyle: { color: '#6366f1' },
      }],
    };
  }

  if (type === 'waterfall') {
    const nk = nameField || 'name';
    const vk = valueField || 'value';
    const values = rows.map(r => Number(r[vk]) || 0);
    const baseData = [];
    let acc = 0;
    for (const v of values) { baseData.push(acc); acc += v; }
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: [...rows.map(r => String(r[nk] ?? '')), '合计'] },
      yAxis: { type: 'value' },
      series: [
        { name: '占位', type: 'bar', stack: 'wf', itemStyle: { color: 'transparent' }, data: [...baseData, 0] },
        {
          name: '值', type: 'bar', stack: 'wf',
          data: [...values, acc],
          label: { show: true, position: 'top', formatter: (p) => (p.dataIndex === values.length ? `合计 ${p.value}` : p.value) },
        },
      ],
    };
  }

  if (type === 'sunburst') {
    const hasLevel = rows.some(r => r.层级 !== undefined);
    let data;
    if (hasLevel) {
      const map = {};
      for (const r of rows) {
        const lv = String(r.层级 ?? '');
        if (!map[lv]) map[lv] = { name: lv, children: [] };
        map[lv].children.push({ name: String(r.名称 ?? ''), value: Number(r.value ?? 0) });
      }
      data = Object.values(map);
    } else {
      data = rows.map(r => ({ name: String(r.名称 ?? r[xField] ?? ''), value: Number(r.value ?? 0) }));
    }
    return {
      ...base, tooltip: { trigger: 'item' },
      series: [{ type: 'sunburst', radius: ['20%', '85%'], data, label: { fontSize: 11 } }],
    };
  }

  if (type === 'candlestick') {
    const nk = nameField || 'name';
    return {
      ...base, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: rows.map(r => String(r[nk] ?? '')), axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' },
      series: [{
        type: 'candlestick', data: rows.map(r => Array.isArray(r.value) ? r.value : []),
        itemStyle: { color: '#ef4444', color0: '#10b981', borderColor: '#ef4444', borderColor0: '#10b981' },
      }],
    };
  }

  const yf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField) || '';
  return {
    ...base, tooltip: { trigger: 'axis' },
    xAxis: 轴(X轴别名 || '', { type: 'category', data: rows.map(r => String(r[xField] ?? '')) }),
    yAxis: 轴(Y轴别名 || '', { type: 'value', ...(坐标范围 ? { min: 坐标范围[0], max: 坐标范围[1] } : {}) }),
    series: [系列样式({ type: 'bar', data: rows.map(r => Number(r[yf]) || 0), animationDelay: (idx) => idx * 60 })],
  };
}
