import { useRef, useEffect } from 'react';
import * as echarts from 'echarts';
// 词云扩展：echarts-wordcloud 2.x 自动注册（与 echarts 6 的兼容性依赖运行时；若报错回退到 ECharts 自定义 series 或直接文字展示）
import 'echarts-wordcloud';

// 藏青系协调色板 + 主题常量（阶段 13 重设计：与 UI 主色统一）
const COLORS = ['#0f4c81', '#3d7bb8', '#5b8cb8', '#8aa9c4', '#b45309', '#0f766e', '#64748b', '#334155'];
const CHART_TEXT_STYLE = { fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif', fontSize: 12, color: '#475569' };
const CHART_TOOLTIP = {
  backgroundColor: '#ffffff',
  borderColor: '#e2e8f0',
  borderWidth: 1,
  textStyle: { fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif', fontSize: 12, color: '#1e293b' },
  extraCssText: 'box-shadow: 0 8px 16px -8px rgba(15,76,129,.15); border-radius: 8px;',
};

export default function EChartsChart({ chartType, chartConfig, height = 320 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
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
  }, [chartType, chartConfig]);

  // resize 监听：handler 动态读取最新 chartRef，避免图表重建后调用已 dispose 的旧实例
  useEffect(() => {
    const handler = () => { if (chartRef.current) chartRef.current.resize(); };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  const hasData = Array.isArray(chartConfig?.数据) && chartConfig.数据.length > 0;

  return (
    <div style={{ position: 'relative', width: '100%', height, minHeight: 160 }}>
      {!hasData && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: '#999', fontSize: 14, zIndex: 1,
        }}>
          暂无图表数据
        </div>
      )}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}

function buildOption(chartType, config) {
  const rows = Array.isArray(config?.数据) ? config.数据 : [];
  if (!rows.length) return null;

  const xField = config.X轴 || Object.keys(rows[0])[0] || '';
  const yFields = config.Y轴 || [];
  const groupField = config.颜色 || config.分组字段;
  const title = config.标题 || '';
  const nameField = config.名称;
  const valueField = config.值;

  const base = {
    title: { text: title, left: 'center', textStyle: { fontSize: 14, fontWeight: 600, color: '#1e293b' } },
    color: COLORS,
    textStyle: CHART_TEXT_STYLE,
    grid: { left: '3%', right: '4%', bottom: '8%', containLabel: true },
    animationDuration: 600,
    animationEasing: 'cubicOut',
  };

  const type = chartType || 'bar';

  if (type === 'pie' || type === 'donut') {
    const nk = nameField || xField;
    const vk = valueField || (yFields[0] || Object.keys(rows[0]).find(k => k !== nk) || '');
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: type === 'donut' ? ['45%', '70%'] : ['0%', '60%'],
        data: rows.map(r => ({ name: String(r[nk] ?? ''), value: Number(r[vk]) || 0 })),
        label: { formatter: '{b}\n{d}%' },
      }],
    };
  }

  if (type === 'line' || type === 'area') {
    const yf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField) || '';
    return {
      ...base, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
      yAxis: { type: 'value' },
      series: [{
        type: 'line', data: rows.map(r => Number(r[yf]) || 0),
        smooth: true, areaStyle: type === 'area' ? { opacity: 0.4 } : undefined,
      }],
    };
  }

  if (type === 'scatter') {
    const yf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField) || '';
    return {
      ...base,
      xAxis: { type: 'value', name: xField },
      yAxis: { type: 'value', name: yf },
      series: [{ type: 'scatter', data: rows.map(r => [Number(r[xField]) || 0, Number(r[yf]) || 0]), symbolSize: 8 }],
    };
  }

  if (type === 'radar') {
    const indicators = (yFields.length >= 2 ? yFields : Object.keys(rows[0]).filter(k => k !== xField)).map(f => ({ name: f }));
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
    const vf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField && k !== groupField) || '';
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
    const yf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField && k !== groupField) || '';
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: groups, bottom: 0 },
      xAxis: { type: 'category', data: xVals },
      yAxis: { type: 'value' },
      series: groups.map((g, i) => ({
        name: g, type: 'bar', stack: 'total',
        data: xVals.map(xv => { const m = rows.find(r => String(r[xField] ?? '') === xv && String(r[groupField] ?? '') === g); return m ? Number(m[yf]) || 0 : 0; }),
        itemStyle: { color: COLORS[i % COLORS.length] },
      })),
    };
  }

  if (type === 'histogram') {
    const yf = yFields[0] || Object.keys(rows[0]).find(k => k !== xField) || '';
    return {
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')), axisLabel: { rotate: 45 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: rows.map(r => Number(r[yf]) || 0), barWidth: '99%', itemStyle: { color: '#6366f1' } }],
    };
  }

  if (type === 'wordcloud') {
    const nk = nameField || 'name';
    const vk = valueField || 'value';
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
      ...base, tooltip: { ...CHART_TOOLTIP, trigger: 'item', formatter: '{b}: {c}' },
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
    xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: rows.map(r => Number(r[yf]) || 0) }],
  };
}
