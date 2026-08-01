import { useRef, useEffect } from 'react';
import * as echarts from 'echarts';

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

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

  // resize 监听
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const handler = () => chart.resize();
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
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    color: COLORS,
    grid: { left: '3%', right: '4%', bottom: '8%', containLabel: true },
  };

  const type = chartType || 'bar';

  if (type === 'pie') {
    const nk = nameField || xField;
    const vk = valueField || (yFields[0] || Object.keys(rows[0]).find(k => k !== nk) || '');
    return {
      ...base, tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['0%', '60%'],
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
      ...base, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
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
      ...base, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')), axisLabel: { rotate: 45 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: rows.map(r => Number(r[yf]) || 0), barWidth: '99%', itemStyle: { color: '#6366f1' } }],
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
