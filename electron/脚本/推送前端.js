#!/usr/bin/env node
// electron/脚本/推送前端.js
// 把仓库里刚构建好的前端产物推到「用户覆盖层」，让**已安装**的桌面版换界面时不用重新打包。
//
// 背景（阶段七十五）：用户抱怨「每一次更新桌面版都需要重新打包太麻烦了」。
// 根因不是打包慢，而是两件事被捆在了一次 `npm run dist` 里：
//   1) 前端产物 frontend/dist 被 extraResources 拷进安装包 → 每改一行前端都要重打整个包；
//   2) 后端是 PyInstaller 产物 → 没有"先跑起来看看"的开发路径。
// 现在桌面版启动时按四级优先级找前端（核心/前端产物.js，有单测覆盖）：
//   1. 用户覆盖层 %APPDATA%\数据分析Agent\frontend\dist
//   2. 安装包副本  resources/backend/_internal/frontend/dist
//   3. 仓库 frontend/dist
//   4. 都不可用 → 不注入 FRONTEND_DIST，让后端用它自己的默认值
// 所以日常改前端只需要：`cd frontend && npm run build` → `cd ../electron && npm run push:ui` → 重启桌面版。
//
// 用法：
//   npm run refresh:ui                        # 构建 + 推送（一步）
//   npm run push:ui                           # 只推已构建的 dist
//   npm run push:ui -- --dir "D:\\某目录"      # 推到别处（比如给同事一份）
//   npm run push:ui -- --from "D:\\另一份dist" # 推别处构建的产物
//
// 安全：
//   - 只动 目标目录（%APPDATA%\数据分析Agent\frontend\dist），绝不碰 data/（用户数据库在那里）；
//   - 源目录没有 index.html 就直接失败退出码 1，绝不推半成品上去——推坏了桌面版会白屏，
//     而且很难看出是"推的这份有问题"而不是"程序坏了"。
//
// 坑（写在这里防止有人"顺手简化"）：**不用 fs.cpSync**。Node 24 上 cpSync 拷这个 dist 会
// 直接让进程静默崩掉（退出码 -1073740791 / 0xC0000409 STATUS_STACK_BUFFER_OVERRUN，
// 不抛异常、没有 stderr），改成手写递归 copyFileSync 后 52 个文件全部正常。
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function 参数(名) {
  const i = process.argv.indexOf(名);
  return i >= 0 ? process.argv[i + 1] : null;
}

function 数文件(目录) {
  return fs.readdirSync(目录, { withFileTypes: true })
    .reduce((n, e) => n + (e.isDirectory() ? 数文件(path.join(目录, e.name)) : 1), 0);
}

/** 递归复制（刻意不用 fs.cpSync：见文件头"坑"）。 */
function 复制树(源, 目标) {
  fs.mkdirSync(目标, { recursive: true });
  for (const 条目 of fs.readdirSync(源, { withFileTypes: true })) {
    const 来自 = path.join(源, 条目.name);
    const 去 = path.join(目标, 条目.name);
    if (条目.isDirectory()) 复制树(来自, 去);
    else fs.copyFileSync(来自, 去);
  }
}

function 主() {
  const 仓库根 = path.resolve(__dirname, '..', '..');
  const 源 = path.resolve(参数('--from') || path.join(仓库根, 'frontend', 'dist'));
  const 目标 = path.resolve(
    参数('--dir') || path.join(
      process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'),
      '数据分析Agent', 'frontend', 'dist',
    ),
  );

  if (!fs.existsSync(path.join(源, 'index.html'))) {
    console.error(`[失败] 源目录里没有 index.html：${源}`);
    console.error('       先构建：cd frontend && npm run build');
    process.exitCode = 1;
    return;
  }

  console.log(`源  ：${源}`);
  console.log(`目标：${目标}`);

  // 覆盖而不是合并：旧构建残留的 hash 文件名不会被任何 index.html 引用，
  // 留着只会让目录越来越胖（本仓库曾在 dist/assets 堆过 6 份历史 EChartsChart-*.js）。
  // 用 核心/删目录.js 而不是直接 fs.rmSync：目标路径 %APPDATA%\数据分析Agent\... 含中文，
  // 而 rmSync 在非 ASCII 路径上会静默不删（阶段八十一实测，node v24.9.0/win32）。
  const { 删目录 } = require('../核心/删目录');
  if (!删目录(目标)) {
    console.error(`[失败] 删不掉旧覆盖层，中止：${目标}`);
    console.error('       不删就复制会留下旧 hash chunk，桌面版可能继续加载旧界面。');
    process.exitCode = 1;
    return;
  }
  复制树(源, 目标);

  const 有入口 = fs.existsSync(path.join(目标, 'index.html'));
  console.log(`[完成] 已推送 ${数文件(目标)} 个文件，index.html ${有入口 ? '就位' : '缺失（异常）'}`);
  console.log('       重启桌面版（或托盘 → 重启后端）即可生效。');
  if (!有入口) process.exitCode = 1;
}

主();
