/* oxlint-disable react/only-export-components -- Context 惯例：Provider 组件 + useApp hook 同文件导出 */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AppContext = createContext(null);

function loadState(key, fallback) {
  try {
    const cached = localStorage.getItem(key);
    return cached ? JSON.parse(cached) : fallback;
  } catch { return fallback; }
}

export function AppProvider({ children }) {
  const [dataset, setDataset] = useState(() => loadState('dataset_cache', null));
  // 认证状态
  const [user, setUser] = useState(() => loadState('user_cache', null));
  const [isAuthed, setIsAuthed] = useState(() => {
    // B18 修复：Safari 隐私模式/localStorage 禁用时 getItem 抛 SecurityError，需 try 包裹
    try { return !!localStorage.getItem('access_token'); } catch { return false; }
  });

  // 一次性清理旧版前端报表缓存（阶段 12 收尾：报表历史一律以服务端为准）
  useEffect(() => {
    localStorage.removeItem('reports_cache');
  }, []);

  // 401 全局登出：token 失效/残留时（api.js handleAuthExpired 触发）
  // 同步清空内存态 → ProtectedRoute 自动重定向登录页
  useEffect(() => {
    const onAuthExpired = () => {
      setUser(null);
      setIsAuthed(false);
      setDataset(null); // 与 api.js 清除 dataset_cache 保持一致，避免旧数据集残留展示
    };
    window.addEventListener('auth:expired', onAuthExpired);
    return () => window.removeEventListener('auth:expired', onAuthExpired);
  }, []);

  // 设置认证状态（登录/注册成功后调用）
  const setAuth = useCallback((token, userInfo) => {
    try {
      if (token) localStorage.setItem('access_token', token);
      if (userInfo) localStorage.setItem('user_cache', JSON.stringify(userInfo));
    } catch { /* localStorage 不可用时忽略，仅本次会话有效 */ }
    if (userInfo) setUser(userInfo);
    setIsAuthed(!!token);
  }, []);

  // 登出
  const logout = useCallback(() => {
    try {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user_cache');
      localStorage.removeItem('dataset_cache'); // B5 修复：登出清数据集缓存，防下个账号看到残留数据
    } catch { /* ignore */ }
    setUser(null);
    setIsAuthed(false);
    setDataset(null);
  }, []);

  useEffect(() => {
    if (dataset) localStorage.setItem('dataset_cache', JSON.stringify(dataset));
  }, [dataset]);

  return (
    <AppContext.Provider value={{
      dataset, setDataset,
      user, isAuthed, setAuth, logout,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
