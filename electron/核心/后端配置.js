// electron/核心/后端配置.js
/**
 * 根据用户设置构建后端进程的环境变量（纯逻辑，便于单测；不依赖 electron API）。
 *
 * 默认形态（零配置开箱即用）：
 *   DB_BACKEND=sqlite（本地 %APPDATA% 库）+ AUTH_ENABLED=false（演示模式，回环免认证）
 *
 * 用户可在 userData/settings.json 里覆盖：
 *   { "数据库": { "模式": "mysql", "主机": ..., "端口": ..., "用户": ..., "密码": ..., "库名": ... } }
 *     → 注入 DB_BACKEND=mysql 与 MYSQL_*（网页版/桌面版连同一个库，账号数据天然同步）
 *   { "认证模式": "real" }
 *     → AUTH_ENABLED=true + JWT_SECRET_KEY（强密钥）+ 预置管理员口令
 *       （后端启动安全自检要求：认证开启时这两项必须显式非默认值）
 */

/** 默认：sqlite + 演示模式的后端环境变量补丁。 */
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