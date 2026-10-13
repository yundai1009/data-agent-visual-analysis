// electron/tests/设置存取.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { 读设置, 写设置 } = require('../核心/设置存取');

test('无文件时读回空对象', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-set-'));
  assert.deepStrictEqual(读设置(dir), {});
  fs.rmSync(dir, { recursive: true, force: true });
});

test('写入后读回合并结果', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-set-'));
  写设置(dir, { 开机自启: true });
  写设置(dir, { 窗口宽: 1440 });
  const s = 读设置(dir);
  assert.strictEqual(s.开机自启, true);
  assert.strictEqual(s.窗口宽, 1440);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('损坏 JSON 读回空对象不抛错', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-set-'));
  fs.writeFileSync(path.join(dir, 'settings.json'), '{{{ bad', 'utf-8');
  assert.deepStrictEqual(读设置(dir), {});
  fs.rmSync(dir, { recursive: true, force: true });
});

test('带 UTF-8 BOM 的 JSON 正常解析（Windows 记事本/PS 写出场景）', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-set-'));
  fs.writeFileSync(path.join(dir, 'settings.json'), '\uFEFF{"数据库":{"模式":"mysql"}}', 'utf-8');
  const s = 读设置(dir);
  assert.strictEqual(s.数据库.模式, 'mysql');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('值为 null 表示删除该键（切回 SQLite/演示模式时清凭据用）', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daa-set-'));
  // 模拟：先配好 MySQL + 真实认证
  写设置(dir, {
    数据库: { 模式: 'mysql', 主机: 'h', 端口: 3306, 用户: 'u', 密码: 'p', 库名: 'daa' },
    认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'pw', 窗口最大化: true,
  });
  // 再切回 SQLite + 演示模式：数据库段整体替换，两个凭据键用 null 删除
  const 结果 = 写设置(dir, { 数据库: { 模式: 'sqlite' }, 认证模式: 'demo', JWT密钥: null, 预置管理员口令: null });
  assert.deepStrictEqual(结果.数据库, { 模式: 'sqlite' });
  assert.strictEqual('JWT密钥' in 结果, false);
  assert.strictEqual('预置管理员口令' in 结果, false);
  // 未提及的键仍保留（合并语义不变）
  assert.strictEqual(结果.窗口最大化, true);
  const 磁盘 = 读设置(dir);
  assert.strictEqual('JWT密钥' in 磁盘, false, '凭据不能只从返回值清掉、磁盘上还留着');
  assert.strictEqual(磁盘.认证模式, 'demo');
  fs.rmSync(dir, { recursive: true, force: true });
});