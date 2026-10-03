/**
 * 清洗操作摘要 → 可读中文描述（纯函数，可单测）。
 * 阶段 52 缺陷修复：清洗弹窗原本直接 `JSON.stringify(操作摘要)` 原样输出，
 * 用户在弹窗里看到的是 `{"去重":{"执行":true,"删除行数":0}...}` 这类原始 JSON。
 */
export function 清洗摘要转文本(摘要) {
  if (!摘要 || typeof 摘要 !== 'object') return '';
  const rows = [];
  const actions = {
    去重: (v) => (v?.执行 ? `去重：删除 ${v?.删除行数 ?? 0} 行重复数据` : '去重：未执行'),
    填充缺失: (v) => (v?.执行 ? `填充缺失：${v?.填充列数 ?? 0} 列` : '填充缺失：未执行'),
    删除空行: (v) => (v?.执行 ? `删除空行：删除 ${v?.删除行数 ?? 0} 行` : '删除空行：未执行'),
  };
  for (const [key, val] of Object.entries(摘要)) {
    const fmt = actions[key];
    if (fmt) {
      rows.push(fmt(val));
    } else if (typeof val === 'object' && val !== null) {
      rows.push(`${key}：${清洗摘要转文本(val)}`.replace(/：：/g, '：'));
    } else {
      rows.push(`${key}：${String(val)}`);
    }
  }
  return rows.join('；');
}