import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ErrorBoundary from './components/ErrorBoundary';
import Login from './pages/Login';
import DataManagement from './pages/DataManagement';
import Analysis from './pages/Analysis';
import Report from './pages/Report';
import NotFound from './pages/NotFound';
import { fetchMe } from './api';
import { AppProvider, useApp } from './AppContext';

// 是否强制登录。生产/正式构建默认 true；演示构建（vite --mode demo）注入 false。
// 构建时通过 .env.demo 的 VITE_AUTH_REQUIRED=false 控制，零基础演示无需注册账号。
const AUTH_REQUIRED = import.meta.env.VITE_AUTH_REQUIRED !== 'false';

// 启动时校验残留 token：localStorage 里的 token 可能来自旧实例/已失效
// （实例切换、JWT 密钥变化、过期）。有效 → 刷新用户信息；401 → api.js
// handleAuthExpired 自动登出并跳转登录页，避免用户带着坏 token 卡在报错页。
function AuthBootstrap() {
  const { isAuthed, setAuth } = useApp();
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
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <div
                className="flex h-screen text-gray-900 antialiased"
                style={{
                  background: 'radial-gradient(120% 90% at 85% -10%, rgba(15,76,129,.09), transparent 55%), radial-gradient(90% 70% at -10% 110%, rgba(15,76,129,.05), transparent 50%), #F7F8FA',
                }}
              >
                <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
                <main className="flex-1 overflow-auto">
                  <ErrorBoundary>
                    <Routes>
                      <Route path="/data" element={<ProtectedRoute><DataManagement /></ProtectedRoute>} />
                      <Route path="/analysis" element={<ProtectedRoute><Analysis /></ProtectedRoute>} />
                      <Route path="/report" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                      <Route path="/report/:reportId" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                      <Route path="*" element={<ProtectedRoute><NotFound /></ProtectedRoute>} />
                    </Routes>
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
