import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import PageData from './components/PageData'
import PageAnalysis from './components/PageAnalysis'
import PageResult from './components/PageResult'

export default function App() {
  const [page, setPage] = useState('data')

  // 监听跨页面导航（如分析页→报表页）
  useEffect(() => {
    const handler = (e) => setPage(e.detail)
    window.addEventListener('nav', handler)
    return () => window.removeEventListener('nav', handler)
  }, [])

  return (
    <div className="flex h-screen">
      <Sidebar active={page} onChange={setPage} />
      <main className="flex-1 overflow-auto bg-gray-50">
        <div key={page} className="page-enter">
          {page === 'data' && <PageData />}
          {page === 'analysis' && <PageAnalysis />}
          {page === 'result' && <PageResult />}
        </div>
      </main>
    </div>
  )
}
