import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ErrorBoundary from './components/ErrorBoundary';
import Login from './pages/Login';
import DataManagement from './pages/DataManagement';
import Analysis from './pages/Analysis';
import Report from './pages/Report';
import { AppProvider, useApp } from './AppContext';

// 是否强制登录。生产环境设为 true；本地演示想免登录可改 false。
const AUTH_REQUIRED = true;

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
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <div className="flex h-screen bg-[#F7F8FA] text-gray-900 antialiased">
                <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
                <main className="flex-1 overflow-auto">
                  <ErrorBoundary>
                    <Routes>
                      <Route path="/data" element={<ProtectedRoute><DataManagement /></ProtectedRoute>} />
                      <Route path="/analysis" element={<ProtectedRoute><Analysis /></ProtectedRoute>} />
                      <Route path="/report" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                      <Route path="/report/:reportId" element={<ProtectedRoute><Report /></ProtectedRoute>} />
                      <Route path="*" element={<Navigate to="/data" replace />} />
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
