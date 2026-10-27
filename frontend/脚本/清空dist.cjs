#!/usr/bin/env node
// frontend/脚本/清空dist.cjs
// 构建前把 dist 整目录删掉，不依赖 Vite 的 emptyOutDir。
//
// 背景（阶段八十一）：`vite.config.js` 里明明写了 `build.emptyOutDir: true`，
// 但实测不生效——在 dist/assets 里种一个 STALE-probe.js 再 `npm run build`，
// 文件原地不动、构建产物从 42 个变成 43 个；连跑两次、种一次残留，三次都是
// 「什么在里面就留什么，新的往旁边加」。
//
// 根源不是配置没写对：Vite 的 emptyDir 内部逐项调 `fs.rmSync`，而 `fs.rmSync`
// 在**路径含非 ASCII 字符**时会静默不删、不抛异常（node v24.9.0 / win32 实测）。
// 本仓库根目录叫「自助式数据分析Agent平台」，所以 emptyOutDir 在这里必然失效。
// 后果不是体积问题，而是**旧 chunk 会被原样推进桌面版覆盖层、被打进安装包**，
// 于是「明明改了，看到的还是旧的」反复复发——阶段八十就是被它坑的。
//
// 为什么不继续调 Vite 配置：emptyOutDir 的行为取决于 Vite 内部实现，升级一次
// 就可能变；"删掉再构建"是构建系统里唯一不随版本漂移的语义。
// 为什么不写成 `rm -rf dist && vite build`：Windows 上没有 rm -rf，npm scripts
// 里跨平台写删除命令最终会变成一串转义。
// 为什么复用 ../electron/核心/删目录.js：它先试 rmSync、再用手写递归
// （readdir+unlink+rmdir，实测在中文路径下有效）兜底，并以 existsSync 作为
// 唯一真相——不信任何 API 的"成功返回"。
const path = require('node:path');
const fs = require('node:fs');
const { 删目录 } = require(path.resolve(__dirname, '..', '..', 'electron', '核心', '删目录'));

const 前端根 = path.resolve(__dirname, '..');
const dist = path.join(前端根, 'dist');

/** 删掉 dist 目录（不存在就当作已完成）。导出供单测调用。 */
function 清空dist(目录 = dist) {
  return 删目录(目录);
}

module.exports = { 清空dist, dist };

if (require.main === module) {
  const 前 = fs.existsSync(dist);
  const 成了 = 清空dist();
  console.log(成了
    ? `[清空] ${前 ? '已删除旧 dist' : 'dist 本来就不存在'}：${dist}`
    : `[失败] 删不掉：${dist}`);
  process.exitCode = 成了 ? 0 : 1;
}
