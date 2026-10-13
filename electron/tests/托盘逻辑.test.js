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

test('菜单含配置项，且退出前有分隔线（配置不要挤在退出旁边）', () => {
  const m = 托盘菜单({ 是否主窗口可见: false });
  const ids = m.map(x => x.id);
  assert.ok(ids.includes('config'), '缺少配置项入口');
  const 配置项 = m.find(x => x.id === 'config');
  assert.strictEqual(配置项.type, 'normal');
  assert.ok(配置项.label.length > 0);
  // 顺序约定：show → config → separator → quit
  assert.ok(ids.indexOf('show') < ids.indexOf('config'));
  assert.ok(ids.indexOf('config') < ids.indexOf('separator'));
  assert.ok(ids.indexOf('separator') < ids.indexOf('quit'));
});
