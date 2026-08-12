/* =============================================================================
 * 文件：frontend/src/pages/Account.jsx —— 账号设置页（路由 /account）
 * 功能：三个账号级操作，全部调后端接口后同步前端状态：
 *   1. 修改用户名 changeUsername → setAuth 换新 token + 新用户名（旧 token 被后端吊销）
 *   2. 修改密码   changePassword  → setAuth 换新 token（旧会话全部失效，当前会话续命）
 *   3. 注销账号   deleteAccount   → logout() + 跳登录页（后端删除全部数据）
 * 重点设计：改名/改密后端都会签发新 token（旧 token 吊销），
 *   所以成功后必须走 setAuth 统一入口，把 token + user_cache + 内存态一次性更新。
 * 依赖：
 *   - api.js：changeUsername / changePassword / deleteAccount
 *   - AppContext：useApp() 里的 user、setAuth、logout
 * ============================================================================= */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UserRoundPen, KeyRound, UserX } from 'lucide-react';
import { useApp } from '../AppContext';
import { changeUsername, changePassword, deleteAccount } from '../api';

// 三个共享样式串：普通输入框 / 主按钮（蓝）/ 危险按钮（红）
const inputCls =
  'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:border-accent transition-all';
const btnPrimary =
  'w-full py-2.5 rounded-lg text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-40';
const btnDanger =
  'w-full py-2.5 rounded-lg text-sm font-medium text-white hover:bg-red-600 transition-all disabled:opacity-40 bg-red-500';

// Section 区块组件：图标 + 标题 + 描述 + 内容区的卡片容器，三个操作区共用
// 入参：icon（图标组件）、title（标题）、desc（描述）、children（内容区）
function Section({ icon: Icon, title, desc, children }) {
  return (
    <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] p-6">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 text-accent" />
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      </div>
      {desc && <p className="text-xs text-gray-500 mb-4">{desc}</p>}
      {children}
    </div>
  );
}

// Account 账号设置页主组件
// 业务定位：普通用户自助管理登录凭证与账号；三个操作各自独立 loading/提示文案，互不阻塞
// 依赖：useApp() 的 user（展示当前用户名/角色）、setAuth（改后换 token）、logout（注销后清理）
export default function Account() {
  const navigate = useNavigate();
  const { user, logout, setAuth } = useApp();

  // 修改用户名表单状态（输入框 + 结果提示 + 提交中标记）
  const [newName, setNewName] = useState('');
  const [nameMsg, setNameMsg] = useState('');
  const [nameBusy, setNameBusy] = useState(false);
  // 修改密码表单状态
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');
  const [pwdBusy, setPwdBusy] = useState(false);
  // 注销账号表单状态
  const [delPwd, setDelPwd] = useState('');
  const [delMsg, setDelMsg] = useState('');
  const [delBusy, setDelBusy] = useState(false);

  // 修改用户名：成功后后端吊销旧 token 并签发新 token，必须用 setAuth 同步三处状态
  const handleChangeName = async () => {
    setNameMsg('');
    setNameBusy(true);
    try {
      const res = await changeUsername(newName);
      // 改名即吊销旧 token：用 setAuth 统一更新 token + user_cache + 内存态，界面立即生效
      // 【关键行】把后端返回的新 token 和最新用户名同步到三处：localStorage + 内存 state + 登录态标记。
      // 为什么：改名后旧 token 已被后端吊销，若只存 localStorage 不更新内存态，
      //   界面仍显示旧用户名（微信改昵称是即时生效的体验）；若不换 token，
      //   下一次请求携带旧 token 会被 401 直接踢回登录页。
      // 删除后果：改名成功提示后页面仍显示旧用户名直到刷新；或后续请求带旧 token 被 401 全局登出。
      // 替代方案：单独做 updateUser 只更新用户名（改动更小），但多套状态源容易再出现
      //   不一致（token 换了 user 没换）；统一走 setAuth 单一入口更稳。
      if (res?.access_token) setAuth(res.access_token, { ...user, username: res.username || newName });
      setNameMsg('用户名已修改，下次登录请使用新用户名');
      setNewName('');
    } catch (e) {
      setNameMsg(e.message || '修改失败');
    }
    setNameBusy(false);
  };

  // 修改密码：同样换新 token，但用户名不变，所以 user 原样传回（{ ...user }）
  const handleChangePwd = async () => {
    setPwdMsg('');
    setPwdBusy(true);
    try {
      const res = await changePassword(oldPwd, newPwd);
      // 改密即吊销旧 token：保持当前会话不中断
      // 【关键行】换新 token 且保留原用户信息：改密后旧 token 立即失效，不换的话
      //   当前会话下一次请求就被 401 踢出（自己刚改完密码就被登出，体验很怪）。
      // 为什么：后端安全策略是“改密吊销全部旧会话”，前端必须无缝衔接到新 token。
      // 删除后果：改密成功后当前用户立刻被全局登出，被迫重新登录。
      // 替代方案：改密后强制跳登录页重新登录（更保守更安全），但牺牲了会话连续性；
      //   无缝换 token 是主流做法（GitHub/微信都如此），风险由后端吊销机制兜底。
      if (res?.access_token) setAuth(res.access_token, { ...user });
      setPwdMsg('密码已修改');
      setOldPwd(''); setNewPwd('');
    } catch (e) {
      setPwdMsg(e.message || '修改失败');
    }
    setPwdBusy(false);
  };

  // 注销账号：后端删完数据后，前端登出 + 跳登录页（本地缓存由 logout 统一清理）
  const handleDeleteAccount = async () => {
    setDelMsg('');
    setDelBusy(true);
    try {
      await deleteAccount(delPwd);
      // 【关键行】注销成功后必须走 logout 清空本地 token/用户/数据集缓存。
      // 为什么：账号已被删除，残留的 token 会让「返回上一页」还能访问受保护页面；
      //   同时 dataset_cache 若不清理，下个账号会看到已注销账号的数据。
      // 删除后果：注销后仍停留在原页面，任意操作再次 401，或下个账号登录看到残留数据。
      // 替代方案：只清 token 不清 dataset_cache（少删一个 key），但会留下跨账号数据残留；
      //   直接复用 logout 一次清干净最省事。
      logout();
      navigate('/login');
    } catch (e) {
      setDelMsg(e.message || '注销失败');
    }
    setDelBusy(false);
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-5">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-gray-900">账号设置</h2>
        <span className="text-xs text-gray-400 bg-gray-100 rounded-full px-2.5 py-0.5">
          {user?.username || '未登录'}
          {user?.role === 'admin' && ' · 管理员'}
        </span>
      </div>

      {/* 修改用户名 */}
      <Section
        icon={UserRoundPen}
        title="修改用户名"
        desc="用户名即登录凭证（登录名）。修改后旧用户名立即失效，下次登录请使用新用户名。"
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">当前用户名</label>
            <input className={`${inputCls} bg-gray-50`} value={user?.username || ''} disabled />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">新用户名</label>
            <input
              className={inputCls}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="2-50 个字符，需唯一"
              autoComplete="off"
            />
          </div>
          {nameMsg && (
            <p className={`text-xs ${nameMsg.includes('成功') || nameMsg.includes('已修改') ? 'text-emerald-600' : 'text-red-500'}`}>
              {nameMsg}
            </p>
          )}
          <button
            onClick={handleChangeName}
            disabled={nameBusy || newName.trim().length < 2}
            className={btnPrimary}
            style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}
          >
            {nameBusy ? '提交中…' : '确认修改用户名'}
          </button>
        </div>
      </Section>

      {/* 修改密码 */}
      <Section icon={KeyRound} title="修改密码" desc="需验证当前密码；修改后旧会话全部失效，当前会话保持登录。">
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">当前密码</label>
            <input
              type="password"
              className={inputCls}
              value={oldPwd}
              onChange={(e) => setOldPwd(e.target.value)}
              placeholder="输入当前密码"
              autoComplete="current-password"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">新密码</label>
            <input
              type="password"
              className={inputCls}
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              placeholder="至少 6 位"
              autoComplete="new-password"
            />
          </div>
          {pwdMsg && (
            <p className={`text-xs ${pwdMsg.includes('成功') || pwdMsg.includes('已修改') ? 'text-emerald-600' : 'text-red-500'}`}>
              {pwdMsg}
            </p>
          )}
          <button
            onClick={handleChangePwd}
            disabled={pwdBusy || !oldPwd || newPwd.length < 6}
            className={btnPrimary}
            style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}
          >
            {pwdBusy ? '提交中…' : '确认修改密码'}
          </button>
        </div>
      </Section>

      {/* 注销账号（危险区） */}
      <Section icon={UserX} title="注销账号" desc="将永久删除你的账号与全部数据（数据集/报表/看板/分享），此操作不可恢复。">
        <div className="space-y-3">
          <input
            type="password"
            className={inputCls}
            value={delPwd}
            onChange={(e) => setDelPwd(e.target.value)}
            placeholder="输入当前密码确认注销"
            autoComplete="current-password"
          />
          {delMsg && <p className="text-xs text-red-500">{delMsg}</p>}
          <button
            onClick={handleDeleteAccount}
            disabled={delBusy || !delPwd}
            className={btnDanger}
          >
            {delBusy ? '注销中…' : '永久注销账号'}
          </button>
        </div>
      </Section>
    </div>
  );
}
