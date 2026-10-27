// electron/tests/配置页契约.test.js
/**
 * 配置窗口的「静态契约」测试。
 *
 * 配置页是内联脚本 + file:// 加载，DOM 绑定那一层没法用 node --test 跑；
 * 但它最容易出的错是「拼错一个 id / 调了不存在的 API / 调了主进程没注册的 IPC /
 * 打包时漏掉 配置页 目录」——这些全都能静态比对出来，且比人工点一遍更早发现。
 */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const 根 = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(根, '配置页', 'index.html'), 'utf-8');
const preload = fs.readFileSync(path.join(根, '配置页', 'preload.js'), 'utf-8');
const mainJs = fs.readFileSync(path.join(根, 'main.js'), 'utf-8');
const 包json = JSON.parse(fs.readFileSync(path.join(根, 'package.json'), 'utf-8'));

const 内联脚本 = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const 收集 = (文本, 正则) => [...文本.matchAll(正则)].map((m) => m[1]);
const htmlId = 收集(html, /id="([^"]+)"/g);

test('配置页内联脚本用的每个 id 在 HTML 里都存在', () => {
  const 脚本Id = new Set(收集(内联脚本, /\$\('([^']+)'\)/g));
  // 字段映射表里的 id 同样要真实存在（读表单全靠它）
  const 字段块 = 内联脚本.match(/var 字段 = \{([\s\S]*?)\};/);
  assert.ok(字段块, '找不到 字段 映射表');
  收集(字段块[1], /:\s*'([^']+)'/g).forEach((id) => 脚本Id.add(id));
  assert.ok(脚本Id.size > 0, '没解析出任何 id，测试本身失效了');
  for (const id of 脚本Id) {
    assert.ok(htmlId.includes(id), `HTML 里缺少 id="${id}"`);
  }
});

test('密码显示切换按钮指向的输入框都存在', () => {
  const 目标 = 收集(html, /data-切换密码="([^"]+)"/g);
  assert.ok(目标.length >= 3, '密码/密钥/口令三处都应有显示切换');
  for (const id of 目标) {
    assert.ok(htmlId.includes(id), `切换按钮指向不存在的 id="${id}"`);
    // 注意属性顺序不固定（type 可能写在 id 前面），要拿整个标签判断
    const 标签 = html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`));
    assert.ok(标签 && /type="password"/.test(标签[0]), `id="${id}" 应为 password 输入`);
  }
});

test('两个单选组的 name 与取值都在 HTML 里', () => {
  for (const [name, 取值] of [['数据库模式', ['sqlite', 'mysql']], ['认证模式', ['demo', 'real']]]) {
    assert.ok(new RegExp(`name="${name}"`).test(html), `缺少 name="${name}" 的单选组`);
    for (const v of 取值) {
      assert.ok(html.includes(`name="${name}" value="${v}"`), `缺少 ${name}=${v}`);
    }
  }
});

test('配置页调用的 API 全部由 preload 暴露', () => {
  const 调用 = new Set(收集(内联脚本, /API\.([A-Za-z一-龥]+)\(/g));
  // 键名是中文，\w 匹配不到，必须显式带 CJK 范围
  const 暴露 = 收集(preload.slice(preload.indexOf('exposeInMainWorld(')), /([\w\u4e00-\u9fa5]+):\s*\(/g);
  assert.ok(调用.size >= 5, `解析到的 API 调用只有 ${调用.size} 个，测试可能失效`);
  for (const 名 of 调用) {
    assert.ok(暴露.includes(名), `preload 未暴露 API.${名}`);
  }
  // 暴露出来的都该被用上，避免留一个高权限空壳
  for (const 名 of 暴露) {
    assert.ok(调用.has(名), `preload 暴露了 API.${名} 但页面没用到`);
  }
});

test('preload 用的 IPC 通道全部在主进程注册', () => {
  const 通道 = new Set(收集(preload, /ipcRenderer\.(?:invoke|send)\('([^']+)'/g));
  assert.ok(通道.size >= 6, '配置窗口至少要有 6 个 IPC 通道');
  const 已注册 = new Set(收集(mainJs, /ipcMain\.(?:handle|on)\('([^']+)'/g));
  for (const 名 of 通道) {
    assert.ok(已注册.has(名), `main.js 没注册 IPC 通道 ${名}`);
  }
});

test('页面脚本读的全局名与 preload 暴露的全局名一致', () => {
  const 暴露名 = preload.match(/exposeInMainWorld\('([^']+)'/)[1];
  assert.match(内联脚本, new RegExp(`window\\.${暴露名}\\b`), `页面没有读 window.${暴露名}`);
});

test('CSP 放行了内联脚本/样式（file:// 下 self 匹配不可靠，别被后人改回外链）', () => {
  const csp = html.match(/Content-Security-Policy"\s+content="([^"]+)"/)[1];
  assert.match(csp, /script-src 'unsafe-inline'/);
  assert.match(csp, /style-src 'unsafe-inline'/);
  assert.ok(!/<script[^>]+src=/.test(html), '配置页不应有外链脚本');
  assert.ok(!/<link[^>]+stylesheet/.test(html), '配置页不应有外链样式');
});

test('打包白名单带上 配置页 与 核心（漏了装出来就是白页）', () => {
  const files = 包json.build.files;
  assert.ok(files.includes('配置页/**/*'), 'build.files 缺 配置页/**/*');
  assert.ok(files.includes('核心/**/*'), 'build.files 缺 核心/**/*');
  assert.ok(files.includes('main.js') && files.includes('preload.js'));
});

test('配置页不加载任何外部资源（离线可用 + 无远程内容）', () => {
  assert.ok(!/https?:\/\//.test(html.replace(/http-equiv/g, '')) || !/<(script|img|iframe)/i.test(html.replace(/https?:\/\/[^\s"'<>]*/g, '')),
    '配置页不应引用远程地址');
  assert.ok(!/<iframe/i.test(html), '配置页不应内嵌 iframe');
});

// ---- 阶段七十九：SMTP 字段组（挂在「真实认证」下，demo 模式下被隐藏）----
test('SMTP 五个字段的 id 都在 HTML 里，且都是 password(密码) 或 text(其余)', () => {
  for (const [id, 应该是] of [
    ['邮件主机', 'text'], ['邮件端口', 'number'], ['邮件用户', 'text'],
    ['邮件密码', 'password'], ['邮件发件人', 'text'],
  ]) {
    assert.ok(htmlId.includes(id), `HTML 缺少 id="${id}"`);
    const 标签 = html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`));
    assert.ok(标签 && 标签[0].includes(`type="${应该是}"`), `id="${id}" 类型应为 ${应该是}`);
  }
});

test('SMTP 字段的显示切换按钮指向 邮件密码', () => {
  const 目标 = 收集(html, /data-切换密码="([^"]+)"/g);
  assert.ok(目标.includes('邮件密码'), 'SMTP 密码应有显示切换');
});

test('SMTP 字段组在「真实认证」fieldset 内（demo 时连隐藏带不显示）', () => {
  // 认证字段本身含一个嵌套 fieldset（SMTP），所以不能只截到「下一个 <fieldset」——
  // 那样截到的是 SMTP 那个内层，反而把被测字段排除了。这里按 depth 走一遍找真正的闭合点。
  const 起点 = html.indexOf('id="认证字段"');
  assert.ok(起点 >= 0, '缺少 认证字段 fieldset');
  const 开 = html.lastIndexOf('<fieldset', 起点);
  assert.ok(开 >= 0, '找不到 认证字段 的起始标签');
  let 深度 = 0;
  let 游标 = 开;
  let 结束 = html.length;
  while (游标 < html.length) {
    const 下一个开 = html.indexOf('<fieldset', 游标 + 1);
    const 下一个闭 = html.indexOf('</fieldset>', 游标 + 1);
    if (下一个闭 < 0) break;
    if (下一个开 >= 0 && 下一个开 < 下一个闭) { 深度 += 1; 游标 = 下一个开; continue; }
    深度 -= 1;
    游标 = 下一个闭;
    if (深度 <= 0) { 结束 = 下一个闭 + '</fieldset>'.length; break; }
  }
  const 区块 = html.slice(开, 结束);
  for (const id of ['邮件主机', '邮件端口', '邮件用户', '邮件密码', '邮件发件人']) {
    assert.ok(区块.includes(`id="${id}"`), `SMTP 字段 ${id} 应在 认证字段 内`);
  }
});

test('SMTP 字段被纳入页面 字段 映射表（读表单靠它往返）', () => {
  const 字段块 = 内联脚本.match(/var 字段 = \{([\s\S]*?)\};/);
  assert.ok(字段块, '找不到 字段 映射表');
  const 映射 = 字段块[1];
  for (const id of ['邮件主机', '邮件端口', '邮件用户', '邮件密码', '邮件发件人']) {
    assert.ok(映射.includes(id), `字段映射表缺 ${id}`);
  }
});

test('SMTP 主机/端口/用户/密码/发件人 既是 HTML id 又是 字段 映射值，且二者一致', () => {
  const 字段块 = 内联脚本.match(/var 字段 = \{([\s\S]*?)\};/);
  const 映射值 = 收集(字段块[1], /'(邮件[^']+)'/g);
  for (const v of 映射值) {
    assert.ok(htmlId.includes(v), `字段映射值 ${v} 在 HTML 里没有对应 id`);
  }
});