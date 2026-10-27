// electron/tests/配置模型.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const {
  默认表单, 设置转表单, 表单转设置, 校验表单, 生效配置, 是否需要重启,
  随机强密钥, 密钥最小长度,
} = require('../核心/配置模型');

const mysql表单 = () => ({ ...默认表单(), 数据库模式: 'mysql', 主机: 'db.local', 端口: 3307, 用户: 'u', 密码: 'p@ss', 库名: 'daa2' });
const real表单 = () => ({ ...默认表单(), 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'S3cret!2026' });

test('默认表单 = SQLite + 演示模式（零配置形态）', () => {
  const f = 默认表单();
  assert.strictEqual(f.数据库模式, 'sqlite');
  assert.strictEqual(f.认证模式, 'demo');
  assert.strictEqual(f.端口, 3306);
  assert.strictEqual(f.主机, '127.0.0.1');
  assert.strictEqual(f.库名, 'daa');
  assert.strictEqual(f.密码, '');
  assert.strictEqual(f.JWT密钥, '');
  // 每次调用返回新对象，避免调用方改坏共享默认值
  f.主机 = '被改了';
  assert.strictEqual(默认表单().主机, '127.0.0.1');
});

test('设置转表单：空设置回落到默认；MySQL 与真实认证能正确回填', () => {
  assert.deepStrictEqual(设置转表单(), 默认表单());
  assert.deepStrictEqual(设置转表单({}), 默认表单());

  const 回填 = 设置转表单({
    数据库: { 模式: 'mysql', 主机: '10.0.0.5', 端口: '3307', 用户: 'daa_app', 密码: 'p@ss', 库名: 'daa' },
    认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'pw',
  });
  assert.strictEqual(回填.数据库模式, 'mysql');
  assert.strictEqual(回填.主机, '10.0.0.5');
  assert.strictEqual(回填.端口, 3307, '端口应转成数字，避免下拉框里出现 "3307" 字符串');
  assert.strictEqual(回填.认证模式, 'real');
  assert.strictEqual(回填.预置管理员口令, 'pw');
});

test('设置转表单：非法取值不外泄，落到安全默认', () => {
  const f = 设置转表单({ 数据库: { 模式: 'postgres', 主机: 'x' }, 认证模式: 'ldap' });
  assert.strictEqual(f.数据库模式, 'sqlite');
  assert.strictEqual(f.认证模式, 'demo');
  // 数据库对象里的其它字段仍应被回填，切回 mysql 时不用重打
  assert.strictEqual(f.主机, 'x');
});

test('表单转设置：MySQL 分支逐字段映射', () => {
  // 阶段七十九：「邮件服务: null」是新增的整段删除标记（演示模式不配 SMTP），
  // 属于补丁形状的契约扩展，不是放宽断言——下面新增的 SMTP 用例会各自断言真正的值。
  assert.deepStrictEqual(表单转设置(mysql表单()), {
    数据库: { 模式: 'mysql', 主机: 'db.local', 端口: 3307, 用户: 'u', 密码: 'p@ss', 库名: 'daa2' },
    认证模式: 'demo',
    JWT密钥: null,
    预置管理员口令: null,
    邮件服务: null,
  });
});

test('表单转设置：切回 SQLite 只保留 模式，MySQL 凭据不再落盘', () => {
  const 补丁 = 表单转设置({ ...mysql表单(), 数据库模式: 'sqlite' });
  assert.deepStrictEqual(补丁.数据库, { 模式: 'sqlite' });
  assert.strictEqual(补丁.数据库.主机, undefined, 'sqlite 模式不应写 MySQL 主机');
});

test('表单转设置：切回演示模式用 null 表达删除（写设置的删除约定）', () => {
  const 补丁 = 表单转设置({ ...real表单(), 认证模式: 'demo' });
  assert.strictEqual(补丁.认证模式, 'demo');
  assert.strictEqual(补丁.JWT密钥, null);
  assert.strictEqual(补丁.预置管理员口令, null);
  assert.strictEqual(补丁.邮件服务, null, '演示模式免登录，SMTP 配置也要一起清掉');
});

test('校验：默认表单与合法 MySQL / 真实认证都通过', () => {
  assert.deepStrictEqual(校验表单(默认表单()), { ok: true, 错误: [] });
  assert.strictEqual(校验表单(mysql表单()).ok, true);
  assert.strictEqual(校验表单(real表单()).ok, true);
  // 端口边界：1 与 65535 合法，字符串数字也合法（表单读出来就是字符串）
  assert.strictEqual(校验表单({ ...mysql表单(), 端口: '1' }).ok, true);
  assert.strictEqual(校验表单({ ...mysql表单(), 端口: '65535' }).ok, true);
});

test('校验：SMTP 留空放行（继续 dry-run），填了主机就要凑齐发信最低要求', () => {
  // 阶段七十九：阶段一不配 SMTP 是合法默认（demo 模式注册无意义，real 模式会走 dry-run 并如实告知）。
  assert.deepStrictEqual(校验表单(real表单()).错误, []);
  // 只填主机、其余留空 —— 必须报「用户名」与「密码」缺失
  const 半填 = 校验表单({ ...real表单(), 邮件主机: 'smtp.qq.com', 邮件用户: '', 邮件密码: '' });
  assert.strictEqual(半填.ok, false);
  assert.ok(半填.错误.some(e => /SMTP 用户名/.test(e)), '缺 SMTP 用户名应报');
  assert.ok(半填.错误.some(e => /授权码/.test(e)), '缺 SMTP 密码应提示「授权码」而非「密码」');
  // 端口非法也要拦
  assert.ok(校验表单({ ...real表单(), 邮件主机: 'smtp.qq.com', 邮件用户: 'a@b.com', 邮件密码: 'x', 邮件端口: '70000' }).错误.some(e => /SMTP 端口/.test(e)), 'SMTP 端口越界应报');
  // 完整填好则通过
  assert.strictEqual(校验表单({ ...real表单(), 邮件主机: 'smtp.qq.com', 邮件端口: 465, 邮件用户: '123@qq.com', 邮件密码: 'abcd', 邮件发件人: '123@qq.com' }).ok, true);
});

test('校验：MySQL 必填项逐条给出人话错误', () => {
  assert.match(校验表单({ ...mysql表单(), 主机: '  ' }).错误[0], /主机/);
  assert.match(校验表单({ ...mysql表单(), 用户: '' }).错误[0], /用户名/);
  assert.match(校验表单({ ...mysql表单(), 库名: '' }).错误[0], /库名/);
  for (const 端口 of ['', '0', '65536', '3306.5', 'abc']) {
    assert.match(校验表单({ ...mysql表单(), 端口 }).错误[0], /端口/, `端口 ${端口} 应被拒绝`);
  }
  // sqlite 模式不校验 MySQL 字段（它们压根不进后端 env）
  assert.strictEqual(校验表单({ ...默认表单(), 主机: '', 用户: '', 库名: '', 端口: '' }).ok, true);
});

test('校验：真实认证拒绝弱密钥与默认口令（对齐后端启动自检）', () => {
  assert.match(校验表单({ ...real表单(), JWT密钥: 'short' }).错误[0], new RegExp(`${密钥最小长度}`));
  assert.match(校验表单({ ...real表单(), JWT密钥: '' }).错误[0], /JWT/);
  // change-me-in-production 只有 24 字符，长度与默认值两条都会命中——断言「其中一条」而非第一条
  assert.ok(校验表单({ ...real表单(), JWT密钥: 'change-me-in-production' }).错误.some(e => /change-me-in-production/.test(e)));
  assert.match(校验表单({ ...real表单(), 预置管理员口令: '' }).错误[0], /口令/);
  assert.match(校验表单({ ...real表单(), 预置管理员口令: 'admin123' }).错误[0], /admin123/);
  // 演示模式不要求密钥/口令
  assert.strictEqual(校验表单({ ...默认表单(), JWT密钥: '', 预置管理员口令: '' }).ok, true);
});

test('校验：非法模式值被拒绝', () => {
  assert.match(校验表单({ ...默认表单(), 数据库模式: 'postgres' }).错误[0], /数据库模式/);
  assert.match(校验表单({ ...默认表单(), 认证模式: 'ldap' }).错误[0], /认证模式/);
});

test('是否需要重启：全新安装点保存不该白白重启一次', () => {
  // 磁盘上没有 settings.json（={}），用户第一次点保存写的是显式 sqlite+demo —— 生效配置一致
  assert.strictEqual(是否需要重启({}, 表单转设置(默认表单())), false);
  assert.strictEqual(是否需要重启({}, { 数据库: { 模式: 'sqlite' }, 认证模式: 'demo' }), false);
});

test('是否需要重启：数据库 / 认证的实质变化都要重启', () => {
  const 基线 = { 数据库: { 模式: 'sqlite' }, 认证模式: 'demo' };
  assert.strictEqual(是否需要重启(基线, { ...基线, 数据库: { 模式: 'mysql', 主机: 'h', 端口: 3306, 用户: 'u', 密码: '', 库名: 'daa' } }), true);
  const mysql = { 数据库: { 模式: 'mysql', 主机: 'h', 端口: 3306, 用户: 'u', 密码: 'p', 库名: 'daa' }, 认证模式: 'demo' };
  assert.strictEqual(是否需要重启(mysql, { ...mysql, 数据库: { ...mysql.数据库, 密码: 'p2' } }), true, 'MySQL 密码变了要重启');
  assert.strictEqual(是否需要重启(mysql, { ...mysql, 数据库: { ...mysql.数据库, 端口: 3307 } }), true, '端口变了要重启');
  const real = { 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'pw' };
  assert.strictEqual(是否需要重启(基线, real), true);
  assert.strictEqual(是否需要重启(real, { ...real, JWT密钥: 'z'.repeat(64) }), true, 'JWT 密钥变了要重启');
});

test('是否需要重启：键顺序不同不算变化（归一化比较）', () => {
  const a = { 数据库: { 模式: 'mysql', 主机: 'h', 端口: 3306, 用户: 'u', 密码: 'p', 库名: 'daa' } };
  const b = { 数据库: { 库名: 'daa', 密码: 'p', 用户: 'u', 端口: 3306, 主机: 'h', 模式: 'mysql' } };
  assert.strictEqual(是否需要重启(a, b), false);
});

test('是否需要重启：sqlite 下改 MySQL 字段、demo 下改密钥都不算变化', () => {
  const 基线 = { 数据库: { 模式: 'sqlite' }, 认证模式: 'demo' };
  assert.strictEqual(是否需要重启(基线, { 数据库: { 模式: 'sqlite', 主机: '改了', 用户: '也改了' }, 认证模式: 'demo' }), false);
  assert.strictEqual(是否需要重启(基线, { ...基线, JWT密钥: 'k'.repeat(64) }), false, '演示模式下密钥不进 env');
});

test('生效配置：只暴露真正会进 env 的字段', () => {
  assert.deepStrictEqual(生效配置({}), { 数据库: { 模式: 'sqlite' }, 认证: { 模式: 'demo' } });
  const c = 生效配置({ 数据库: { 模式: 'mysql', 主机: 'h', 端口: 3306, 用户: 'u', 密码: 'p', 库名: 'daa' }, 认证模式: 'real', JWT密钥: 'k', 预置管理员口令: 'p' });
  assert.strictEqual(c.数据库.模式, 'mysql');
  assert.strictEqual(c.认证.模式, 'real');
  assert.strictEqual(c.认证.JWT密钥, 'k');
  assert.strictEqual(c.认证.邮件, null, 'real 但没填 SMTP 主机，邮件不应参与重启判定');
});

test('生效配置：real + SMTP 主机非空才把邮件纳入（触发重启判定的范围）', () => {
  const c = 生效配置({ 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'p', 邮件服务: { 主机: 'smtp.qq.com', 端口: 465, 用户: '123@qq.com', 密码: 'auth', 发件人: '123@qq.com' } });
  assert.deepStrictEqual(c.认证.邮件, { 主机: 'smtp.qq.com', 端口: 465, 用户: '123@qq.com', 密码: 'auth', 发件人: '123@qq.com' });
});

test('表单转设置：real + SMTP 主机非空写整段，空主机写 null', () => {
  const 有邮件 = 表单转设置({ ...real表单(), 邮件主机: 'smtp.qq.com', 邮件端口: 465, 邮件用户: '123@qq.com', 邮件密码: 'auth', 邮件发件人: '123@qq.com' });
  assert.deepStrictEqual(有邮件.邮件服务, { 主机: 'smtp.qq.com', 端口: 465, 用户: '123@qq.com', 密码: 'auth', 发件人: '123@qq.com' });
  const 空邮件 = 表单转设置({ ...real表单(), 邮件主机: '  ', 邮件用户: '123@qq.com', 邮件密码: 'auth' });
  assert.strictEqual(空邮件.邮件服务, null, '主机留空（含纯空格）应回落 null，不写空段');
});

test('设置转表单：邮件字段能正确回填', () => {
  const 回填 = 设置转表单({ 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'p', 邮件服务: { 主机: 'smtp.qq.com', 端口: '465', 用户: '123@qq.com', 密码: 'auth', 发件人: '123@qq.com' } });
  assert.strictEqual(回填.邮件主机, 'smtp.qq.com');
  assert.strictEqual(回填.邮件端口, 465, '端口应转成数字');
  assert.strictEqual(回填.邮件用户, '123@qq.com');
  assert.strictEqual(回填.邮件密码, 'auth');
  assert.strictEqual(回填.邮件发件人, '123@qq.com');
});

test('是否需要重启：real 下 SMTP 主机新增/变更要触发重启，demo 下改邮件不算', () => {
  const real无邮 = { 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'p' };
  const real有邮 = { ...real无邮, 邮件服务: { 主机: 'smtp.qq.com', 端口: 465, 用户: '123@qq.com', 密码: 'auth', 发件人: '123@qq.com' } };
  assert.strictEqual(是否需要重启(real无邮, real有邮), true, '新增 SMTP 要重启后端');
  assert.strictEqual(是否需要重启(real有邮, { ...real有邮, 邮件服务: { ...real有邮.邮件服务, 密码: 'new' } }), true, 'SMTP 密码变了要重启');
  const demo = { 数据库: { 模式: 'sqlite' }, 认证模式: 'demo' };
  assert.strictEqual(是否需要重启(demo, { ...demo, 邮件服务: { 主机: 'smtp.qq.com' } }), false, 'demo 模式不进 env，改邮件不算变化');
});

test('往返：设置 → 表单 → 设置，生效配置不变', () => {
  const 原设置 = { 数据库: { 模式: 'mysql', 主机: 'db.local', 端口: 3307, 用户: 'u', 密码: 'p@ss', 库名: 'daa2' }, 认证模式: 'real', JWT密钥: 'k'.repeat(64), 预置管理员口令: 'pw' };
  const 往返后 = { ...原设置, ...表单转设置(设置转表单(原设置)) };
  assert.deepStrictEqual(生效配置(往返后), 生效配置(原设置));
  assert.strictEqual(是否需要重启(原设置, 往返后), false);
});

test('随机强密钥：64 位 hex 且每次不同', () => {
  const a = 随机强密钥();
  assert.match(a, /^[0-9a-f]{64}$/);
  assert.ok(a.length >= 密钥最小长度);
  assert.notStrictEqual(a, 随机强密钥(), '必须每次重新随机，否则同两次生成可预测');
});