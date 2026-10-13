// 启动时给后端挑一个没被占用的回环端口：为什么不能写死 8000 见下面「为什么」。
// 做了什么：探测空闲端口(startPort=8000) 逐个试 net.createServer().listen(端口, '127.0.0.1')，
//   监听成功就立刻 close 并把这个端口交出去；监听失败（被占用）则 +1 重试，试满 startPort…startPort+50 共 51 个才 reject。
// 为什么找空闲端口而不是固定 8000：开发机上后端可能正开着，或上一个桌面实例没退干净，
//   写死端口会直接 bind 失败，用户看到「后端未就绪」却查不出真实原因；探测让多开与残留端口都被静默绕开。
// 为什么探测完 close 再交给 uvicorn：net 与 uvicorn 无法共享同一个监听套接字，只能「先占住确认没人抢，再放掉让 uvicorn 抢」；
//   放掉到 uvicorn 绑定之间存在毫秒级竞态，理论上仍可能被第三方抢占——这是已知取舍，赌的是桌面版独占本机回环端口。
// 坑：只探 127.0.0.1 不探 0.0.0.0；若别的程序绑在 0.0.0.0:8000，这里会判定「空闲」，后端随后绑定失败。
// 坑：全占用时 reject 的错误文案是「端口 8000-8050 全部被占用」，区间含两端；main.js 未捕获它，会冒泡成启动失败的通用弹窗。
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