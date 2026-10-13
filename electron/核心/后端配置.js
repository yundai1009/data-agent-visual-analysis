// 把用户设置翻译成后端子进程的环境变量（纯函数，不依赖 electron，可直接单测）。
// 做了什么：构建后端环境(基础环境, 设置) 先叠一层 默认补丁（DB_BACKEND=sqlite / AUTH_ENABLED=false / HOST=127.0.0.1），
//   再按设置注入 API_PORT 与 PORT、mysql 模式下的 MYSQL_*、real 认证下的 AUTH_ENABLED / JWT_SECRET_KEY / SEED_ADMIN_PASSWORD。
// 为什么在这里拼 env 而不是让后端自己去读桌面版的 settings.json：后端是网页版与桌面版共用的同一份代码，
//   给它开一条「读桌面版私有目录」的配置路径，就等于把桌面版特有的东西焊进后端；env 是两版共有的进程契约，且外部可观测。
// 为什么默认是 sqlite + 演示模式：零配置开箱即用是新装桌面版的硬要求，MySQL 与真实认证是可选增强，不能变成前置条件。
// 坑：API_PORT 与 PORT 都写同一个值——后端自检与 uvicorn 历史上读的键不统一，两个都写才能保证哪个生效结果都一样。
// 坑：mysql 分支只在 模式==='mysql' 时才覆盖 DB_BACKEND，其它未知模式会静默沿用默认 sqlite，不报错也不提示（校验在 配置模型.js 里做）。
// 坑：认证开启时若密钥/口令为空就不注入这两个键——特意留给后端自检去报「未设置」，用空串注入会把「没配」伪装成「配了」。
function 默认补丁() {
  return {
    DB_BACKEND: 'sqlite',
    AUTH_ENABLED: 'false',
    HOST: '127.0.0.1',
  };
}

/**
 * @param {object} 基础环境 process.env 的副本
 * @param {object} 设置 userData/settings.json 内容（可能为空）
 * @returns {object} 合并后的后端环境变量
 */
function 构建后端环境(基础环境, 设置 = {}) {
  const env = { ...基础环境, ...默认补丁() };
  const 端口 = 设置.端口 != null ? String(设置.端口) : '8000';
  env.API_PORT = 端口;
  env.PORT = 端口;

  const 数据库 = 设置.数据库 || {};
  if (数据库.模式 === 'mysql') {
    env.DB_BACKEND = 'mysql';
    env.MYSQL_HOST = 数据库.主机 || '127.0.0.1';
    env.MYSQL_PORT = String(数据库.端口 || 3306);
    env.MYSQL_USER = 数据库.用户 || '';
    env.MYSQL_PASSWORD = 数据库.密码 || '';
    env.MYSQL_DATABASE = 数据库.库名 || '';
  }

  if (设置.认证模式 === 'real') {
    // 认证开启：后端自检要求显式强密钥 + 非默认预置管理员口令，否则拒绝启动
    env.AUTH_ENABLED = 'true';
    if (设置.JWT密钥) env.JWT_SECRET_KEY = String(设置.JWT密钥);
    if (设置.预置管理员口令) env.SEED_ADMIN_PASSWORD = String(设置.预置管理员口令);
  }

  return env;
}

module.exports = { 构建后端环境, 默认补丁 };