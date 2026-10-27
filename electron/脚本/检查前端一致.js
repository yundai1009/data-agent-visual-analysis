#!/usr/bin/env node
// electron/脚本/检查前端一致.js
// 打包前自检：确认「装进安装包里的那份前端」和「仓库刚构建出来的前端」是同一份。
//
// 背景（阶段八十）：桌面版出现「打开还是旧版」，排查下来是三层前端副本里有一层悄悄陈旧：
//   1. 用户覆盖层 %APPDATA%\数据分析Agent\frontend\dist   ← npm run push:ui 更新
//   2. 安装包副本 resources/backend/_internal/frontend/dist ← 由 dist-backend/ 拷来
//   3. dist-backend/_internal/frontend/dist                ← 由 build-backend/daa-backend.spec 收集 frontend/dist
//
// 坑（这次真踩到）：只改前端时如果跳过 `npm run build:backend` 直接跑 `npx electron-builder`，
// PyInstaller 产物 dist-backend 里那份前端还是上一次的，electron-builder 会把它原样搬进安装包 ——
// 于是「代码是新的、装出来是旧的」，而且 win-unpacked 的 exe 时间戳是新的，看起来完全正常。
// 更坏的是 extraResources 里两条规则都指向 backend/_internal/frontend/dist，谁最后写赢不靠读代码能确定。
//
// 所以：让工具在打包前把两边的 index.html 哈希比一下，不一致就直接失败，
// 不靠人记住「改前端也要重建后端」这条隐性规则。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const 仓库根 = path.resolve(__dirname, '..', '..');
const 源 = path.join(仓库根, 'frontend', 'dist', 'index.html');
const 打包副本 = path.join(__dirname, '..', 'dist-backend', '_internal', 'frontend', 'dist', 'index.html');

function 哈希(文件) {
  return crypto.createHash('sha256').update(fs.readFileSync(文件)).digest('hex');
}

function 取入口引用的包(文件) {
  // 只比 index.html 里引用的入口 chunk 名，比整文件哈希更能说清「差在哪」
  const 文本 = fs.readFileSync(文件, 'utf8');
  const 命中 = 文本.match(/assets\/(index-[A-Za-z0-9_-]+\.js)/);
  return 命中 ? 命中[1] : '(未找到 index-*.js)';
}

function 主() {
  if (!fs.existsSync(源)) {
    console.error(`[失败] 前端未构建：${源} 不存在`);
    console.error('       先跑：cd frontend && npm run build');
    process.exitCode = 1;
    return;
  }
  if (!fs.existsSync(打包副本)) {
    console.error(`[失败] 后端产物里没有前端副本：${打包副本} 不存在`);
    console.error('       先跑：npm run build:backend（spec 会把 frontend/dist 收进去）');
    process.exitCode = 1;
    return;
  }

  const 源入口 = 取入口引用的包(源);
  const 副入口 = 取入口引用的包(打包副本);

  if (哈希(源) === 哈希(打包副本)) {
    console.log(`[通过] 打包副本与仓库前端一致（入口 ${源入口}）`);
    return;
  }

  console.error('[失败] 打包副本里的前端是旧的，现在打包会把旧界面发给用户');
  console.error(`       仓库 frontend/dist   入口：${源入口}`);
  console.error(`       dist-backend 内置副本 入口：${副入口}`);
  console.error('       修法：npm run build:backend 之后重新跑 electron-builder');
  console.error('       （或直接用 npm run dist —— 它本来就先 build:backend 再打包）');
  process.exitCode = 1;
}

主();
