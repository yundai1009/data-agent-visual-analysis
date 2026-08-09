import { useState, useEffect, Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ErrorBoundary from './components/ErrorBoundary';
import { fetchMe } from './api';
import { AppProvider, useApp } from './AppContext';

// 页面级懒加载：每个页面独立 chunk，首屏只下载当前页面代码（阶段 27 bundle 优化）
const Login = lazy(() => import('./pages/Login'));
const ShareView = lazy(() => import('./pages/ShareView'));
const DataManagement = lazy(() => import('./pages/DataManagement'));
const Analysis = lazy(() => import('./pages/Analysis'));
const Report = lazy(() => import('./pages/Report'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Admin = lazy(() => import('./pages/Admin'));
const NotFound = lazy(() => import('./pages/NotFound'));

// 懒加载期间的最小兜底（登录/分享页也走同一 Suspense）
function PageFallback() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-sm text-gray-400">加载中…</div>
    </div>
  );
}

// 是否强制登录。生产/正式构建默认 true；演示构建（vite --mode demo）注入 false。
// 构建时通过 .env.demo 的 VITE_AUTH_REQUIRED=false 控制，零基础演示无需注册账号。
const AUTH_REQUIRED = import.meta.env.VITE_AUTH_REQUIRED !== 'false';

// 启动时校验残留 token：localStorage 里的 token 可能来自旧实例/已失效
// （实例切换、JWT 密钥变化、过期）。有效 → 刷新用户信息；401 → api.js
// handleAuthExpired 自动登出并跳转登录页，避免用户带着坏 token 卡在报错页。
function AuthBootstrap() {
  const { isAuthed } = useApp();
  useEffect(() => {
    if (!AUTH_REQUIRED || !isAuthed) return;
    let cancelled = false;
    fetchMe()
      .then((user) => {
        // token 有效：仅刷新本地用户信息缓存，不触碰认证状态
        // （setAuth(null, user) 会把 isAuthed 误置 false 导致误踢出登录页）
        if (!cancelled && user) {
          try {
            localStorage.setItem('user_cache', JSON.stringify(user));
          } catch { /* ignore */ }
        }
      })
      .catch(() => { /* 401 已由 handleAuthExpired 登出；网络错误保持现状 */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

// 路由守卫：未登录访问受保护页面时跳转登录页
function ProtectedRoute({ children }) {
  const { isAuthed } = useApp();
  if (AUTH_REQUIRED && !isAuthed) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <AppProvider>
      <AuthBootstrap />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Suspense fallback={<PageFallback />}><Login /></Suspense>} />
          <Route path="/s/:shareId" element={<Suspense fallback={<PageFallback />}><ShareView /></Suspense>} />
          <Route
            path="/*"
            element={
              <div
                className="flex min-h-[100dvh] text-gray-900 antialiased"
                style={{
                  background: 'radial-gradient(120% 90% at 85% -10%, rgba(15,76,129,.09), transparent 55%), radial-gradient(90% 70% at -10% 110%, rgba(15,76,129,.05), transparent 50%), #F7F8FA',
                }}
              >
                <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:px-4 focus:py-2 focus:rounded-lg focus:bg-accent focus:text-white focus:text-sm">
                  跳到主内容
                </a>
                <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
                <main id="main-content" className="flex-1 overflow-auto">
                  <ErrorBoundary>
                    {/* 懒加载 Suspense 仅覆盖内容区：页面代码未就绪时侧边栏布局常驻 */}
                    <Suspense fallback={<PageFallback />}>
                      <Routes>
                        <Route path="/data" element={<ProtectedRoute><DataManagement /></ProtectedRoute>} />
                        <Route path="/analysis" element={<ProtectedRoute><Analysis /></ProtectedRoute>} />
                        <Route path="/report" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                        <Route path="/report/:reportId" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                        <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                        <Route path="/admin" element={<ProtectedRoute><Admin /></ProtectedRoute>} />
                        <Route path="*" element={<ProtectedRoute><NotFound /></ProtectedRoute>} />
                      </Routes>
                    </Suspense>
                  </ErrorBoundary>
                </main>
              </div>
            }
          />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
