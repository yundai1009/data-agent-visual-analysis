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
  const [isAuthed, setIsAuthed] = useState(() => !!localStorage.getItem('access_token'));

  // 一次性清理旧版前端报表缓存（阶段 12 收尾：报表历史一律以服务端为准）
  useEffect(() => {
    localStorage.removeItem('reports_cache');
  }, []);

  // 设置认证状态（登录/注册成功后调用）
  const setAuth = useCallback((token, userInfo) => {
    if (token) localStorage.setItem('access_token', token);
    if (userInfo) localStorage.setItem('user_cache', JSON.stringify(userInfo));
    if (userInfo) setUser(userInfo);
    setIsAuthed(!!token);
  }, []);

  // 登出
  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_cache');
    setUser(null);
    setIsAuthed(false);
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
