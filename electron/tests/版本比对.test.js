// electron/tests/版本比对.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const { 比对版本 } = require('../核心/版本比对');

test('同版本 = 最新', () => assert.strictEqual(比对版本('0.1.0', '0.1.0'), '最新'));
test('本地低 = 可更新', () => assert.strictEqual(比对版本('0.1.0', '0.2.0'), '可更新'));
test('本地高 = 最新', () => assert.strictEqual(比对版本('1.0.0', '0.9.9'), '最新'));
test('多段数值比较', () => assert.strictEqual(比对版本('1.9.9', '1.10.0'), '可更新'));
test('非法版本 = 未知', () => assert.strictEqual(比对版本('abc', '0.1.0'), '未知'));