// electron/核心/设置存取.js
const fs = require('node:fs');
const path = require('node:path');

/**
 * 读 userData/settings.json；不存在/损坏返回 {}。
 * @param {string} 目录 userData 目录
 */
function 读设置(目录) {
  const file = path.join(目录, 'settings.json');
  try {
    // 去 UTF-8 BOM 再解析：Windows PowerShell/记事本写出的 JSON 常带 BOM，
    // 直接 JSON.parse 会抛而被 catch 静默返回 {}（配置全部失效，难排查）
    const raw = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

/**
 * 合并写入 userData/settings.json（原子写：先写临时文件再 rename）。
 * @param {string} 目录 userData 目录
 * @param {object} partial 要合并的字段
 */
function 写设置(目录, partial) {
  const file = path.join(目录, 'settings.json');
  const next = { ...读设置(目录), ...partial };
  fs.mkdirSync(目录, { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2), 'utf-8');
  fs.renameSync(tmp, file);
  return next;
}

module.exports = { 读设置, 写设置 };