// 打包链自检（阶段八十）：防止「前端改了、装出来还是旧界面」再发生一次。
//
// 背景：桌面版有三层前端副本（用户覆盖层 / 安装包副本 / dist-backend 内置副本）。
// 只改前端时若跳过 `npm run build:backend` 直接跑 electron-builder，PyInstaller 产物里那份旧前端
// 会被原样搬进安装包，而 win-unpacked 的 exe 时间戳是新的，从外面完全看不出来。
// 这些断言锁住的是「打包入口必须带自检」这条隐性规则，不是锁住实现细节。
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const electron根 = path.resolve(__dirname, '..');
const 包 = JSON.parse(fs.readFileSync(path.join(electron根, 'package.json'), 'utf8'));

test('打包入口先重建后端，再自检前端一致，最后才打包', () => {
  const dist = 包.scripts.dist;
  assert.match(dist, /build:backend/, 'dist 必须先 npm run build:backend：spec 会把 frontend/dist 收进 dist-backend');
  assert.match(dist, /检查前端一致\.js/, 'dist 必须带前端一致性自检，否则旧前端会被静默打进安装包');
  assert.ok(
    dist.indexOf('build:backend') < dist.indexOf('检查前端一致.js'),
    '自检必须排在 build:backend 之后——它比的就是 build:backend 的产物',
  );
  assert.ok(
    dist.indexOf('检查前端一致.js') < dist.indexOf('electron-builder'),
    '自检必须排在 electron-builder 之前，否则它只能事后抱怨',
  );
});

test('dist:dir 与 dist 同样带自检', () => {
  assert.match(包.scripts['dist:dir'], /检查前端一致\.js/);
});

test('提供独立的 check:ui 入口，便于打包前手工确认', () => {
  assert.match(包.scripts['check:ui'], /检查前端一致\.js/);
});

test('自检脚本真实存在，且不靠 fs.cpSync 拷目录', () => {
  const 脚本 = path.join(electron根, '脚本', '检查前端一致.js');
  assert.ok(fs.existsSync(脚本), '脚本/检查前端一致.js 必须存在，否则 dist 会直接失败');
  const 源码 = fs.readFileSync(脚本, 'utf8').replace(/^\s*\/\/.*$/gm, '');
  assert.ok(!/fs\.cpSync/.test(源码), 'Node 24 上 cpSync 拷该产物会静默崩进程（见推送前端.js 的坑）');
});

test('推送前端脚本是覆盖而非合并（旧 hash chunk 不许残留）', () => {
  const 源码 = fs.readFileSync(path.join(electron根, '脚本', '推送前端.js'), 'utf8');
  assert.match(源码, /删目录\(目标/, '必须先删目标目录：旧构建的 hash 文件名没人引用，留着只会让覆盖层越来越胖');
  assert.ok(!/fs\.rmSync\(目标/.test(源码), '目标路径含中文（%APPDATA%\\数据分析Agent\\…），裸 fs.rmSync 会静默不删（阶段八十一）：必须用 核心/删目录.js 的 删目录()');
});
