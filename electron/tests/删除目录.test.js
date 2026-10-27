// electron/tests/删除目录.test.js
// 锁住阶段八十一的根因：`fs.rmSync` 在**路径含非 ASCII 字符**时不可靠——
// 轻则静默 no-op（什么都不删也不报错），重则直接让进程崩掉（0xC0000409）。
// 这组测试**真的碰文件系统**（不用 mock）：要证明的正是"某个 API 在这台机器上
// 不工作"这种只能靠真实行为才能观察的事情；mock 过的 rmSync 永远"成功"。
//
// 注意本文件自己的清理也用 `删目录()` 而不是 `fs.rmSync()`：
// 临时目录名故意带中文，用 fs.rmSync 清理会反过来把测试进程打死
// （实测 exitCode -1073740791，与阶段七十五记录过的 fs.cpSync 崩溃是同一个签名）。
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { 删目录, 手写递归删除, 含非ASCII } = require('../核心/删目录');

/** 造一棵带子目录和文件的树（模拟 frontend/dist 的形状），返回根路径。 */
function 造树(根) {
  fs.mkdirSync(path.join(根, 'assets', '深一层'), { recursive: true });
  fs.writeFileSync(path.join(根, 'index.html'), '<!doctype html>');
  fs.writeFileSync(path.join(根, 'assets', 'a-1.js'), 'x');
  fs.writeFileSync(path.join(根, 'assets', '深一层', 'b-2.js'), 'x');
  return 根;
}

test('含非ASCII：中文/全角/emoji 判为真，纯 ASCII 判为假', () => {
  assert.strictEqual(含非ASCII('D:\\work\\daa\\frontend\\dist'), false);
  assert.strictEqual(含非ASCII('D:\\python\\数据分析agent\\frontend\\dist'), true);
  assert.strictEqual(含非ASCII('C:\\Users\\x\\AppData\\Roaming\\数据分析Agent\\dist'), true);
  assert.strictEqual(含非ASCII('/tmp/前端产出'), true);
});

test('删目录：路径含中文也能删干净（rmSync 在这个路径上会崩或哑火）', () => {
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), '删目录-中文-'));
  const 目标 = 造树(path.join(根, '前端产出'));
  assert.ok(fs.existsSync(目标), '前置：树造出来了');
  assert.strictEqual(删目录(目标), true, '删目录 必须返回 true');
  assert.ok(!fs.existsSync(目标), '删完必须真的不存在——判据是 existsSync，不是 API 返回值');
  删目录(根);
});

test('删目录：目标本来就不存在时返回 true（幂等）', () => {
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), '删目录-空-'));
  assert.strictEqual(删目录(path.join(根, '没有这个目录')), true);
  删目录(根);
});

test('手写递归删除：含中文路径下 readdir/unlink/rmdir 都正常（rmSync 的替代路径）', () => {
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), '手写删除-'));
  const 目标 = 造树(path.join(根, '数据分析Agent平台', 'dist'));
  assert.ok(fs.existsSync(目标));
  手写递归删除(目标);
  assert.ok(!fs.existsSync(目标), '手写递归在中文路径下必须有效');
  删目录(根);
});

test('删目录：返回值必须严格等于"删完是否不存在"（不许拿 rmSync 的空返回当成功）', () => {
  // 回归点：曾经写成 `fs.rmSync(...); return true;` —— rmSync 静默 no-op 时
  // 依然返回 true，调用方以为删干净了，于是"先删再拷"退化成"拷贝旧文件"。
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), '删目录-判据-'));
  const 目标 = 造树(path.join(根, '中文-判据'));
  assert.strictEqual(删目录(目标), !fs.existsSync(目标), '返回值必须与 existsSync 一致');
  删目录(根);
});

test('删目录：ASCII 路径这条快路径也不能退化（普通 clone 目录仍然一次删净）', () => {
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-plain-'));
  const 目标 = 造树(path.join(根, 'plain-dist'));
  assert.strictEqual(删目录(目标), true);
  assert.ok(!fs.existsSync(目标));
  删目录(根);
});
