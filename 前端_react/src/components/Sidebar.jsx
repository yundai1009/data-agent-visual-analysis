import { useState } from 'react'

const nav = [
  {
    key: 'data', label: '数据管理',
    icon: 'M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7C5 4 4 5 4 7zM8 3v3m8-3v3M4 11h16',
  },
  {
    key: 'analysis', label: '智能分析',
    icon: 'M13 10V3L4 14h7v7l9-11h-7z',
  },
  {
    key: 'result', label: '报表历史',
    icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
  },
]

function NavItem({ item, active, onClick, collapsed }) {
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm cursor-pointer transition-all duration-150 relative ${
        active
          ? 'bg-accent-light text-accent font-medium'
          : 'text-gray-500 hover:bg-gray-100 hover:text-gray-600'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      {active && !collapsed && (
        <span className="absolute left-0 top-2 bottom-2 w-[3px] bg-accent rounded-r" />
      )}
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d={item.icon} />
      </svg>
      {!collapsed && <span className="sidebar-text truncate">{item.label}</span>}
    </div>
  )
}

export default function Sidebar({ active, onChange }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={`bg-white border-r border-gray-200 flex flex-col shrink-0 transition-all duration-200 relative ${
        collapsed ? 'w-14' : 'w-48'
      }`}
    >
      {/* 品牌区 */}
      <div className="h-14 flex items-center gap-2.5 px-3 border-b border-gray-100">
        <div className="w-7 h-7 rounded-lg bg-gray-600 text-white flex items-center justify-center text-[10px] font-bold shrink-0">
          DA
        </div>
        {!collapsed && (
          <div className="sidebar-text overflow-hidden transition-opacity">
            <p className="text-xs font-semibold text-gray-600">数据助手</p>
            <p className="text-[10px] text-gray-400 -mt-0.5">自助分析平台</p>
          </div>
        )}
      </div>

      {/* 导航 */}
      <nav className="flex-1 p-2 space-y-0.5 mt-1">
        {nav.map(item => (
          <NavItem
            key={item.key}
            item={item}
            active={active === item.key}
            onClick={() => onChange(item.key)}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* 底部用户 */}
      <div className="p-2 border-t border-gray-100">
        <div className={`flex items-center gap-2 px-3 py-2 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-7 h-7 rounded-lg bg-gray-100 text-gray-500 flex items-center justify-center text-xs font-medium shrink-0">
            云
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-600 truncate">云端用户</p>
            </div>
          )}
          <span className="pulse-dot shrink-0" />
        </div>
      </div>

      {/* 折叠按钮 */}
      <div className="absolute -right-3 top-1/2 -translate-y-1/2 z-10">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-6 h-6 rounded-md border border-gray-200 bg-white flex items-center justify-center text-gray-400 hover:text-accent hover:border-accent transition-all cursor-pointer"
        >
          <svg className={`w-3 h-3 transition-transform duration-200 ${collapsed ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      </div>
    </aside>
  )
}
