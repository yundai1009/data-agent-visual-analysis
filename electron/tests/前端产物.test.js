// 阶段七十五：桌面版前端产物定位单测。
// 锁的不是"能不能读到文件"，而是四级规则的**优先级**本身：
//   1. 用户覆盖层（%APPDATA%\数据分析Agent\frontend\dist）最高
//   2. 安装包副本（resources/backend/_internal/frontend/dist）
//   3. 仓库 frontend/dist（开发模式）
//   4. 都不可用 → null，绝不把坏路径传给后端
// 为什么优先级是产品决策而不是实现细节：开发机上装过旧安装包时，
// 如果安装包副本抢在仓库 dist 前面，就会读到陈旧产物，"改了 dist 却没变化"极难自查。
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const { 解析前端目录, 是可用产物, 前端目录来源 } = require('../核心/前端产物');

const 仓库根 = path.resolve(__dirname, '..', '..');
const 仓库产物 = path.join(仓库根, 'frontend', 'dist');

function 造副本(有index = true) {
  const 目录 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-dist-'));
  if (有index) fs.writeFileSync(path.join(目录, 'index.html'), '<html></html>', 'utf-8');
  return 目录;
}

test('只有仓库产物时：用仓库 frontend/dist（开发模式不重打包就能生效）', () => {
  assert.strictEqual(解析前端目录(仓库根, null), 仓库产物);
});

test('覆盖层与副本参数是空串/空白：都当没给，回落仓库 dist', () => {
  assert.strictEqual(解析前端目录(仓库根, '', ''), 仓库产物);
  assert.strictEqual(解析前端目录(仓库根, '   ', '   '), 仓库产物);
});

test('安装包副本可用时优先于仓库 dist（打包模式自包含性不被破坏）', () => {
  const 副本 = 造副本();
  assert.strictEqual(解析前端目录(仓库根, 副本), path.resolve(副本));
  fs.rmSync(副本, { recursive: true, force: true });
});

test('用户覆盖层存在时压过安装包副本（装了正式版也能换界面，不用重新打包）', () => {
  const 副本 = 造副本();
  const 覆盖 = 造副本();
  assert.strictEqual(解析前端目录(仓库根, 副本, 覆盖), path.resolve(覆盖));
  fs.rmSync(副本, { recursive: true, force: true });
  fs.rmSync(覆盖, { recursive: true, force: true });
});

test('覆盖层目录在但缺 index.html → 不算可用，继续往下回落', () => {
  const 空目录 = 造副本(false);
  assert.strictEqual(解析前端目录(仓库根, null, 空目录), 仓库产物);
  fs.rmSync(空目录, { recursive: true, force: true });
});

test('副本路径给了但磁盘上没有 → 回落，不把坏路径传给后端', () => {
  const 不存在 = path.join(os.tmpdir(), 'daa-dist-肯定不存在-xyz');
  const 也不存在 = path.join(os.tmpdir(), 'daa-dist-也不存在-xyz');
  assert.strictEqual(解析前端目录(仓库根, 不存在, 也不存在), 仓库产物);
});

test('三层都不可用 → null（让后端用它自己的默认值）', () => {
  const 假仓库 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-repo-'));
  assert.strictEqual(解析前端目录(假仓库, null, null), null);
  fs.rmSync(假仓库, { recursive: true, force: true });
});

test('是可用产物：只认 index.html 是文件，不认"目录存在"', () => {
  const 空目录 = 造副本(false);
  assert.strictEqual(是可用产物(空目录), false);
  fs.writeFileSync(path.join(空目录, 'index.html'), '<html></html>', 'utf-8');
  assert.strictEqual(是可用产物(空目录), true);
  fs.rmSync(空目录, { recursive: true, force: true });
  assert.strictEqual(是可用产物(path.join(os.tmpdir(), '绝无此目录-abc')), false);
  assert.strictEqual(是可用产物(null), false);
});

test('返回值是绝对路径（后端 cwd 是 %APPDATA%，相对路径会指错）', () => {
  assert.ok(path.isAbsolute(解析前端目录(仓库根, null)));
});

test('前端目录来源：说清这次用的是哪一份，排障时一眼看懂', () => {
  assert.strictEqual(前端目录来源(仓库根, null, null), '仓库构建产物');
  const 覆盖 = 造副本();
  assert.strictEqual(前端目录来源(仓库根, null, 覆盖), '用户覆盖层');
  fs.rmSync(覆盖, { recursive: true, force: true });
  const 假仓库 = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-repo-'));
  assert.strictEqual(前端目录来源(假仓库, null, null), '无（回落后端默认值）');
  fs.rmSync(假仓库, { recursive: true, force: true });
});
