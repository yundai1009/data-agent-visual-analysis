// settings.json 的唯一读写入口：读（容错）与写（原子合并 + null 删除），别处不要直接碰 fs。
// 做了什么：读设置(目录) 读 <目录>/settings.json，文件不存在或 JSON 损坏一律返回 {} 而不抛；
//   写设置(目录, 补丁) 合并旧值后删掉所有值为 null 的键，先写 settings.json.tmp 再 rename 覆盖，返回合并后的结果。
// 为什么用「临时文件 + rename」而不是直接 writeFileSync：直接写在进程被强杀/断电时可能留下半截 JSON，
//   下次启动 读设置 只能返回 {}，表现为「配置莫名全部丢失」且无从排查；同一卷上的 rename 是原子替换，能杜绝半截文件。
// 为什么读失败时静默返回 {} 而不是抛：配置读不出来不该让整个桌面版起不来（sqlite 演示模式仍可跑）；
//   代价是「配置坏了」与「从没配过」在调用方眼里一样，所以 main.js 把 配置文件路径 一并回给配置窗口，让用户能自己去 %APPDATA%\数据分析Agent 看一眼。
// 坑：必须先剥 UTF-8 BOM 再 JSON.parse——Windows 记事本 / PowerShell 写出的 JSON 常带 BOM，不剥会抛在 parse 上被 catch 吃掉、配置静默全部失效。
// 坑：「值为 null = 删除该键」是与 配置模型.js 的 表单转设置 之间的口头契约，两边都没有类型约束兜底，改一处必须同步另一处。
// 坑：同步 fs 调用且无写锁——只在主进程单线程的 IPC 处理里调用，不存在并发写；但配置窗口与主窗口同时保存仍靠 Electron 的 IPC 串行化兜着。
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
 * 约定：值为 null 的键 = 删除该键——合并写入无法用「不传这个键」表达删除，
 * 例如从 MySQL/真实认证切回 SQLite/演示模式时要把凭据字段从文件里清掉。
 * @param {string} 目录 userData 目录
 * @param {object} partial 要合并的字段（值为 null 表示删除）
 */
function 写设置(目录, partial) {
  const file = path.join(目录, 'settings.json');
  const next = { ...读设置(目录), ...partial };
  for (const k of Object.keys(next)) {
    if (next[k] === null) delete next[k];
  }
  fs.mkdirSync(目录, { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2), 'utf-8');
  fs.renameSync(tmp, file);
  return next;
}

module.exports = { 读设置, 写设置 };