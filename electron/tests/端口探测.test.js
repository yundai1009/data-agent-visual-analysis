// electron/tests/端口探测.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const net = require('node:net');
const { 探测空闲端口 } = require('../核心/端口探测');

test('返回可用端口', async () => {
  const port = await 探测空闲端口(18000);
  assert.ok(port >= 18000 && port < 18051);
});

test('被占用端口自动跳到下一个空闲端口', async () => {
  const 占用 = net.createServer();
  await new Promise(r => 占用.listen(18100, '127.0.0.1', r));
  const port = await 探测空闲端口(18100);
  assert.strictEqual(port, 18101);
  占用.close();
});

test('全部被占用时拒绝', async () => {
  const servers = [];
  for (let p = 18200; p < 18251; p++) {
    const s = net.createServer();
    await new Promise(r => s.listen(p, '127.0.0.1', r));
    servers.push(s);
  }
  await assert.rejects(() => 探测空闲端口(18200), /全部被占用/);
  servers.forEach(s => s.close());
});
