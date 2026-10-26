#!/usr/bin/env node
// electron/脚本/重启桌面版.js —— 一条命令换掉**已安装**桌面版的界面（阶段七十五）。
//
// 为什么需要它：用户抱怨「每一次更新桌面版都需要重新打包太麻烦了」。
// 根因是 frontend/dist 被 extraResources 拷进安装包，于是每改一行前端都要
// 重跑 PyInstaller + electron-builder。现在：
//   1) 桌面版启动时优先读「用户覆盖层」%APPDATA%\数据分析Agent\frontend\dist；
//   2) 本脚本把仓库里刚 build 好的 dist 推到那一层；
//   3) 关掉正在跑的桌面版再重开 —— 新界面立刻生效，全程不打包。
// 后端代码有改动时仍然需要 npm run dist（Python 打不进覆盖层），前端不用。
//
// 用法（在 electron/ 目录下）：
//   node 脚本/重启桌面版.js                 # build + push + 重启，一步
//   node 脚本/重启桌面版.js --no-build      # 只推已有 dist 并重启（已 build 过）
//   node 脚本/重启桌面版.js --push-only     # 只推，不重启（桌面版正开着且你不想关）
//
// 坑：不要用 taskkill /IM electron.exe —— 那会连带杀掉 VS Code 等所有 Electron 应用。
// 这里按命令行里是否带本项目的 main.js 路径精确匹配，只杀自家进程。
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync, spawn } = require('node:child_process');

const 仓库根 = path.resolve(__dirname, '..', '..');
const 前端目录 = path.join(仓库根, 'frontend');
const electron目录 = path.resolve(__dirname, '..');

const 参数 = new Set(process.argv.slice(2));

function 跑(命令, 参数列表, cwd) {
  const 结果 = spawnSync(命令, 参数列表, { encoding: 'utf-8', cwd, stdio: 'inherit', shell: 参数列表.length > 0 && process.platform === 'win32' });
  return 结果;
}

function 跑npm(脚本名, cwd) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const 结果 = spawnSync(npm, ['run', 脚本名], { encoding: 'utf-8', cwd, stdio: 'inherit' });
  if (结果.status !== 0) {
    console.error(`[失败] npm run ${脚本名} 退出码 ${结果.status}`);
    process.exit(结果.status || 1);
  }
}

function 找桌面版进程() {
  if (process.platform !== 'win32') return [];
  const ps = spawnSync('powershell.exe', [
    '-NoProfile', '-Command',
    "Get-CimInstance Win32_Process -Filter \"Name='electron.exe'\" | Where-Object { $_.CommandLine -like '*daa-desktop*' -or $_.CommandLine -like '*electron\\main.js*' } | Select-Object -ExpandProperty ProcessId",
  ], { encoding: 'utf-8' });
  const ids = String(ps.stdout || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => /^\d+$/.test(s));
  return ids;
}

function 关掉桌面版() {
  const ids = 找桌面版进程();
  if (ids.length === 0) {
    console.log('桌面版当前没有在运行，直接启动。');
    return;
  }
  console.log(`关闭正在运行的桌面版（PID ${ids.join(', ')}）…`);
  const ps = spawnSync('powershell.exe', [
    '-NoProfile', '-Command',
    `Stop-Process -Id ${ids.join(',')} -Force`,
  ], { encoding: 'utf-8' });
  if (ps.status !== 0) {
    console.error('[警告] 关不掉旧进程，新窗口照样能开，但旧窗口可能还在。');
  }
  // 等它把端口和后端子进程放出来，否则新实例可能抢不到端口
  const 开始 = Date.now();
  while (Date.now() - 开始 < 5000) {
    if (找桌面版进程().length === 0) return;
    spawnSync('powershell.exe', ['-NoProfile', '-Command', 'Start-Sleep -Milliseconds 300'], { encoding: 'utf-8' });
  }
}

function 起桌面版() {
  // 开发模式（electron .）走仓库 dist，不要求 dist-backend 存在（main.js 会用系统 Python 兜底）
  const 子进程 = spawn(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['electron', '.'], {
    cwd: electron目录,
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  });
  子进程.unref();
}

function 主() {
  console.log('== 1/3 构建前端 ==');
  if (参数.has('--no-build') || 参数.has('--push-only')) {
    console.log('（跳过构建）');
  } else {
    跑npm('build', 前端目录);
  }

  console.log('== 2/3 推送到用户覆盖层 ==');
  const 推送 = spawnSync(process.execPath, [path.join(electron目录, '脚本', '推送前端.js')], {
    encoding: 'utf-8', stdio: 'inherit',
  });
  if (推送.status !== 0) {
    console.error('[失败] 推送前端失败，桌面版不会重启。');
    process.exit(推送.status || 1);
  }

  if (参数.has('--push-only')) {
    console.log('[完成] 已推送。桌面版还在运行的话，重启它即可生效。');
    return;
  }

  console.log('== 3/3 重启桌面版 ==');
  关掉桌面版();
  起桌面版();
  console.log('[完成] 桌面版已用新前端启动。');
}

主();
