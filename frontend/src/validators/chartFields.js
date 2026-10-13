// 图表类型 × 字段的匹配校验：在真正生成图表之前拦住「字段类型不对」的组合。
// 做了什么：export default validateChartFields(type, x, y, group, profile)，按图表类型分别判定所需字段，
//   通过返回 null，不通过返回一句可直接展示的中文提示；只依赖 profile 里的 数值字段 / 分类字段 / 日期字段 / 文本字段 四份清单。
// 为什么判定要抽成纯函数而不是写在图表配置弹窗里：这份规则是「哪种图能吃什么字段」的唯一事实来源，
//   埋在组件里就只能靠手点「每种图 × 每种字段组合」来验证；抽出来后能对着真实 profile 批量单测（见 validators/__tests__）。
// 为什么不直接复用后端 report_generator 的字段要求：后端拿到的是重塑后的数据形状（列名已变成 名称/值 之类的角色占位名），
//   而这里的 profile 是用户上传时的原始字段画像，两者不在同一层；强行复用会把后端那套角色占位名黑名单漏进前端。
// 约定：饼图 / 漏斗图 / 环形图 / 词云 用的是「建议」措辞且不阻断——数值字段画饼图是常见用法，硬拦会挡住合理需求。
// 约定：日期字段与分类字段一视同仁（xIsCat 同时接受两者），因为绝大多数图表的分桶轴两种都能吃。
// 坑：profile 为空直接返回 null 是刻意的——字段画像是异步算出来的，先到的调用不能因为画像还没到就把用户堵在弹窗里。
// 坑：词云只报错于「X 选了分类字段、且该字段不在 文本字段 清单里」这一种组合；选数值字段、或不选 X 都不会提示。
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