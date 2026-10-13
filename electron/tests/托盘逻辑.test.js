// electron/tests/托盘逻辑.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const { 托盘菜单 } = require('../核心/托盘逻辑');

test('菜单含显示与退出', () => {
  const m = 托盘菜单({ 是否主窗口可见: true });
  const ids = m.map(x => x.id);
  assert.ok(ids.includes('show') && ids.includes('quit'));
  assert.ok(m.some(x => x.type === 'separator'));
});
