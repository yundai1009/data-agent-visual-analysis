// electron/tests/后端配置.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const { 构建后端环境 } = require('../核心/后端配置');

const 基础 = { PATH: 'x', FOO: 'bar' };

test('默认：sqlite + 演示模式（零配置开箱即用）', () => {
  const env = 构建后端环境(基础, {});
  assert.strictEqual(env.DB_BACKEND, 'sqlite');
  assert.strictEqual(env.AUTH_ENABLED, 'false');
  assert.strictEqual(env.HOST, '127.0.0.1');
  assert.strictEqual(env.FOO, 'bar'); // 基础环境保留
  assert.ok(!('MYSQL_HOST' in env));
});

test('mysql 模式：注入 MYSQL_* 并切换 DB_BACKEND', () => {
  const env = 构建后端环境(基础, {
    数据库: { 模式: 'mysql', 主机: '127.0.0.1', 端口: 3306, 用户: 'daa_app', 密码: 'secret', 库名: 'daa' },
  });
  assert.strictEqual(env.DB_BACKEND, 'mysql');
  assert.strictEqual(env.MYSQL_HOST, '127.0.0.1');
  assert.strictEqual(env.MYSQL_PORT, '3306');
  assert.strictEqual(env.MYSQL_USER, 'daa_app');
  assert.strictEqual(env.MYSQL_PASSWORD, 'secret');
  assert.strictEqual(env.MYSQL_DATABASE, 'daa');
  assert.strictEqual(env.AUTH_ENABLED, 'false'); // 数据库切换不影响认证模式
});

test('真实认证：AUTH_ENABLED=true + JWT 密钥 + 预置口令', () => {
  const env = 构建后端环境(基础, {
    认证模式: 'real',
    JWT密钥: 'a-strong-secret-123',
    预置管理员口令: 'NotAdmin123!',
  });
  assert.strictEqual(env.AUTH_ENABLED, 'true');
  assert.strictEqual(env.JWT_SECRET_KEY, 'a-strong-secret-123');
  assert.strictEqual(env.SEED_ADMIN_PASSWORD, 'NotAdmin123!');
});

test('真实认证缺密钥：不注入（后端自检会拒绝启动，属用户配置错误提示）', () => {
  const env = 构建后端环境(基础, { 认证模式: 'real' });
  assert.strictEqual(env.AUTH_ENABLED, 'true');
  assert.ok(!('JWT_SECRET_KEY' in env));
});

test('mysql + 真实认证组合', () => {
  const env = 构建后端环境(基础, {
    数据库: { 模式: 'mysql', 主机: '127.0.0.1', 用户: 'daa_app', 密码: 's', 库名: 'daa' },
    认证模式: 'real',
    JWT密钥: 'k',
    预置管理员口令: 'p',
  });
  assert.strictEqual(env.DB_BACKEND, 'mysql');
  assert.strictEqual(env.AUTH_ENABLED, 'true');
});

// ---- 阶段七十五：前端产物路径显式注入 ----
// 用户抱怨「每一次更新桌面版都需要重新打包太麻烦了」：根因是 frontend/dist 被
// extraResources 拷进安装包。现在由 main.js 显式传 FRONTEND_DIST，开发模式指向仓库 dist。
test('选项.前端目录 透传成 FRONTEND_DIST', () => {
  const env = 构建后端环境(基础, {}, { 前端目录: 'D:/repo/frontend/dist' });
  assert.strictEqual(env.FRONTEND_DIST, 'D:/repo/frontend/dist');
});

test('前端目录为空/空白：不注入，保留后端自己的默认值', () => {
  assert.ok(!('FRONTEND_DIST' in 构建后端环境(基础, {}, { 前端目录: '' })));
  assert.ok(!('FRONTEND_DIST' in 构建后端环境(基础, {}, { 前端目录: '   ' })));
  assert.ok(!('FRONTEND_DIST' in 构建后端环境(基础, {})));
});

test('注入 FRONTEND_DIST 不影响数据库/认证分支', () => {
  const env = 构建后端环境(基础, {
    数据库: { 模式: 'mysql', 主机: 'h', 用户: 'u', 密码: 'p', 库名: 'daa' },
    认证模式: 'real', JWT密钥: 'k', 预置管理员口令: 'p',
  }, { 前端目录: '/x/frontend/dist' });
  assert.strictEqual(env.FRONTEND_DIST, '/x/frontend/dist');
  assert.strictEqual(env.DB_BACKEND, 'mysql');
  assert.strictEqual(env.AUTH_ENABLED, 'true');
});
