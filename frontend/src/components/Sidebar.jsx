import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Database, Zap, BarChart3, LayoutDashboard, ChevronLeft, ChevronRight, LogOut, KeyRound, X, UserRoundPen } from 'lucide-react';
import { useApp } from '../AppContext';
import { changePassword, changeUsername } from '../api';

const navItems = [
  { to: '/data', icon: Database, label: '数据管理' },
  { to: '/analysis', icon: Zap, label: '智能分析' },
  { to: '/report', icon: BarChart3, label: '报表历史' },
  { to: '/dashboard', icon: LayoutDashboard, label: '图表看板' },
];

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

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleChangePwd = async () => {
    setPwdMsg('');
    setPwdBusy(true);
    try {
      await changePassword(oldPwd, newPwd);
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
      await changeUsername(newName);
      setNameMsg('用户名已修改，请重新登录后生效');
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
        {navItems.map((item) => (
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
    </aside>
  );
}
