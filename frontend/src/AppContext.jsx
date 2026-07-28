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
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
