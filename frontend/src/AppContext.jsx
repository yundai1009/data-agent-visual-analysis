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
  // reports: 历史报表列表（最新在前），持久化到 localStorage
  const [reports, setReports] = useState(() => loadState('reports_cache', []));
  // 认证状态
  const [user, setUser] = useState(() => loadState('user_cache', null));
  const [isAuthed, setIsAuthed] = useState(() => !!localStorage.getItem('access_token'));

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

  useEffect(() => {
    localStorage.setItem('reports_cache', JSON.stringify(reports));
  }, [reports]);

  // 添加新报表到列表头部
  const addReport = useCallback((report) => {
    setReports(prev => {
      const id = report.报表ID || Date.now().toString(36);
      return [{ ...report, _historyId: id }, ...prev].slice(0, 50); // 最多保留 50 条
    });
  }, []);

  // 根据 historyId 获取报表
  const getReportById = useCallback((id) => {
    return reports.find(r => r._historyId === id) || null;
  }, [reports]);

  return (
    <AppContext.Provider value={{
      dataset, setDataset,
      reports, setReports, addReport, getReportById,
      user, isAuthed, setAuth, logout,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
