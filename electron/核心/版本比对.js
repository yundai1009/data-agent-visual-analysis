// 更新检查的语义判断：本地版本 vs GitHub Releases 最新 tag，产出「最新 / 可更新 / 未知」三态。
// 做了什么：比对版本(本地, 最新) 按 . 分段 parseInt 后逐段做数值比较（缺失段按 0 补），首个不等即返回；
//   任一段 parseInt 出 NaN（非法版本号）或版本串为空 → 返回 '未知'，绝不猜。
// 为什么自己写而不引 semver：这里只需要「大于 / 小于 / 相等」三个结论，比较逻辑十几行；
//   为此引入 semver 换来的是 prerelease、build 元数据解析和一份运行时依赖，还得额外包 try 兜它对非标准串直接 throw 的行为。
// 为什么把「未知」单列一态而不是并进「可更新」：网络不通、仓库 tag 格式异常都落在这里，
//   误判成可更新会让已在最新版的用户反复被提示下载——这类误报比漏报更劝退。
// 坑：判定是「本地 >= 最新 = 最新」，同版本号不提示更新，也因此不区分本地是不是预发布版。
// 坑：返回的是给前端直接展示/判断的中文枚举，不是 semver 那种比较函数或差值；调用方拿它做 if 即可。
// 坑：tag 的 v 前缀由 main.js 先 replace(/^v/i, '') 剥掉，本函数不负责剥离，传入带 v 的版本号会被 parseInt 解析成 NaN 而落到「未知」。
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