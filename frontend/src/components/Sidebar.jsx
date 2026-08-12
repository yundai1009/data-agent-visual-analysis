/* =============================================================================
 * 文件：frontend/src/components/Sidebar.jsx —— 全局侧边栏组件
 * 层级：被 App.jsx 在全局布局中渲染，所有页面都能看到（非页面级组件）
 * 功能：
 *   1. 导航菜单：根据用户角色动态显示入口（管理员额外显示「管理后台」）
 *   2. 当前用户展示：读取 user 对象，展示用户名首字 + 在线状态小圆点
 *   3. 意见反馈：点击弹出 Modal，调 api.js 的 submitFeedback 提交到后端
 *   4. 退出登录：调 AppContext 的 logout() 清空状态 → navigate('/login')
 *   5. 侧边栏折叠/展开：由父组件传入 collapsed + onToggle 控制宽度动画
 * 依赖：
 *   - useApp() —— 读取 user（用户名/角色）、调用 logout()
 *   - api.js submitFeedback() —— 提交反馈到后端 /feedback
 *   - react-router-dom NavLink + useNavigate —— 导航高亮与路由跳转
 * ============================================================================= */
import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { Database, Zap, BarChart3, LayoutDashboard, Shield, ChevronLeft, ChevronRight, LogOut, X, UserRoundPen, MessageSquareHeart } from 'lucide-react';
import { useApp } from '../AppContext';
import { submitFeedback } from '../api';

const navItems = [
  { to: '/data', icon: Database, label: '数据管理' },
  { to: '/analysis', icon: Zap, label: '智能分析' },
  { to: '/report', icon: BarChart3, label: '报表历史' },
  { to: '/dashboard', icon: LayoutDashboard, label: '图表看板' },
  { to: '/account', icon: UserRoundPen, label: '账号设置' },
];
// 管理员专属入口：仅 admin 角色显示（权限判断写在 JSX 渲染处）
const adminNav = { to: '/admin', icon: Shield, label: '管理后台' };

// Sidebar 侧边栏组件
// 入参 props：collapsed（boolean）= 是否收起（仅显示图标）；onToggle（回调）= 点击折叠按钮触发
// 业务定位：App.jsx 在所有页面左侧固定渲染，承载导航、用户信息、反馈、登出四个功能
export default function Sidebar({ collapsed, onToggle }) {
  const navigate = useNavigate();
  const { user, logout } = useApp();
  // 意见反馈：弹窗状态（评分 + 文字 + 提示信息 + loading）
  const [fbOpen, setFbOpen] = useState(false);
  const [fbScore, setFbScore] = useState(5);
  const [fbText, setFbText] = useState('');
  const [fbMsg, setFbMsg] = useState('');
  const [fbBusy, setFbBusy] = useState(false);

  // 提交反馈：调用后端 /feedback 接口，成功后 1.2 秒自动关闭弹窗（让用户看清提示）
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

  // 退出登录：清空全局状态（AppContext.logout 清 localStorage + 内存态）→ 跳转登录页
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
      {/* 导航项渲染：navItems + 管理员入口（条件拼接）*/}
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

      {/* User + Toggle 底部区域：用户信息、反馈入口、退出、折叠 */}
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

        {/* 意见反馈（C） */}
        <button
          onClick={() => { setFbOpen(true); setFbMsg(''); setFbText(''); }}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title="意见反馈"
        >
          <MessageSquareHeart className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">意见反馈</span>}
        </button>

        <button
          onClick={handleLogout}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="退出登录"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="ml-2 text-xs">退出</span>}
        </button>

        <button
          onClick={onToggle}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-all"
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

          {/* 意见反馈弹窗：用 createPortal 渲染到 document.body 上层，
              避免被 aside 的 overflow-hidden 裁剪 */}
      {fbOpen && createPortal(
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
      , document.body)}


    </aside>
  );
}
