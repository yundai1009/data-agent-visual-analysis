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
      className={`bg-white border-r border-gray-200 flex flex-col shrink-0 transition-all duration-250 ease-in-out overflow-hidden ${
        collapsed ? 'w-14' : 'w-52'
      }`}
      style={{ boxShadow: '1px 0 4px rgba(0,0,0,.02)' }}
    >
      {/* Brand */}
      <div className="h-16 flex items-center gap-2.5 px-3 border-b border-gray-100 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-gray-900 text-white flex items-center justify-center text-xs font-bold shrink-0">
          DA
        </div>
        <div className={`transition-opacity duration-200 overflow-hidden ${collapsed ? 'opacity-0 w-0' : 'opacity-100'}`}>
          <p className="text-sm font-semibold text-gray-900 whitespace-nowrap">数据助手</p>
          <p className="text-xs text-gray-400 leading-tight -mt-0.5 whitespace-nowrap">自助分析平台</p>
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
                  ? 'bg-accent-soft/80 text-accent font-medium'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-[3px] bg-accent-soft0 rounded-r-[3px]" />
                )}
                <item.icon className="w-4 h-4 shrink-0" />
                <span className={`transition-opacity duration-200 whitespace-nowrap ${collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'}`}>
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* User + Toggle */}
      <div className="p-2 border-t border-gray-100 space-y-1">
        <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg">
          <div className="w-7 h-7 rounded-lg bg-gray-100 flex items-center justify-center text-xs text-gray-500 shrink-0">
            {(user?.username || '云').slice(0, 1)}
          </div>
          <div className={`transition-opacity duration-200 ${collapsed ? 'opacity-0 w-0' : 'opacity-100'}`}>
            <p className="text-xs font-medium text-gray-700 whitespace-nowrap">{user?.username || '未登录'}</p>
          </div>
          <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0 ml-auto" />
        </div>

        <button
          onClick={handleLogout}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all"
          title="登出"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">登出</span>}
        </button>

        <button
          onClick={onToggle}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-all"
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  );
}
