// 拖拽上传的前端侧过滤：把浏览器丢过来的 File 列表筛成「后端一定收得下」的子集。
// 做了什么：提取可上传文件(files) 返回 { name, path, 扩展名 }[]，只保留扩展名在白名单里的项；
//   扩展名取文件名最后一个 . 之后的部分并小写；同时导出 允许扩展名，供 UI 直接渲染 accept 与提示文案。
// 为什么白名单放前端而不是让用户传上去再由后端拒绝：拖拽常常一次落下十几个文件（文件夹、图片、PDF），
//   先筛一遍能把「哪些不支持」当场说清楚，比让用户收一个 400/415 再回头找强得多；后端 upload 白名单仍是最终边界，这里只是提前拦截。
// 约定：这份白名单必须与后端 upload 允许的集合保持一致，改一边就要改另一边，否则会出现「前端放行、后端 415」的裂缝。
// 坑：文件名先兜底成 '' 再算 lastIndexOf——原写法在 f.name 为 undefined 时会先用 TypeError 崩掉；
//   没有扩展名时 lastIndexOf 返回 -1，被 || 0 兜成 0 而切出整个文件名，必然不在白名单里、被过滤掉，这是想要的降级。
// 坑：path 只是透传字段，浏览器渲染进程拿不到真实磁盘路径；要有值得靠 preload 的 取文件真实路径(File) 去补，缺失时上传仍可走纯 File 直传。
// 坑：目前 frontend/src 里没有任何调用方（桌面端前端零改动约束），实际只有 electron/tests 在消费它——别以为改这里会立刻影响界面。
/** 允许拖拽上传的扩展名（与后端 upload 白名单一致：csv/xlsx/xls 等）。 */
const 允许扩展名 = ['.csv', '.xlsx', '.xls'];
function 提取可上传文件(files) {
  return (files || []).map(f => {
    // 兜底 name 缺失：先取 (f||{}).name 再做 lastIndexOf（review 指出的原写法在 name=undefined 时先抛 TypeError）
    const 文件名 = (f || {}).name || '';
    const 扩展名 = 文件名.slice(文件名.lastIndexOf('.') || 0).toLowerCase();
    return { name: 文件名, path: (f || {}).path || '', 扩展名 };
  }).filter(f => 允许扩展名.includes(f.扩展名));
}

module.exports = { 提取可上传文件, 允许扩展名 };
