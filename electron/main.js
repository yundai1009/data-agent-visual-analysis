// 桌面版（Electron）主进程：进程编排中枢——拉起后端、等它就绪、开窗口、管托盘、承接 desktop:* IPC。
// 做了什么：① 启动时探测空闲端口(8000 起) → spawn 打包好的后端 exe → 轮询 /healthz 直到 200；
//   ② 就绪才开主窗口加载 http://127.0.0.1:<端口>，起不来就弹框并给「打开配置」自救入口；③ 托盘常驻，关窗口只隐藏不退出；
//   ④ IPC 侧只做「读盘 / 落盘 / 开目录 / 重启后端」的编排，配置语义一律委托 核心/ 下的纯函数。
// 为什么把语义拆到 核心/ 目录：main.js 一 require('electron') 就只能在 Electron 运行时里跑，
//   配置校验、是否需重启、托盘菜单、版本比对、env 拼装写在这里一行都测不了；拆成纯 node 模块后 `npm test`（node --test）不开窗口就能覆盖。
// 坑：后端 exe 是打包产物 electron/dist-backend/daa-backend.exe，开发模式（npm start）下不存在，必须先 npm run build:backend。
// 坑：数据根固定 %APPDATA%\数据分析Agent，不用 app.getPath('userData')——后者按应用名生成，与 db/日志目录错位会让读设置读到空对象。
// 坑：close 的 preventDefault 会拦住 app.quit()，before-quit 里必须 destroy() 窗口，否则托盘「退出」只杀后端、进程赖着不退。
// 坑：will-navigate 按 协议+主机+端口 三段精确比对，不用 startsWith——http://127.0.0.1:8000@evil.com 能骗过前缀判断。
const { app, BrowserWindow, ipcMain, shell, dialog, Tray, Menu } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { 探测空闲端口 } = require('./核心/端口探测');
const { 读设置, 写设置 } = require('./核心/设置存取');
const { 构建后端环境 } = require('./核心/后端配置');
const { 解析前端目录, 前端目录来源 } = require('./核心/前端产物');
const { 比对版本 } = require('./核心/版本比对');
const { 设置转表单, 表单转设置, 校验表单, 是否需要重启, 随机强密钥 } = require('./核心/配置模型');

const APP_NAME = '自助式数据分析Agent平台';
const 数据根目录 = () => path.join(app.getPath('appData'), '数据分析Agent');
const 配置文件路径 = () => path.join(数据根目录(), 'settings.json');
const 后端日志路径 = () => path.join(数据根目录(), 'logs', 'backend.log');

let 主窗口 = null;
let 配置窗口 = null;
let 后端进程 = null;
let 托盘 = null;
// 全局保存本次启动端口（will-navigate 校验用）；声明前置避免 TDZ 隐患
let 全局端口 = 8000;

/** 开发模式下没有 PyInstaller 产物时，用系统 Python 直接跑后端源码。
 *  优先 py -3（Windows launcher，装过多版本 Python 时不会串到 Python 2），回落 python。
 *  打包版永远走 daa-backend.exe，不会用到这条路径（用户机器上未必有 Python）。 */
function 后端兜底命令() {
  return ['py', '-3', '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', String(全局端口)];
}

/** 找到打包进 extraResources 的后端可执行文件；开发模式（electron .）下不存在则返回 null，
 *  由调用方决定走 PyInstaller 兜底还是直接报错。 */
function 后端入口() {
  const packaged = path.join(process.resourcesPath, 'backend', 'daa-backend.exe');
  return fs.existsSync(packaged) ? packaged : null;
}

/** 安装包里的前端副本（`backend/_internal/frontend/dist/`）；不存在返回 null。 */
function 前端副本路径() {
  const packaged = path.join(process.resourcesPath, 'backend', '_internal', 'frontend', 'dist');
  return fs.existsSync(packaged) ? packaged : null;
}

/** 用户覆盖层：把新 dist 放进 %APPDATA%\数据分析Agent\frontend\dist 就能换掉安装包里的界面，
 *  不用重新打包（阶段七十五，对应 npm run push:ui 脚本）。 */
function 用户覆盖路径() {
  return path.join(数据根目录(), 'frontend', 'dist');
}

/** 仓库根：打包模式下 main.js 在 app.asar 里（__dirname = .../resources/app.asar），
 *  仓库 dist 不存在；开发模式下 __dirname = <仓库>/electron，仓库根就是上一级。 */
function 仓库根() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..');
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
  // 阶段七十五：前端产物路径显式注入。
  // 在此之前 frontend/dist 靠 extraResources 拷进安装包，每改一行前端都要 npm run dist
  // 重打整个包（PyInstaller + electron-builder 各跑一遍）。现在开发模式直接指向仓库
  // frontend/dist，改完 npm run build 刷新窗口就生效；打包模式仍用 resources 里的副本，
  // 离线分发的自包含性不变。解析规则在 核心/前端产物.js，有单测覆盖。
  const 前端目录 = 解析前端目录(仓库根(), 前端副本路径(), 用户覆盖路径());
  console.log(`前端产物：${前端目录来源(仓库根(), 前端副本路径(), 用户覆盖路径())} → ${前端目录 || '（后端默认）'}`);
  const env = 构建后端环境(process.env, { ...用户设置, 端口: port }, { 前端目录 });
  env.DAA_SQLITE_PATH = path.join(dataDir, 'daa.db');
  const exe = 后端入口();
  const proc = exe
    ? spawn(exe, [], { env, cwd: dataDir, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    // 开发模式（npm start）没有 PyInstaller 产物：直接让系统 Python 跑同一份后端代码。
    // 这条路只为开发存在，打包版始终走 exe（用户机器上未必有 Python）。
    : spawn(后端兜底命令()[0], 后端兜底命令().slice(1), {
      env, cwd: dataDir, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    });
  if (!exe) {
    console.log('未找到 dist-backend/daa-backend.exe，开发模式走系统 Python 跑后端');
  }
  // 日志落 %APPDATA%\数据分析Agent\logs\backend.log
  const logDir = path.join(数据目录, 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  const logStream = fs.createWriteStream(path.join(logDir, 'logs', 'backend.log'), { flags: 'a' });
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

/**
 * 启动后端进程并等待就绪。失败时结束进程并返回 { ok:false, 错误 }（不弹窗、不退出），
 * 由调用方决定是「提示 + 打开配置」还是「把错误回给配置窗口」。
 * 首次启动与「配置保存后重启」共用这一条路径，避免两处逻辑漂移。
 */
async function 启动后端进程(超时Ms = 30000) {
  // 已有进程在跑（重启场景）：先彻底结束再拉新进程，否则端口未释放会绑定失败
  if (后端进程) {
    const 旧进程 = 后端进程;
    后端进程 = null;
    try { 旧进程.kill(); } catch { /* 可能已退出 */ }
    await new Promise((r) => {
      if (旧进程.exitCode !== null) return r();
      const 计时 = setTimeout(r, 5000);
      旧进程.once('exit', () => { clearTimeout(计时); r(); });
    });
  }
  let proc;
  try {
    proc = spawnBackend(全局端口);
  } catch (e) {
    return { ok: false, 错误: e.message };
  }
  后端进程 = proc;
  const ok = await 等后端就绪(全局端口, 超时Ms, proc);
  if (!ok) {
    if (后端进程 === proc) 后端进程 = null;
    try { proc.kill(); } catch { /* 可能已退出 */ }
    return {
      ok: false,
      错误: `后端 ${Math.round(超时Ms / 1000)} 秒内未就绪（常见原因：MySQL 服务未启动、账号或密码错误、端口被占用）`,
    };
  }
  return { ok: true, 错误: '' };
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
  // 关窗口 = 隐藏到托盘（不退出）；退出只走托盘菜单（before-quit 回收后端进程）
  主窗口.on('close', (e) => {
    e.preventDefault();
    主窗口.hide();
  });
  主窗口.on('closed', () => { 主窗口 = null; });
}

/**
 * 桌面版配置窗口（数据库模式 / 认证模式）。
 * 刻意不复用网页版前端：frontend/dist 是网页版与桌面版共用的构建产物，
 * 桌面专属的「改后端配置」界面不能混进去，否则网页版也会多出一个本机专用入口。
 * 因此这里加载 electron/配置页/ 下的本地 file:// 页面，用独立 preload 只暴露配置相关 IPC。
 * 单实例：已打开则前置聚焦。
 */
async function 创建配置窗口() {
  if (配置窗口 && !配置窗口.isDestroyed()) {
    配置窗口.show();
    配置窗口.focus();
    return 配置窗口;
  }
  配置窗口 = new BrowserWindow({
    width: 780, height: 860, minWidth: 660, minHeight: 580,
    icon: path.join(__dirname, 'build', 'logo.ico'),
    title: `${APP_NAME} · 配置`,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '配置页', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  配置窗口.setMenuBarVisibility(false);
  配置窗口.once('ready-to-show', () => { if (配置窗口 && !配置窗口.isDestroyed()) 配置窗口.show(); });
  配置窗口.on('closed', () => { 配置窗口 = null; });
  配置窗口.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  // 本地页面不允许任何导航（含被 iframe/脚本触发的），避免配置窗口变成任意页面宿主
  配置窗口.webContents.on('will-navigate', (e) => e.preventDefault());
  await 配置窗口.loadFile(path.join(__dirname, '配置页', 'index.html'));
  return 配置窗口;
}

/** 建托盘（幂等）。菜单模板由被单测覆盖的 托盘菜单(state) 生成，避免测试与实现漂移。 */
function 建立托盘() {
  if (托盘 && !托盘.isDestroyed()) return 托盘;
  const { 托盘菜单 } = require('./核心/托盘逻辑');
  const 托盘图标路径 = path.join(__dirname, 'build', '托盘图标.png');
  托盘 = new Tray(fs.existsSync(托盘图标路径) ? 托盘图标路径 : path.join(__dirname, '..', 'logo.ico'));
  托盘.setToolTip(APP_NAME);
  托盘.setContextMenu(Menu.buildFromTemplate(
    托盘菜单({ 是否主窗口可见: !!主窗口 && !主窗口.isDestroyed() && 主窗口.isVisible() }).map(项 => {
      if (项.type === 'separator') return { type: 'separator' };
      return {
        label: 项.label,
        click: () => {
          if (项.id === 'show') {
            // 后端起不来时没有主窗口，此时的「唯一界面」是配置窗口——别让菜单项点了没反应
            if (主窗口 && !主窗口.isDestroyed()) {
              if (主窗口.isMinimized()) 主窗口.restore();
              主窗口.show();
              主窗口.focus();
            } else {
              创建配置窗口();
            }
          } else if (项.id === 'config') {
            创建配置窗口();
          } else if (项.id === 'quit') {
            process.env.DAA_TRAY = '1';
            app.quit();
          }
        },
      };
    })
  ));
  托盘.on('double-click', () => { if (主窗口 && !主窗口.isDestroyed()) { 主窗口.show(); 主窗口.focus(); } });
  return 托盘;
}

/**
 * 按磁盘上的最新配置重启后端，并按需建主窗口 / 重新加载页面。供配置窗口调用。
 * @returns {Promise<{ok: boolean, 错误: string}>}
 */
async function 重启后端() {
  const 结果 = await 启动后端进程();
  if (!结果.ok) return 结果;
  if (主窗口 && !主窗口.isDestroyed()) {
    主窗口.loadURL(`http://127.0.0.1:${全局端口}`);
  } else {
    await 创建主窗口();
  }
  return { ok: true, 错误: '' };
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

// ===== 桌面版可视化配置（数据库模式 / 认证模式）=====
// 语义全部落在被单测覆盖的 核心/配置模型.js：这里只负责「读盘 / 落盘 / 开目录 / 重启后端」。
ipcMain.handle('desktop:config-load', () => ({
  表单: 设置转表单(读设置(数据根目录())),
  文件路径: 配置文件路径(),
}));

// 纯校验（不落盘）：供配置页做输入即时提示；保存时再校验一次，主进程是可信边界
ipcMain.handle('desktop:config-validate', (_e, 表单) => 校验表单(表单));

ipcMain.handle('desktop:config-save', (_e, 表单) => {
  const 校验 = 校验表单(表单);
  if (!校验.ok) return { ok: false, 错误: 校验.错误, 需重启: false };
  const 旧 = 读设置(数据根目录());
  // 写设置 合并写并返回合并结果；表单转设置 会对要清理的键给出 null（写设置的删除约定）
  const 新 = 写设置(数据根目录(), 表单转设置(表单));
  return { ok: true, 错误: [], 需重启: 是否需要重启(旧, 新) };
});

ipcMain.handle('desktop:config-gen-secret', () => 随机强密钥());

ipcMain.handle('desktop:config-open-dir', async (_e, 目标) => {
  const 目录 = 目标 === '日志' ? path.join(数据根目录(), 'logs') : 数据根目录();
  fs.mkdirSync(目录, { recursive: true });
  const 失败 = await shell.openPath(目录);
  return 失败 ? { ok: false, 说明: `打开失败：${失败}` } : { ok: true, 说明: `已打开 ${目录}` };
});

ipcMain.handle('desktop:restart-backend', async () => {
  const 结果 = await 重启后端();
  if (结果.ok) {
    // 重启成功：收起配置窗口并把主窗口亮出来
    // （从「启动失败 → 打开配置」进来时本来没有主窗口，重启成功后 重启后端() 已建好）
    if (配置窗口 && !配置窗口.isDestroyed()) 配置窗口.close();
    if (主窗口 && !主窗口.isDestroyed()) {
      if (主窗口.isMinimized()) 主窗口.restore();
      主窗口.show();
      主窗口.focus();
    }
  }
  return 结果;
});

ipcMain.on('desktop:config-close', () => {
  if (配置窗口 && !配置窗口.isDestroyed()) 配置窗口.close();
  // 后端起不来时配置窗口是唯一界面，关掉它就等于应用没有可见界面了——直接退出
  if (!主窗口 || 主窗口.isDestroyed()) app.quit();
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
      const 启动 = await 启动后端进程();
      if (启动.ok) {
        await 创建主窗口();
      } else {
        // 后端起不来的头号原因是配置问题（MySQL 没启动 / 账号密码错 / 端口占用）。
        // 旧版这里直接 quit，用户只能自己去 %APPDATA% 手改 settings.json——
        // 现在给「打开配置」这条自救路径：改回 SQLite + 演示模式就能先跑起来。
        const 选择 = dialog.showMessageBoxSync({
          type: 'error',
          title: APP_NAME,
          message: '后端启动失败，桌面界面无法加载。',
          detail: `${启动.错误}\n\n可在「配置」中改回 SQLite + 演示模式先启动，或修正 MySQL 连接信息后重试。\n日志：${后端日志路径()}`,
          buttons: ['打开配置', '退出'],
          defaultId: 0,
          cancelId: 1,
          noLink: true,
        });
        if (选择 === 0) {
          await 创建配置窗口();
        } else {
          app.quit();
          return;
        }
      }
      // ===== 托盘常驻（Task 3）=====
      建立托盘();
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
  if (配置窗口 && !配置窗口.isDestroyed()) 配置窗口.destroy();
  if (后端进程) { 后端进程.kill(); 后端进程 = null; }
});
app.on('window-all-closed', () => {
  // 托盘常驻：窗口全关不退出；退出只走托盘菜单（before-quit 回收后端进程）
});