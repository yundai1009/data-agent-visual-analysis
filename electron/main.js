// electron/main.js
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { 探测空闲端口 } = require('./核心/端口探测');
const { 读设置, 写设置 } = require('./核心/设置存取');
const { 构建后端环境 } = require('./核心/后端配置');
const { 比对版本 } = require('./核心/版本比对');

const APP_NAME = '自助式数据分析Agent平台';
const 数据根目录 = () => path.join(app.getPath('appData'), '数据分析Agent');

let 主窗口 = null;
let 后端进程 = null;
let 托盘 = null;
// 全局保存本次启动端口（will-navigate 校验用）；声明前置避免 TDZ 隐患
let 全局端口 = 8000;

/** 找到打包进 extraResources 的后端可执行文件；开发模式（electron .）下不存在则抛错提示先打包。 */
function 后端入口() {
  const packaged = path.join(process.resourcesPath, 'backend', 'daa-backend.exe');
  return fs.existsSync(packaged) ? packaged : null;
}

function spawnBackend(port) {
  const 数据目录 = 数据根目录();
  const dataDir = path.join(数据目录, 'data');
  fs.mkdirSync(dataDir, { recursive: true });
  // 用户设置可把后端切到 MySQL（与网页版同库，账号数据同步）+ 真实认证；
  // 默认零配置：sqlite 本地库 + 演示模式（env 由 核心/后端配置.js 生成，有单测覆盖）
  // 注意：设置/数据/日志统一放 数据根目录()（= %APPDATA%\数据分析Agent），不用 app.getPath('userData')
  // —— 后者按应用名自动生成 %APPDATA%\自助式数据分析Agent平台，与 db/日志目录不一致会导致配置读空。
  const 用户设置 = 读设置(数据目录);
  const env = 构建后端环境(process.env, { ...用户设置, 端口: port });
  env.DAA_SQLITE_PATH = path.join(dataDir, 'daa.db');
  const exe = 后端入口();
  if (!exe) {
    throw new Error('未找到后端可执行文件，请先执行 npm run build:backend');
  }
  const proc = spawn(exe, [], {
    env,
    cwd: dataDir,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  // 日志落 %APPDATA%\数据分析Agent\logs\backend.log
  const logDir = path.join(数据目录, 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  const logStream = fs.createWriteStream(path.join(logDir, 'backend.log'), { flags: 'a' });
  proc.stdout.pipe(logStream);
  proc.stderr.pipe(logStream);
  proc.on('exit', (code) => {
    if (后端进程 === proc) 后端进程 = null;
    console.log(`后端进程退出 code=${code}`);
  });
  return proc;
}

async function 等后端就绪(port, 超时Ms = 30000, proc = null) {
  const { execFile } = require('node:child_process');
  const 开始 = Date.now();
  while (Date.now() - 开始 < 超时Ms) {
    // 后端进程已退出（启动即崩）→ 立即失败，不空等满 30s
    if (proc && proc.exitCode !== null) return false;
    try {
      const { data } = await new Promise((resolve, reject) => {
        execFile('curl.exe', ['-s', '-o', 'NUL', '-w', '%{http_code}', `http://127.0.0.1:${port}/healthz`],
          (err, stdout) => err ? reject(err) : resolve({ data: stdout }));
      });
      if (data === '200') return true;
    } catch { /* 未就绪，继续轮询 */ }
    await new Promise(r => setTimeout(r, 300));
  }
  return false;
}

async function 创建主窗口() {
  主窗口 = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1024, minHeight: 700,
    icon: path.join(__dirname, 'build', 'logo.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  主窗口.setMenuBarVisibility(false);
  // 外链交系统浏览器，应用窗口不导航走
  主窗口.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  主窗口.webContents.on('will-navigate', (e, url) => {
    // 精确校验协议+主机+端口，避免 startsWith 前缀绕过（如 http://127.0.0.1:8000@evil.com）
    try {
      const u = new URL(url);
      if (!(u.protocol === 'http:' && u.hostname === '127.0.0.1' && u.port === String(全局端口))) {
        e.preventDefault();
      }
    } catch {
      e.preventDefault();
    }
  });
  const 设置 = 读设置(数据根目录());
  if (设置.窗口最大化) 主窗口.maximize();
  主窗口.loadURL(`http://127.0.0.1:${全局端口}`);
}

// IPC：拖拽取真实路径（webUtils 只能在主进程用）
const { webUtils } = require('electron');
ipcMain.handle('desktop:get-file-path', (event, file) => {
  try { return webUtils.getPathForFile(file); } catch { return ''; }
});
ipcMain.handle('desktop:get-version', () => app.getVersion());
// 更新检查仓库（一期占位）：用户已决定用「专用更新仓库」（非主仓库）承载 Releases，
// 但该仓库尚未创建——此处暂指向主仓库占位，创建后改为专用仓库地址（见 docs 后续计划）。
const 更新仓库 = 'yundai1009/data-agent-visual-analysis';
ipcMain.handle('desktop:check-update', async () => {
  // 一期：GitHub Releases API（比对最新 tag 与本版，仅提示不自动下载；二期接自动安装）
  try {
    const 响应 = await fetch(`https://api.github.com/repos/${更新仓库}/releases/latest`);
    if (!响应.ok) return { 状态: '未知' };
    const 发布 = await 响应.json();
    const 结论 = 比对版本(app.getVersion(), 发布.tag_name.replace(/^v/i, ''));
    return { 状态: 结论, 最新版本: 发布.tag_name, 下载页: 发布.html_url };
  } catch {
    return { 状态: '未知' };
  }
});

// 单实例锁
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    // 托盘常驻后窗口常态是「隐藏」而非「最小化」，只 focus() 唤不回——
    // 必须 show()（并对最小化窗口先 restore），与托盘「显示主窗口」逻辑对齐
    if (主窗口 && !主窗口.isDestroyed()) { if (主窗口.isMinimized()) 主窗口.restore(); 主窗口.show(); 主窗口.focus(); }
  });

  app.whenReady().then(async () => {
    try {
      全局端口 = await 探测空闲端口(8000);
      后端进程 = spawnBackend(全局端口);
      const ok = await 等后端就绪(全局端口, 30000, 后端进程);
      if (!ok) {
        dialog.showErrorBox(`${APP_NAME}`, '后端启动超时，请查看日志：%APPDATA%\\数据分析Agent\\logs\\backend.log');
        app.quit();
        return;
      }
      await 创建主窗口();
      // ===== 托盘常驻（Task 3）=====
      const { Tray, Menu } = require('electron');
      const { 托盘菜单 } = require('./核心/托盘逻辑');
      const 托盘图标路径 = path.join(__dirname, 'build', '托盘图标.png');
      托盘 = new Tray(fs.existsSync(托盘图标路径) ? 托盘图标路径 : path.join(__dirname, '..', 'logo.ico'));
      托盘.setToolTip(APP_NAME);
      // 真实菜单由被单测覆盖的 托盘菜单(state) 生成，避免测试与实现漂移
      托盘.setContextMenu(Menu.buildFromTemplate(
        托盘菜单({ 是否主窗口可见: !!主窗口 && 主窗口.isVisible() }).map(项 => {
          if (项.type === 'separator') return { type: 'separator' };
          return {
            label: 项.label,
            click: () => {
              if (项.id === 'show') {
                if (主窗口 && !主窗口.isDestroyed()) { if (主窗口.isMinimized()) 主窗口.restore(); 主窗口.show(); 主窗口.focus(); }
              } else if (项.id === 'quit') {
                process.env.DAA_TRAY = '1';
                app.quit();
              }
            },
          };
        })
      ));
      托盘.on('double-click', () => { if (主窗口 && !主窗口.isDestroyed()) { 主窗口.show(); 主窗口.focus(); } });
      // 关窗口 = 隐藏到托盘（不退出）；退出只走托盘菜单（before-quit 回收后端进程）
      主窗口.on('close', (e) => {
        e.preventDefault();
        主窗口.hide();
      });
    } catch (e) {
      dialog.showErrorBox(`${APP_NAME}`, `启动失败：${e.message}`);
      app.quit();
    }
  });
}

app.on('before-quit', () => {
  // 退出回收（Task 3）：先放行窗口关闭。close 的 preventDefault 会拦截 app.quit()，
  // 不 destroy 的话托盘「退出」会杀掉后端却不退出（harness 已复现），故此处 destroy。
  if (主窗口 && !主窗口.isDestroyed()) 主窗口.destroy();
  if (后端进程) { 后端进程.kill(); 后端进程 = null; }
});
app.on('window-all-closed', () => {
  // 托盘常驻：窗口全关不退出；退出只走托盘菜单（before-quit 回收后端进程）
});