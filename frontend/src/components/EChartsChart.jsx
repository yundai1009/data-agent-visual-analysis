import React from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  VisualMapComponent, DatasetComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart,
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  VisualMapComponent, DatasetComponent,
  CanvasRenderer,
]);

const CHART_COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

function buildOption(chartType, chartConfig) {
  const { X轴: xField, Y轴: yFields, 颜色: groupField, 数据: data, 名称: nameField, 值: valueField } = chartConfig || {};
  const title = chartConfig?.标题 || '';
  const rows = Array.isArray(data) ? data : [];

  if (!rows.length) {
    return { title: { text: '暂无数据' }, xAxis: {}, yAxis: {}, series: [] };
  }

  const baseOption = {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    color: CHART_COLORS,
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  };

  switch (chartType) {
    case 'pie': {
      const nameKey = nameField || xField || Object.keys(rows[0])[0];
      const valKey = valueField || (yFields && yFields[0]) || Object.keys(rows[0])[1];
      return {
        ...baseOption,
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        series: [{
          type: 'pie',
          radius: ['0%', '60%'],
          center: ['50%', '55%'],
          data: rows.map(r => ({ name: String(r[nameKey] ?? ''), value: Number(r[valKey]) || 0 })),
          encode: { itemName: nameKey, value: valKey },
          label: { formatter: '{b}\n{d}%' },
          emphasis: { itemStyle: { shadowBlur: 10 } },
        }],
      };
    }

    case 'line': {
      const yField = yFields && yFields[0] ? yFields[0] : (Object.keys(rows[0]).find(k => k !== xField) || '');
      return {
        ...baseOption,
        xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
        yAxis: { type: 'value' },
        series: [{
          type: 'line',
          data: rows.map(r => Number(r[yField]) || 0),
          smooth: true,
          areaStyle: { opacity: 0.15 },
          lineStyle: { width: 2 },
        }],
      };
    }

    case 'bar':
    case 'stacked_bar': {
      if (groupField) {
        // 堆积柱状图：按分组字段拆多个 series
        const groups = [...new Set(rows.map(r => String(r[groupField] ?? '')))];
        const xValues = [...new Set(rows.map(r => String(r[xField] ?? '')))];
        const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField && k !== groupField) || '';
        return {
          ...baseOption,
          tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
          legend: { data: groups, bottom: 0 },
          xAxis: { type: 'category', data: xValues },
          yAxis: { type: 'value' },
          series: groups.map((g, i) => ({
            name: g,
            type: 'bar',
            stack: chartType === 'stacked_bar' ? 'total' : undefined,
            data: xValues.map(xv => {
              const match = rows.find(r => String(r[xField] ?? '') === xv && String(r[groupField] ?? '') === g);
              return match ? Number(match[yField]) || 0 : 0;
            }),
            itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] },
          })),
        };
      }
      const yField = yFields && yFields[0] ? yFields[0] : (Object.keys(rows[0]).find(k => k !== xField) || '');
      return {
        ...baseOption,
        xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
        yAxis: { type: 'value' },
        series: [{
          type: 'bar',
          data: rows.map(r => Number(r[yField]) || 0),
          itemStyle: { borderRadius: [4, 4, 0, 0] },
        }],
      };
    }

    case 'scatter': {
      const xDataKey = xField || Object.keys(rows[0])[0];
      const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xDataKey) || '';
      return {
        ...baseOption,
        xAxis: { type: 'value', name: xDataKey },
        yAxis: { type: 'value', name: yField },
        series: [{
          type: 'scatter',
          data: rows.map(r => [Number(r[xDataKey]) || 0, Number(r[yField]) || 0]),
          symbolSize: 8,
        }],
      };
    }

    case 'heatmap': {
      if (!groupField) {
        // 降级为柱状图
        const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField) || '';
        return {
          ...baseOption,
          xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
          yAxis: { type: 'value' },
          series: [{ type: 'bar', data: rows.map(r => Number(r[yField]) || 0) }],
        };
      }
      const xValues = [...new Set(rows.map(r => String(r[xField] ?? '')))];
      const yValues = [...new Set(rows.map(r => String(r[groupField] ?? '')))];
      const valField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField && k !== groupField) || '';
      const heatData = rows.map(r => [
        xValues.indexOf(String(r[xField] ?? '')),
        yValues.indexOf(String(r[groupField] ?? '')),
        Number(r[valField]) || 0,
      ]);
      return {
        ...baseOption,
        tooltip: { position: 'top' },
        xAxis: { type: 'category', data: xValues, splitArea: { show: true } },
        yAxis: { type: 'category', data: yValues, splitArea: { show: true } },
        visualMap: { min: 0, max: Math.max(...heatData.map(d => d[2]), 1), calculable: true, orient: 'horizontal', left: 'center', bottom: '0%' },
        series: [{
          type: 'heatmap',
          data: heatData,
          label: { show: true },
          emphasis: { itemStyle: { shadowBlur: 10 } },
        }],
      };
    }

    case 'area': {
      const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField) || '';
      return {
        ...baseOption,
        xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
        yAxis: { type: 'value' },
        series: [{
          type: 'line',
          data: rows.map(r => Number(r[yField]) || 0),
          smooth: true,
          areaStyle: { opacity: 0.4 },
          lineStyle: { width: 2 },
          symbol: 'none',
        }],
      };
    }

    case 'radar': {
      if (!yFields || yFields.length < 2) {
        return { ...baseOption, title: { ...baseOption.title, subtext: '雷达图需要至少 2 个指标' } };
      }
      const indicator = yFields.map(f => ({ name: f }));
      const firstRow = rows[0] || {};
      return {
        ...baseOption,
        tooltip: { trigger: 'item' },
        legend: { data: rows.map(r => String(r[xField] ?? '')), bottom: 0 },
        radar: { indicator, radius: '60%' },
        series: [{
          type: 'radar',
          data: rows.map(r => ({
            name: String(r[xField] ?? ''),
            value: yFields.map(f => Number(r[f]) || 0),
          })),
        }],
      };
    }

    case 'histogram': {
      const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField) || '';
      return {
        ...baseOption,
        xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')), axisLabel: { rotate: 45 } },
        yAxis: { type: 'value' },
        series: [{
          type: 'bar',
          data: rows.map(r => Number(r[yField]) || 0),
          itemStyle: { color: '#6366f1' },
        }],
      };
    }

    default: {
      // table = 默认柱状图兜底
      const yField = yFields && yFields[0] ? yFields[0] : Object.keys(rows[0]).find(k => k !== xField) || '';
      return {
        ...baseOption,
        xAxis: { type: 'category', data: rows.map(r => String(r[xField] ?? '')) },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: rows.map(r => Number(r[yField]) || 0) }],
      };
    }
  }
}

const CHART_TYPE_MAP = {
  bar: 'bar', line: 'line', pie: 'pie', scatter: 'scatter',
  heatmap: 'heatmap', stacked_bar: 'stacked_bar', area: 'area',
  radar: 'radar', histogram: 'histogram', auto: 'bar', table: 'bar',
};

export default function EChartsChart({ chartType, chartConfig, height = 320 }) {
  const eType = CHART_TYPE_MAP[chartType] || 'bar';
  const option = buildOption(eType, chartConfig);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height, width: '100%' }}
      notMerge
      lazyUpdate
      showLoading={!chartConfig?.数据?.length}
    />
  );
}
