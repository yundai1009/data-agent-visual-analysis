import { describe, it, expect } from 'vitest';
import validateChartFields from '../chartFields';

const profile = {
  数值字段: ['销售额'],
  分类字段: ['地区'],
  日期字段: ['日期'],
  文本字段: ['备注'],
};

const RET = {
  scatterX: '散点图的 X 轴需要选择数值字段',
  scatterY: '散点图的 Y 轴需要选择数值字段',
  histogram: '直方图的 X 轴需要选择数值字段',
  pie: '饼图的 X 轴建议选择分类字段，当前选择可能不适用',
  heatmap: '热力图需要设置分组字段',
  sankey: '桑基图需要设置分组字段（作为流向的源）',
  boxplot: '箱线图的 Y 轴需要选择数值字段',
  candlestick: 'K线图的 Y 轴需要选择数值字段',
  waterfall: '瀑布图的 Y 轴需要选择数值字段',
  funnel: '漏斗图的 X 轴建议选择分类字段',
  donut: '环形图的 X 轴建议选择分类字段',
  wordcloud: '词云图的 X 轴建议选择文本字段（长文本，如评论/备注）',
  stacked: '堆积柱状图需要设置分组字段',
};

describe('validateChartFields', () => {
  it('无 profile 时直接通过', () => {
    expect(validateChartFields('bar', 'x', 'y', '无', null)).toBe(null);
  });

  it('scatter：X/Y 都需数值', () => {
    expect(validateChartFields('scatter', '地区', '销售额', '无', profile)).toBe(RET.scatterX);
    expect(validateChartFields('scatter', '销售额', '日期', '无', profile)).toBe(RET.scatterY);
    expect(validateChartFields('scatter', '销售额', '销售额', '无', profile)).toBe(null);
  });

  it('histogram：X 需数值', () => {
    expect(validateChartFields('histogram', '地区', '', '无', profile)).toBe(RET.histogram);
    expect(validateChartFields('histogram', '销售额', '', '无', profile)).toBe(null);
  });

  it('pie：X 建议分类', () => {
    expect(validateChartFields('pie', '销售额', '', '无', profile)).toBe(RET.pie);
    expect(validateChartFields('pie', '地区', '', '无', profile)).toBe(null);
  });

  it('heatmap / sankey：需分组字段', () => {
    expect(validateChartFields('heatmap', '地区', '销售额', '无', profile)).toBe(RET.heatmap);
    expect(validateChartFields('heatmap', '地区', '销售额', '地区', profile)).toBe(null);
    expect(validateChartFields('sankey', '地区', '销售额', '无', profile)).toBe(RET.sankey);
  });

  it('boxplot / candlestick / waterfall：Y 需数值', () => {
    expect(validateChartFields('boxplot', '地区', '地区', '无', profile)).toBe(RET.boxplot);
    expect(validateChartFields('boxplot', '地区', '销售额', '无', profile)).toBe(null);
    expect(validateChartFields('candlestick', '日期', '地区', '无', profile)).toBe(RET.candlestick);
    expect(validateChartFields('waterfall', '地区', '地区', '无', profile)).toBe(RET.waterfall);
  });

  it('funnel / donut：X 建议分类', () => {
    expect(validateChartFields('funnel', '销售额', '', '无', profile)).toBe(RET.funnel);
    expect(validateChartFields('donut', '销售额', '', '无', profile)).toBe(RET.donut);
    expect(validateChartFields('donut', '地区', '', '无', profile)).toBe(null);
  });

  it('wordcloud：X 建议文本字段', () => {
    expect(validateChartFields('wordcloud', '地区', '', '无', profile)).toBe(RET.wordcloud);
    expect(validateChartFields('wordcloud', '备注', '', '无', profile)).toBe(null);
    // 数值字段不是分类 → 不触发文本提示
    expect(validateChartFields('wordcloud', '销售额', '', '无', profile)).toBe(null);
  });

  it('stacked / stacked_bar：需分组字段', () => {
    expect(validateChartFields('stacked', '地区', '销售额', '无', profile)).toBe(RET.stacked);
    expect(validateChartFields('stacked_bar', '地区', '销售额', '无', profile)).toBe(RET.stacked);
    expect(validateChartFields('stacked', '地区', '销售额', '地区', profile)).toBe(null);
  });

  it('默认图表类型(bars/line/table 等)始终通过', () => {
    expect(validateChartFields('bar', '地区', '销售额', '无', profile)).toBe(null);
    expect(validateChartFields('line', '日期', '销售额', '无', profile)).toBe(null);
    expect(validateChartFields('table', '', '', '无', profile)).toBe(null);
  });
});