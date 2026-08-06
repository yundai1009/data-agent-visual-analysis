import { NavLink, useNavigate } from 'react-router-dom';
import { Database, Zap, BarChart3, ChevronLeft, ChevronRight, LogOut } from 'lucide-react';
import { useApp } from '../AppContext';

const navItems = [
  { to: '/data', icon: Database, label: '数据管理' },
  { to: '/analysis', icon: Zap, label: '智能分析' },
  { to: '/report', icon: BarChart3, label: '报表历史' },
];

export default function Sidebar({ collapsed, onToggle }) {
  const navigate = useNavigate();
  const { user, logout } = useApp();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };
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
    </aside>
  );
}
