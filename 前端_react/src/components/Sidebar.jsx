const nav = [
  { key: 'data', label: '数据', icon: 'M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7C5 4 4 5 4 7zM8 3v3m8-3v3M4 11h16' },
  { key: 'analysis', label: '分析', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
  { key: 'result', label: '报表', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
]

function NavItem({ item, active, onClick }) {
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl text-sm cursor-pointer transition-all duration-200 ${
        active
          ? 'bg-indigo-500/15 text-indigo-400 shadow-[inset_0_0_0_1px_rgba(99,102,241,.2)]'
          : 'text-slate-500 hover:bg-indigo-500/8 hover:text-slate-300'
      }`}
    >
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d={item.icon} />
      </svg>
      <span>{item.label}</span>
    </div>
  )
}

export default function Sidebar({ active, onChange }) {
  return (
    <aside className="glass rounded-2xl w-52 flex flex-col shrink-0 shadow-[0_0_0_1px_rgba(99,102,241,.12),0_0_30px_rgba(99,102,241,.06)]" style={{ padding: '16px 10px' }}>
      {/* 品牌 */}
      <div className="flex items-center gap-2.5 px-3 py-2 mb-6">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-400 to-cyan-400 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/30">
          DA
        </div>
        <div>
          <p className="text-sm font-semibold text-white">Data Agent</p>
          <p className="text-[10px] text-slate-500">自助分析平台</p>
        </div>
      </div>

      {/* 导航 */}
      <nav className="flex-1 space-y-1">
        {nav.map(item => (
          <NavItem key={item.key} item={item} active={active === item.key} onClick={() => onChange(item.key)} />
        ))}
      </nav>

      {/* 底部 */}
      <div className="pt-4 border-t border-slate-800/60 space-y-2">
        <div className="flex items-center gap-2.5 px-4 py-2 rounded-xl cursor-not-allowed text-slate-500">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
          <span className="text-xs">暗色模式</span>
        </div>
        <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-xs font-bold text-white">
            Y
          </div>
          <div className="flex-1">
            <p className="text-xs font-medium text-slate-300">yundai</p>
          </div>
          <div className="pulse-dot" />
        </div>
      </div>
    </aside>
  )
}
