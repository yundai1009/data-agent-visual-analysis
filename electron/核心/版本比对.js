// electron/核心/版本比对.js
/**
 * 语义化版本字符串比较：'1.2.3' vs '1.10.0' 按数字段比较。
 * 返回：'最新'（本地>=最新）| '可更新'（本地<最新）| '未知'（任一解析失败）
 * @param {string} 本地
 * @param {string} 最新
 */
function 比对版本(本地, 最新) {
  const 解析 = (v) => String(v || '').trim().split('.').map(n => parseInt(n, 10));
  const a = 解析(本地);
  const b = 解析(最新);
  if (a.some(Number.isNaN) || b.some(Number.isNaN) || a.length === 0 || b.length === 0) {
    return '未知';
  }
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x > y) return '最新';
    if (x < y) return '可更新';
  }
  return '最新';
}

module.exports = { 比对版本 };