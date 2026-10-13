// electron/核心/端口探测.js
const net = require('node:net');

/**
 * 从 startPort 起找第一个可监听的 TCP 端口（探测后立即释放，交给 uvicorn 绑定）。
 * 最多尝试 50 个端口，全部占用抛错。
 */
function 探测空闲端口(startPort = 8000) {
  return new Promise((resolve, reject) => {
    let current = startPort;
    const 尝试 = () => {
      if (current > startPort + 50) {
        return reject(new Error(`端口 ${startPort}-${current - 1} 全部被占用`));
      }
      const srv = net.createServer();
      srv.once('error', () => {
        current += 1;
        尝试();
      });
      srv.once('listening', () => {
        const port = current;
        srv.close(() => resolve(port));
      });
      srv.listen(current, '127.0.0.1');
    };
    尝试();
  });
}

module.exports = { 探测空闲端口 };