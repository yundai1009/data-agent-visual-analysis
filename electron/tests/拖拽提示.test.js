// electron/tests/拖拽提示.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const { 提取可上传文件 } = require('../核心/拖拽提示');

test('过滤非白名单扩展名', () => {
  const r = 提取可上传文件([{ name: 'a.csv', path: 'C:/a.csv' }, { name: 'b.exe', path: 'C:/b.exe' }]);
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].name, 'a.csv');
});

test('无 path 时返回空串不抛错', () => {
  const r = 提取可上传文件([{ name: 'x.xlsx' }]);
  assert.strictEqual(r[0].path, '');
});