// 稳妥地删掉一个目录（包括路径里带中文的情况）。
//
// 坑（Node v24.9.0 / Windows，本机实测复现，见阶段八十一开发日志）：
//   `fs.rmSync(路径, { recursive: true, force: true })` 在**路径含非 ASCII 字符**时不可靠：
//     ① 有时静默变成 no-op —— 既不删除、也不抛异常，返回值也看不出异常；
//     ② 有时直接把整个进程打死 —— 退出码 **-1073740791 / 0xC0000409
//        STATUS_STACK_BUFFER_OVERRUN**，不抛异常、没有 stderr、连 console.log 都来不及刷。
//   ② 比 ① 更危险：try/catch 抓不住进程级 abort，任何"先删后拷"的脚本会
//   在删的那一步无声退出，调用方只看到"脚本没跑完"。
//   同一条路径下 `fs.unlinkSync` / `fs.rmdirSync` / `fs.readdirSync` 单步调用完全正常，
//   异步的 `fs.promises.rm` 也正常 —— 坏的是 rmSync 这一个入口，不是文件锁、
//   不是权限、不是 Defender 扫描（这些都验证过、都排除了）。
//
//   这个坑在本仓库不是理论风险：仓库根目录叫「自助式数据分析Agent平台」，
//   桌面版前端覆盖层是 %APPDATA%\数据分析Agent\frontend\dist —— 两条生产路径都含中文。
//   后果是"先删再拷"实际只做了"拷"：旧 hash chunk 永远留着，覆盖层越堆越胖
//   （阶段八十就是手工把 82 个文件删到 42 个才把"打开还是旧版"压下去的）。
//
// 因此本模块的顺序是「先手写递归，ASCII 路径才走 rmSync 快路径」：
//   非 ASCII 路径上 rmSync 连试都不许试 —— 它不是"可能失败"，而是可能崩进程。
//
// 为什么不用 fs.promises.rm 一把梭：本模块的调用方（推送前端.js、清空dist.cjs）都是
//   同步流程，改成 async 会把"构建脚本里到底删没删掉"变成时序问题；而手写递归
//   （readdir + unlink + rmdir）已实测在中文路径下有效，且是同步的。
const fs = require('node:fs');
const path = require('node:path');

/** 路径里是否有非 ASCII 字符（中文、emoji、全角标点等）。 */
function 含非ASCII(路径) {
  return /[^\x00-\x7F]/.test(路径);
}

/**
 * 删掉目录（递归）。已不存在视为成功。
 * @param {string} 目标 绝对或相对路径
 * @returns {boolean} 删完后是否确实不存在
 */
function 删目录(目标) {
  if (!fs.existsSync(目标)) return true;

  // ASCII 路径：一步搞定的快路径（也是"只读属性"等边角情况的正确处理者）
  if (!含非ASCII(path.resolve(目标))) {
    try {
      fs.rmSync(目标, { recursive: true, force: true });
    } catch {
      // 吞掉：真正的判据是下面的 existsSync，而不是这里抛不抛
    }
    if (!fs.existsSync(目标)) return true;
  }

  // 非 ASCII 路径（以及快路径没删掉的）：手写递归。
  // 实测 readdir/unlink/rmdir 单步在中文路径下都正常，只有 rmSync 会出事。
  手写递归删除(目标);
  return !fs.existsSync(目标);
}

/** 手写递归删除：readdir → 子目录递归 / 文件 unlink → 最后 rmdir 自己。 */
function 手写递归删除(目标) {
  for (const 条目 of fs.readdirSync(目标, { withFileTypes: true })) {
    const 子 = path.join(目标, 条目.name);
    if (条目.isDirectory()) {
      手写递归删除(子);
      continue;
    }
    try {
      fs.unlinkSync(子);
    } catch (错误) {
      // 只读文件（打包/杀软留下的）先去掉只读位再删一次；再失败就往上抛，
      // 让调用方拿到真实的"删不掉"，而不是一个假的成功。
      if (错误 && (错误.code === 'EPERM' || 错误.code === 'EACCES')) {
        try {
          fs.chmodSync(子, 0o666);
        } catch {
          // chmod 也失败就交给下面的 unlinkSync 报错
        }
        fs.unlinkSync(子);
        continue;
      }
      throw 错误;
    }
  }
  fs.rmdirSync(目标);
}

module.exports = { 删目录, 手写递归删除, 含非ASCII };
