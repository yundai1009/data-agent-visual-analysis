// electron/tests/推送前端契约.test.js
// 锁的是"这条命令真的能跑"，而不是"它长得像能跑"。
// 阶段七十五踩过两个真实的坑，都做成断言防回归：
//   ① fs.cpSync 在 Node 24 上拷这个 dist 会让进程静默崩掉
//      （退出码 -1073740791 / 0xC0000409，不抛异常、没有 stderr），
//      于是"推送成功"其实什么都没推。所以断言必须写 copyFileSync + 递归函数；
//   ② 目标必须落在 数据根目录/frontend/dist —— 写错位置就等于覆盖层永远不生效，
//      用户还是会以为"必须重新打包"。
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

const 脚本路径 = path.resolve(__dirname, '..', '脚本', '推送前端.js');
const 源码 = fs.readFileSync(脚本路径, 'utf-8');
// 只看"代码"：脚本文件头专门写了「不要用 fs.cpSync」的坑位说明，
// 直接对全文匹配会被注释里的那行字误判成违规（第一版就这么红的）。
const 代码 = 源码
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/.*$/gm, '');
const 仓库根 = path.resolve(__dirname, '..', '..');
const 仓库dist = path.join(仓库根, 'frontend', 'dist');

function 跑(参数列表) {
  return spawnSync(process.execPath, [脚本路径, ...参数列表], { encoding: 'utf-8' });
}

function 临时目标() {
  const 根 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-ui-'));
  return { 根, 目标: path.join(根, 'dist') };
}

function 数文件(目录) {
  return fs.readdirSync(目录, { withFileTypes: true })
    .reduce((n, e) => n + (e.isDirectory() ? 数文件(path.join(目录, e.name)) : 1), 0);
}

test('必须用 copyFileSync 递归复制，不能图省事用 fs.cpSync（Node 24 上会静默崩进程）', () => {
  assert.ok(/fs\.copyFileSync/.test(代码), '应使用 fs.copyFileSync');
  assert.ok(!/fs\.cpSync/.test(代码), '不得使用 fs.cpSync（见脚本文件头的坑位说明）');
  assert.ok(/function 复制树/.test(代码) && /复制树\(来自, 去\)/.test(代码), '必须递归处理子目录');
});

test('默认目标路径必须是 %APPDATA%\\数据分析Agent\\frontend\\dist', () => {
  assert.ok(/process\.env\.APPDATA/.test(源码));
  assert.ok(源码.includes("'数据分析Agent'"));
  assert.ok(源码.includes("'frontend'"));
  assert.ok(源码.includes("'dist'"));
});

test('源目录缺 index.html：退出码 1，且报错里教人先构建', () => {
  const 空源 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-src-'));
  const { 根, 目标 } = 临时目标();
  const 结果 = 跑(['--from', 空源, '--dir', 目标]);
  const 输出 = 结果.stdout + (结果.stderr || '');
  assert.strictEqual(结果.status, 1);
  assert.ok(/没有 index\.html/.test(输出));
  assert.ok(/npm run build/.test(输出));
  fs.rmSync(空源, { recursive: true, force: true });
  fs.rmSync(根, { recursive: true, force: true });
});

test('真跑一遍：推到临时目录，文件数与源一致且 index.html 就位', () => {
  assert.ok(fs.existsSync(path.join(仓库dist, 'index.html')), '仓库应有已构建的 dist');
  const { 根, 目标 } = 临时目标();
  const 结果 = 跑(['--from', 仓库dist, '--dir', 目标]);
  assert.strictEqual(结果.status, 0, 结果.stdout + (结果.stderr || ''));
  assert.ok(fs.existsSync(path.join(目标, 'index.html')));
  assert.strictEqual(数文件(目标), 数文件(仓库dist));
  fs.rmSync(根, { recursive: true, force: true });
});

test('重复推送幂等：第二次不会因为目标已存在而失败（旧产物被覆盖而非合并）', () => {
  const { 根, 目标 } = 临时目标();
  const 第一次 = 跑(['--from', 仓库dist, '--dir', 目标]);
  // 手工塞一个旧构建残留，验证"覆盖而不是合并"
  fs.writeFileSync(path.join(目标, 'assets', '陈旧-old.js'), 'x', 'utf-8');
  const 第二次 = 跑(['--from', 仓库dist, '--dir', 目标]);
  assert.strictEqual(第一次.status, 0);
  assert.strictEqual(第二次.status, 0, 第二次.stdout + (第二次.stderr || ''));
  assert.ok(!fs.existsSync(path.join(目标, 'assets', '陈旧-old.js')), '旧残留应被清掉');
  fs.rmSync(根, { recursive: true, force: true });
});
