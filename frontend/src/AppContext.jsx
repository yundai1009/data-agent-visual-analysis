import { createContext, useContext, useState } from 'react';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [dataset, setDataset] = useState(null);
  const [report, setReport] = useState(null);

  return (
    <AppContext.Provider value={{ dataset, setDataset, report, setReport }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
