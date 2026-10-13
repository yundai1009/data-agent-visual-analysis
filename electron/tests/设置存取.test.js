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