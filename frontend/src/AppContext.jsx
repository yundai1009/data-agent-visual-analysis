import { createContext, useContext, useState } from 'react';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [dataset, setDataset] = useState(null);       // { 数据集ID, 文件名, 行数, 数据画像 }
  const [report, setReport] = useState(null);          // generateReport 返回
  const [loading, setLoading] = useState(false);

  return (
    <AppContext.Provider value={{ dataset, setDataset, report, setReport, loading, setLoading }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
