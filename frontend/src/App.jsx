import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import DataManagement from './pages/DataManagement';
import Analysis from './pages/Analysis';
import Report from './pages/Report';

export default function App() {
  const [collapsed, setCollapsed] = useState(false);
  const [datasetContext, setDatasetContext] = useState(null);

  return (
    <BrowserRouter>
      <div className="flex h-screen bg-[#F7F8FA] text-gray-900 antialiased">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/data" element={<DataManagement />} />
            <Route path="/analysis" element={<Analysis />} />
            <Route path="/report" element={<Report />} />
            <Route path="*" element={<Navigate to="/data" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
