import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Database, Zap, BarChart3, LayoutDashboard, Shield, ChevronLeft, ChevronRight, LogOut, KeyRound, X, UserRoundPen, MessageSquareHeart, Download, UserX } from 'lucide-react';
import { useApp } from '../AppContext';
import { changePassword, changeUsername, submitFeedback, exportUserData, deleteAccount } from '../api';

const navItems = [
  { to: '/data', icon: Database, label: '数据管理' },
  { to: '/analysis', icon: Zap, label: '智能分析' },
  { to: '/report', icon: BarChart3, label: '报表历史' },
  { to: '/dashboard', icon: LayoutDashboard, label: '图表看板' },
];

// 管理员专属入口：仅 admin 角色显示
const adminNav = { to: '/admin', icon: Shield, label: '管理后台' };

export default function Sidebar({ collapsed, onToggle }) {
  const navigate = useNavigate();
  const { user, logout } = useApp();
  const [pwdOpen, setPwdOpen] = useState(false);
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');
  const [pwdBusy, setPwdBusy] = useState(false);
  const [nameOpen, setNameOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [nameMsg, setNameMsg] = useState('');
  const [nameBusy, setNameBusy] = useState(false);
  // 反馈弹窗（C：意见反馈入口）
  const [fbOpen, setFbOpen] = useState(false);
  const [fbScore, setFbScore] = useState(5);
  const [fbText, setFbText] = useState('');
  const [fbMsg, setFbMsg] = useState('');
  const [fbBusy, setFbBusy] = useState(false);
  // D 合规：数据导出 + 注销
  const [delOpen, setDelOpen] = useState(false);
  const [delPwd, setDelPwd] = useState('');
  const [delMsg, setDelMsg] = useState('');
  const [delBusy, setDelBusy] = useState(false);
  const handleExportData = async () => {
    try {
      const { blob, filename } = await exportUserData();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert('导出失败：' + (e.message || e));
    }
  };
  const handleDeleteAccount = async () => {
    setDelBusy(true);
    setDelMsg('');
    try {
      await deleteAccount(delPwd);
      handleLogout();
    } catch (e) {
      setDelMsg(e.message || '注销失败');
    }
    setDelBusy(false);
  };

  const handleSubmitFeedback = async () => {
    setFbBusy(true);
    setFbMsg('');
    try {
      await submitFeedback({ score: fbScore, correction: fbText });
      setFbMsg('感谢反馈！');
      setFbText('');
      setTimeout(() => setFbOpen(false), 1200);
    } catch (e) {
      setFbMsg('提交失败：' + (e.message || e));
    }
    setFbBusy(false);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleChangePwd = async () => {
    setPwdMsg('');
    setPwdBusy(true);
    try {
      const res = await changePassword(oldPwd, newPwd);
      // B7 修复：改密吊销旧 token，保存后端返回的新 token 避免下次请求 401 登出
      if (res?.access_token) localStorage.setItem('access_token', res.access_token);
      setPwdMsg('密码已修改');
      setOldPwd(''); setNewPwd('');
      setTimeout(() => setPwdOpen(false), 1100);
    } catch (e) {
      setPwdMsg(e.message || '修改失败');
    }
    setPwdBusy(false);
  };
  const handleChangeName = async () => {
    setNameMsg('');
    setNameBusy(true);
    try {
      const res = await changeUsername(newName);
      // B7 修复：改名吊销旧 token，保存新 token 并同步 user_cache 的 username
      if (res?.access_token) {
        localStorage.setItem('access_token', res.access_token);
        try {
          const uc = JSON.parse(localStorage.getItem('user_cache') || '{}');
          uc.username = newName;
          localStorage.setItem('user_cache', JSON.stringify(uc));
        } catch { /* ignore */ }
      }
      setNameMsg('用户名已修改');
      setTimeout(() => setNameOpen(false), 1400);
    } catch (e) {
      setNameMsg(e.message || '修改失败');
    }
    setNameBusy(false);
  };
  const pwdInput = "w-full border border-white/15 rounded-lg px-3 py-2 text-xs bg-white/[0.07] text-white placeholder:text-slate-400/60 focus:outline-none focus:border-white/40 transition-all";
  return (
    <aside
      className={`flex flex-col shrink-0 transition-all duration-250 ease-in-out overflow-hidden ${
        collapsed ? 'w-14' : 'w-52'
      }`}
      style={{
        background: 'linear-gradient(180deg, rgba(10,20,36,.96), rgba(8,16,30,.96))',
        borderRight: '1px solid rgba(255,255,255,.08)',
        boxShadow: '2px 0 20px rgba(0,0,0,.25)',
        backdropFilter: 'blur(16px)',
      }}
    >
      {/* Brand */}
      <div className="h-16 flex items-center gap-2.5 px-3 border-b border-white/[0.06] shrink-0">
        <div
          className="w-8 h-8 rounded-lg text-white flex items-center justify-center text-xs font-bold shrink-0"
          style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)', boxShadow: '0 4px 12px -3px rgba(15,76,129,.7)' }}
        >
          DA
        </div>
        <div className={`transition-opacity duration-200 overflow-hidden ${collapsed ? 'opacity-0 w-0' : 'opacity-100'}`}>
          <p className="text-sm font-semibold text-white whitespace-nowrap">数据助手</p>
          <p className="text-xs text-slate-400 leading-tight -mt-0.5 whitespace-nowrap">自助分析平台</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-2 space-y-0.5 mt-1">
        {[...navItems, ...((user?.role === 'admin' || user?.roles?.includes?.('admin')) ? [adminNav] : [])].map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 relative ${
                isActive
                  ? 'text-white font-medium'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.05]'
              }`
            }
            style={({ isActive }) => (isActive ? { background: 'rgba(15,76,129,.35)' } : undefined)}
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-[3px]"
                        style={{ background: 'linear-gradient(180deg, #4a8ac2, #0f4c81)' }} />
                )}
                <item.icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-accent-soft' : ''}`} />
                <span className={`transition-opacity duration-200 whitespace-nowrap ${collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'}`}>
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* User + Toggle */}
      <div className="p-2 border-t border-white/[0.06] space-y-1">
        <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-white shrink-0"
            style={{ background: 'rgba(15,76,129,.5)' }}
          >
            {(user?.username || '云').slice(0, 1)}
          </div>
          <div className={`transition-opacity duration-200 ${collapsed ? 'opacity-0 w-0' : 'opacity-100'}`}>
            <p className="text-xs font-medium text-slate-200 whitespace-nowrap">{user?.username || '未登录'}</p>
          </div>
          <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0 ml-auto" />
        </div>

        {/* 修改用户名 */}
        <button
          onClick={() => { setNameOpen(true); setNameMsg(''); setNewName(''); }}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title="修改用户名"
        >
          <UserRoundPen className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">修改用户名</span>}
        </button>

        {/* 修改密码 */}
        <button
          onClick={() => { setPwdOpen(true); setPwdMsg(''); setOldPwd(''); setNewPwd(''); }}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title="修改密码"
        >
          <KeyRound className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">修改密码</span>}
        </button>

        {/* D：导出我的数据 */}
        <button
          onClick={handleExportData}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title="导出我的全部数据"
        >
          <Download className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">导出数据</span>}
        </button>

        {/* 意见反馈（C） */}
        <button
          onClick={() => { setFbOpen(true); setFbMsg(''); setFbText(''); }}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title="意见反馈"
        >
          <MessageSquareHeart className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">意见反馈</span>}
        </button>

        {/* D：注销账号 */}
        <button
          onClick={() => { setDelOpen(true); setDelMsg(''); setDelPwd(''); }}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="注销账号"
        >
          <UserX className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">注销账号</span>}
        </button>

        <button
          onClick={handleLogout}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="登出"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">登出</span>}
        </button>

        <button
          onClick={onToggle}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* 修改用户名弹窗 */}
      {nameOpen && (
        <>
          <div className="fixed inset-0 z-[60] bg-black/50" onClick={() => setNameOpen(false)} />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-[320px] rounded-2xl p-6"
               style={{ background: 'linear-gradient(165deg, rgba(18,30,50,.97), rgba(10,20,36,.97))', border: '1px solid rgba(255,255,255,.12)', boxShadow: '0 30px 80px -20px rgba(0,0,0,.7)' }}>
            <div className="flex items-center justify-between mb-5">
              <p className="text-sm font-semibold text-white">修改用户名</p>
              <button className="text-slate-400 hover:text-white transition-colors" onClick={() => setNameOpen(false)}><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-300 block mb-1.5">当前用户名</label>
                <input className={pwdInput} value={user?.username || ''} disabled />
              </div>
              <div>
                <label className="text-xs text-slate-300 block mb-1.5">新用户名</label>
                <input className={pwdInput} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="2-50 个字符" autoComplete="off" />
              </div>
              <p className="text-[11px] text-slate-400">用户名需保持唯一，与现有账号冲突会被拒绝。</p>
              {nameMsg && <p className={`text-xs ${nameMsg.includes('成功') || nameMsg.includes('已修改') ? 'text-emerald-400' : 'text-red-400'}`}>{nameMsg}</p>}
              <button
                onClick={handleChangeName}
                disabled={nameBusy || newName.trim().length < 2}
                className="w-full py-2.5 rounded-lg text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}
              >
                {nameBusy ? '提交中…' : '确认修改'}
              </button>
            </div>
          </div>
        </>
      )}

      {/* 修改密码弹窗 */}
      {pwdOpen && (
        <>
          <div className="fixed inset-0 z-50 bg-black/50" onClick={() => setPwdOpen(false)} />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[320px] rounded-2xl p-6"
               style={{ background: 'linear-gradient(165deg, rgba(18,30,50,.97), rgba(10,20,36,.97))', border: '1px solid rgba(255,255,255,.12)', boxShadow: '0 30px 80px -20px rgba(0,0,0,.7)' }}>
            <div className="flex items-center justify-between mb-5">
              <p className="text-sm font-semibold text-white">修改密码</p>
              <button className="text-slate-400 hover:text-white transition-colors" onClick={() => setPwdOpen(false)}><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-300 block mb-1.5">旧密码</label>
                <input type="password" className={pwdInput} value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} placeholder="输入当前密码" autoComplete="current-password" />
              </div>
              <div>
                <label className="text-xs text-slate-300 block mb-1.5">新密码</label>
                <input type="password" className={pwdInput} value={newPwd} onChange={(e) => setNewPwd(e.target.value)} placeholder="至少 6 位" autoComplete="new-password" />
              </div>
              {pwdMsg && <p className={`text-xs ${pwdMsg.includes('成功') || pwdMsg.includes('已修改') ? 'text-emerald-400' : 'text-red-400'}`}>{pwdMsg}</p>}
              <button
                onClick={handleChangePwd}
                disabled={pwdBusy || !oldPwd || newPwd.length < 6}
                className="w-full py-2.5 rounded-lg text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}
              >
                {pwdBusy ? '提交中…' : '确认修改'}
              </button>
            </div>
          </div>
        </>
      )}
      {/* 意见反馈弹窗（C） */}
      {fbOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setFbOpen(false)}>
          <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <MessageSquareHeart className="w-4 h-4 text-accent" /> 意见反馈
              </h3>
              <button onClick={() => setFbOpen(false)} className="p-1 rounded hover:bg-gray-100 text-gray-400">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="mb-3">
              <p className="text-xs text-gray-500 mb-1.5">使用体验（1-5 分）</p>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map((v) => (
                  <button key={v} onClick={() => setFbScore(v)}
                    className={`w-9 h-9 rounded-lg text-sm font-semibold transition-all ${
                      v <= fbScore ? 'bg-accent text-white' : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                    }`}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              value={fbText}
              onChange={(e) => setFbText(e.target.value)}
              rows={3}
              placeholder="想吐槽或建议什么？（可选）"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent resize-none mb-2"
            />
            {fbMsg && <p className={`text-xs mb-2 ${fbMsg.startsWith('提交失败') ? 'text-red-500' : 'text-emerald-600'}`}>{fbMsg}</p>}
            <button
              onClick={handleSubmitFeedback}
              disabled={fbBusy}
              className="w-full py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all disabled:opacity-50"
            >
              {fbBusy ? '提交中…' : '提交反馈'}
            </button>
          </div>
        </div>
      )}


      {/* D：注销账号弹窗 */}
      {delOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDelOpen(false)}>
          <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <UserX className="w-4 h-4 text-red-500" /> 注销账号
              </h3>
              <button onClick={() => setDelOpen(false)} className="p-1 rounded hover:bg-gray-100 text-gray-400">
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-3">将永久删除你的账号与全部数据（数据集/报表/看板/分享），此操作不可恢复。请输入密码确认。</p>
            <input
              type="password"
              value={delPwd}
              onChange={(e) => setDelPwd(e.target.value)}
              placeholder="当前密码"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-red-400 mb-2"
            />
            {delMsg && <p className="text-xs text-red-500 mb-2">{delMsg}</p>}
            <button
              onClick={handleDeleteAccount}
              disabled={delBusy || !delPwd}
              className="w-full py-2 rounded-lg bg-red-500 text-white text-sm font-medium hover:bg-red-600 transition-all disabled:opacity-50"
            >
              {delBusy ? '注销中…' : '确认注销'}
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
