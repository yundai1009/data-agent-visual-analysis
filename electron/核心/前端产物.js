// 桌面版前端产物定位（纯函数，不依赖 electron，可直接 node --test）。
// 背景（阶段七十五）：用户抱怨「每一次更新桌面版都需要重新打包太麻烦了」。
// 根因不是打包慢，而是前端产物 frontend/dist 被 extraResources 拷进安装包，
// 于是每改一行前端都要重打整个包（PyInstaller + electron-builder 各跑一遍）。
// 本文件把「用哪个 dist」收敛成一条四级规则，顺序即优先级：
//   1. 用户覆盖层 %APPDATA%\数据分析Agent\frontend\dist —— 装了正式版之后想换界面，
//      把新 dist 拷进这个目录重启即可，**不用重新打包**（npm run push:ui 一条命令）；
//   2. 安装包里的副本 resources/backend/_internal/frontend/dist —— 离线分发自包含性；
//   3. 仓库里的 frontend/dist —— 开发模式（electron .）用，npm run build 后即生效；
//   4. 都没有 → null，让后端用它自己的默认值（不注入 FRONTEND_DIST）。
// 为什么第 4 条是 null 而不是返回一个猜的路径：塞一个不存在的路径会让静态托管
// 静默 404，页面白屏但没有任何报错，这种问题最难查。
// 为什么必须显式区分（不能"有就用"）：开发机上装过旧安装包时，若 resources 副本
// 抢在仓库 dist 前面，就会读到陈旧产物，"改了 dist 却没变化"极难自查。
const path = require('node:path');

const fs = require('node:fs');

/** 目录里是否有 index.html —— 判定"这个 dist 真的能用"，而不是"路径存在"。 */
function 是可用产物(目录) {
  if (!目录) return false;
  try {
    return fs.statSync(path.join(目录, 'index.html')).isFile();
  } catch {
    return false;
  }
}

/**
 * @param {string} 仓库根 主仓库根目录（含 frontend/dist）
 * @param {string|null} 打包副本 安装包里的前端副本
 * @param {string|null} [用户覆盖] %APPDATA%\数据分析Agent\frontend\dist（可选，优先级最高）
 * @returns {string|null} 应该交给后端的 FRONTEND_DIST 绝对路径；都不可用返回 null
 */
function 解析前端目录(仓库根, 打包副本, 用户覆盖 = null) {
  if (是可用产物(用户覆盖)) return path.resolve(用户覆盖);
  if (是可用产物(打包副本)) return path.resolve(打包副本);
  const 仓库产物 = path.resolve(path.join(仓库根, 'frontend', 'dist'));
  return 是可用产物(仓库产物) ? 仓库产物 : null;
}

/** 产出来源标签，用于启动日志里写清"这次用的是哪一份前端"，排障时一眼看懂。 */
function 前端目录来源(仓库根, 打包副本, 用户覆盖 = null) {
  if (是可用产物(用户覆盖)) return '用户覆盖层';
  if (是可用产物(打包副本)) return '安装包副本';
  const 仓库产物 = path.resolve(path.join(仓库根, 'frontend', 'dist'));
  if (是可用产物(仓库产物)) return '仓库构建产物';
  return '无（回落后端默认值）';
}

module.exports = { 解析前端目录, 是可用产物, 前端目录来源 };
