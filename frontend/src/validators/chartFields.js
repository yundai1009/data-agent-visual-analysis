// 图表类型 × 字段匹配校验（纯函数，可单测）
// 返回错误提示字符串，校验通过返回 null。

export default function validateChartFields(type, x, y, group, profile) {
  if (!profile) return null;
  const nf = new Set(profile.数值字段 || []);
  const cf = new Set(profile.分类字段 || []);
  const df = new Set(profile.日期字段 || []);
  const xIsNum = nf.has(x);
  const yIsNum = nf.has(y);
  const xIsCat = cf.has(x) || df.has(x);
  const hasGroup = group && group !== '无';

  switch (type) {
    case 'scatter':
      if (!xIsNum) return '散点图的 X 轴需要选择数值字段';
      if (!yIsNum) return '散点图的 Y 轴需要选择数值字段';
      break;
    case 'histogram':
      if (!xIsNum) return '直方图的 X 轴需要选择数值字段';
      break;
    case 'pie':
      if (!xIsCat && x) return '饼图的 X 轴建议选择分类字段，当前选择可能不适用';
      break;
    case 'heatmap':
      if (!hasGroup) return '热力图需要设置分组字段';
      break;
    case 'sankey':
      if (!hasGroup) return '桑基图需要设置分组字段（作为流向的源）';
      break;
    case 'boxplot':
      if (!yIsNum) return '箱线图的 Y 轴需要选择数值字段';
      break;
    case 'candlestick':
      if (!yIsNum) return 'K线图的 Y 轴需要选择数值字段';
      break;
    case 'waterfall':
      if (!yIsNum) return '瀑布图的 Y 轴需要选择数值字段';
      break;
    case 'funnel':
      if (!xIsCat && x) return '漏斗图的 X 轴建议选择分类字段';
      break;
    case 'donut':
      if (!xIsCat && x) return '环形图的 X 轴建议选择分类字段';
      break;
    case 'wordcloud':
      if (x && !(profile.文本字段 || []).includes(x) && xIsCat) return '词云图的 X 轴建议选择文本字段（长文本，如评论/备注）';
      break;
    case 'stacked':
    case 'stacked_bar':
      if (!hasGroup) return '堆积柱状图需要设置分组字段';
      break;
  }
  return null;
}