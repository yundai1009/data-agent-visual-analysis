import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UserRoundPen, KeyRound, UserX } from 'lucide-react';
import { useApp } from '../AppContext';
import { changeUsername, changePassword, deleteAccount } from '../api';

const inputCls =
  'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:border-accent transition-all';
const btnPrimary =
  'w-full py-2.5 rounded-lg text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-40';
const btnDanger =
  'w-full py-2.5 rounded-lg text-sm font-medium text-white hover:bg-red-600 transition-all disabled:opacity-40 bg-red-500';

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

export default function Account() {
  const navigate = useNavigate();
  const { user, logout, setAuth } = useApp();

  // 修改用户名
  const [newName, setNewName] = useState('');
  const [nameMsg, setNameMsg] = useState('');
  const [nameBusy, setNameBusy] = useState(false);
  // 修改密码
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');
  const [pwdBusy, setPwdBusy] = useState(false);
  // 注销账号
  const [delPwd, setDelPwd] = useState('');
  const [delMsg, setDelMsg] = useState('');
  const [delBusy, setDelBusy] = useState(false);

  const handleChangeName = async () => {
    setNameMsg('');
    setNameBusy(true);
    try {
      const res = await changeUsername(newName);
      // 改名即吊销旧 token：用 setAuth 统一更新 token + user_cache + 内存态，界面立即生效
      if (res?.access_token) setAuth(res.access_token, { ...user, username: res.username || newName });
      setNameMsg('用户名已修改，下次登录请使用新用户名');
      setNewName('');
    } catch (e) {
      setNameMsg(e.message || '修改失败');
    }
    setNameBusy(false);
  };

  const handleChangePwd = async () => {
    setPwdMsg('');
    setPwdBusy(true);
    try {
      const res = await changePassword(oldPwd, newPwd);
      // 改密即吊销旧 token：保持当前会话不中断
      if (res?.access_token) setAuth(res.access_token, { ...user });
      setPwdMsg('密码已修改');
      setOldPwd(''); setNewPwd('');
    } catch (e) {
      setPwdMsg(e.message || '修改失败');
    }
    setPwdBusy(false);
  };

  const handleDeleteAccount = async () => {
    setDelMsg('');
    setDelBusy(true);
    try {
      await deleteAccount(delPwd);
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
