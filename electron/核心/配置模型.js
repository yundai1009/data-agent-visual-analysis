// electron/核心/配置模型.js
/**
 * 桌面版可视化配置（数据库模式 / 认证模式）纯逻辑层。
 *
 * 为什么单独一层：把「settings.json 的形状」与「表单的形状」在这里做双向映射 +
 * 校验 + 变更判定，渲染层只负责 DOM 绑定、主进程只负责落盘/重启后端——
 * 语义集中在纯函数里，才能被 `node --test` 直接覆盖（不需要 electron / DOM / 真实窗口）。
 *
 * 校验规则刻意与后端启动安全自检（api/main.py::_启动安全自检）对齐：
 * 认证开启时 JWT_SECRET_KEY 必须显式非默认、SEED_ADMIN_PASSWORD 必须覆盖 admin123，
 * 否则后端起不来。前端先拦一遍，是为了让用户看到「人话错误」而不是一个启动失败弹窗。
 */
const crypto = require('node:crypto');

const 数据库模式选项 = ['sqlite', 'mysql'];
const 认证模式选项 = ['demo', 'real'];
/** JWT 密钥最小长度：低于 32 字符的密钥空间不足，容易被暴力枚举（HS256 无最小长度限制，由我们兜）。 */
const 密钥最小长度 = 32;

/** 空表单 = 零配置默认形态：sqlite 本地库 + 演示模式（与 核心/后端配置.js 默认补丁一致）。 */
function 默认表单() {
  return {
    数据库模式: 'sqlite',
    主机: '127.0.0.1',
    端口: 3306,
    用户: 'daa_app',
    密码: '',
    库名: 'daa',
    认证模式: 'demo',
    JWT密钥: '',
    预置管理员口令: '',
  };
}

/**
 * settings.json → 表单（用于「打开配置」时回填）。
 * 只认已知字段，未知字段原样留在文件里不在这里体现（写回时也是整体替换这几组字段）。
 */
function 设置转表单(设置 = {}) {
  const 表单 = 默认表单();
  const 数据库 = 设置.数据库 || {};
  if (数据库模式选项.includes(数据库.模式)) 表单.数据库模式 = 数据库.模式;
  if (数据库.主机 != null) 表单.主机 = String(数据库.主机);
  if (数据库.端口 != null) 表单.端口 = Number(数据库.端口) || 3306;
  if (数据库.用户 != null) 表单.用户 = String(数据库.用户);
  if (数据库.密码 != null) 表单.密码 = String(数据库.密码);
  if (数据库.库名 != null) 表单.库名 = String(数据库.库名);
  if (认证模式选项.includes(设置.认证模式)) 表单.认证模式 = 设置.认证模式;
  if (设置.JWT密钥 != null) 表单.JWT密钥 = String(设置.JWT密钥);
  if (设置.预置管理员口令 != null) 表单.预置管理员口令 = String(设置.预置管理员口令);
  return 表单;
}

/**
 * 表单 → settings.json 补丁（用于保存）。
 * 切回 SQLite / 演示模式时**不写入** mysql / 密钥字段；能替换整个 `数据库` 段，
 * 但 `JWT密钥`、`预置管理员口令` 是顶层键，靠 写设置() 的「值为 null = 删除该键」约定清掉
 * （合并写入无法用「不传」表达删除）。
 */
function 表单转设置(表单 = {}) {
  const 补丁 = {};
  if (表单.数据库模式 === 'mysql') {
    补丁.数据库 = {
      模式: 'mysql',
      主机: String(表单.主机 || '').trim(),
      端口: Number(表单.端口) || 0,
      用户: String(表单.用户 || '').trim(),
      密码: String(表单.密码 ?? ''),
      库名: String(表单.库名 || '').trim(),
    };
  } else {
    补丁.数据库 = { 模式: 'sqlite' };
  }
  if (表单.认证模式 === 'real') {
    补丁.认证模式 = 'real';
    补丁.JWT密钥 = String(表单.JWT密钥 ?? '');
    补丁.预置管理员口令 = String(表单.预置管理员口令 ?? '');
  } else {
    补丁.认证模式 = 'demo';
    补丁.JWT密钥 = null;
    补丁.预置管理员口令 = null;
  }
  return 补丁;
}

/**
 * 校验表单；返回 { ok, 错误: string[] }（错误为可直接展示给用户的中文）。
 * @param {object} 表单
 */
function 校验表单(表单 = {}) {
  const 错误 = [];
  if (!数据库模式选项.includes(表单.数据库模式)) {
    错误.push('数据库模式取值非法（应为 sqlite 或 mysql）');
  }
  if (表单.数据库模式 === 'mysql') {
    if (!String(表单.主机 || '').trim()) 错误.push('MySQL 主机不能为空');
    const 端口 = Number(表单.端口);
    if (!Number.isInteger(端口) || 端口 < 1 || 端口 > 65535) {
      错误.push('MySQL 端口必须是 1–65535 之间的整数');
    }
    if (!String(表单.用户 || '').trim()) 错误.push('MySQL 用户名不能为空');
    if (!String(表单.库名 || '').trim()) 错误.push('MySQL 库名不能为空');
  }
  if (!认证模式选项.includes(表单.认证模式)) {
    错误.push('认证模式取值非法（应为 demo 或 real）');
  }
  if (表单.认证模式 === 'real') {
    const 密钥 = String(表单.JWT密钥 || '');
    if (密钥.length < 密钥最小长度) {
      错误.push(`真实认证必须提供至少 ${密钥最小长度} 个字符的 JWT 密钥（可点「生成强密钥」）`);
    }
    if (密钥 === 'change-me-in-production') {
      错误.push('JWT 密钥不能使用公开默认值 change-me-in-production');
    }
    const 口令 = String(表单.预置管理员口令 || '');
    if (!口令) {
      错误.push('真实认证必须设置预置管理员口令');
    } else if (口令 === 'admin123') {
      错误.push('预置管理员口令不能使用公开默认值 admin123');
    }
  }
  return { ok: 错误.length === 0, 错误 };
}

/** 稳定序列化（键名排序）——避免同一份配置因键顺序不同被误判为「变了」。 */
function 稳定串(值) {
  if (值 === null || typeof 值 !== 'object') return JSON.stringify(值 ?? null);
  if (Array.isArray(值)) return '[' + 值.map(稳定串).join(',') + ']';
  return '{' + Object.keys(值).sort().map(k => JSON.stringify(k) + ':' + 稳定串(值[k])).join(',') + '}';
}

/**
 * 配置里真正会进后端进程 env 的部分（= 改了才需要重启的范围）。
 * 关键点：先归一化再比较——
 * · 没写过 settings.json（={}）与「显式写了 sqlite/demo」必须判定为「没变」，
 *   否则全新安装第一次点保存也会白白重启一次后端；
 * · sqlite 模式下 MySQL 主机/端口/账号等不参与比较（它们压根不会被注入）；
 * · demo 模式下 JWT 密钥/口令不参与比较。
 */
function 生效配置(设置 = {}) {
  const 表单 = 设置转表单(设置);
  const 数据库 = 表单.数据库模式 === 'mysql'
    ? { 模式: 'mysql', 主机: 表单.主机, 端口: 表单.端口, 用户: 表单.用户, 密码: 表单.密码, 库名: 表单.库名 }
    : { 模式: 'sqlite' };
  const 认证 = 表单.认证模式 === 'real'
    ? { 模式: 'real', JWT密钥: 表单.JWT密钥, 预置管理员口令: 表单.预置管理员口令 }
    : { 模式: 'demo' };
  return { 数据库, 认证 };
}

/**
 * 判断保存后是否需要重启后端进程。
 * @param {object} 旧设置 磁盘上的设置
 * @param {object} 新设置 即将写入的设置
 */
function 是否需要重启(旧设置 = {}, 新设置 = {}) {
  return 稳定串(生效配置(旧设置)) !== 稳定串(生效配置(新设置));
}

/** 生成 64 字符（32 字节 hex）强随机密钥，供认证模式用。 */
function 随机强密钥() {
  return crypto.randomBytes(32).toString('hex');
}

module.exports = {
  默认表单,
  设置转表单,
  表单转设置,
  校验表单,
  生效配置,
  是否需要重启,
  随机强密钥,
  数据库模式选项,
  认证模式选项,
  密钥最小长度,
};
