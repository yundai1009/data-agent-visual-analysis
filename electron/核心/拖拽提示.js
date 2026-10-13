// electron/核心/拖拽提示.js
/** 允许拖拽上传的扩展名（与后端 upload 白名单一致：csv/xlsx/xls 等）。 */
const 允许扩展名 = ['.csv', '.xlsx', '.xls'];

/**
 * 从拖拽 File 列表返回可上传文件信息。
 * @param {Array<{name: string, path?: string}>} files
 * @returns {Array<{name: string, path: string, 扩展名: string}>} 可上传项；不可识别项忽略
 */
function 提取可上传文件(files) {
  return (files || []).map(f => {
    // 兜底 name 缺失：先取 (f||{}).name 再做 lastIndexOf（review 指出的原写法在 name=undefined 时先抛 TypeError）
    const 文件名 = (f || {}).name || '';
    const 扩展名 = 文件名.slice(文件名.lastIndexOf('.') || 0).toLowerCase();
    return { name: 文件名, path: (f || {}).path || '', 扩展名 };
  }).filter(f => 允许扩展名.includes(f.扩展名));
}

module.exports = { 提取可上传文件, 允许扩展名 };
