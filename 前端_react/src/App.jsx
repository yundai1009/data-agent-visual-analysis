import { useState } from 'react'
import Sidebar from './components/Sidebar'
import PageData from './components/PageData'
import PageAnalysis from './components/PageAnalysis'
import PageResult from './components/PageResult'

const pages = {
  data: { label: '数据', comp: PageData },
  analysis: { label: '分析', comp: PageAnalysis },
  result: { label: '报表', comp: PageResult },
}

export default function App() {
  const [page, setPage] = useState('data')

  const PageComp = pages[page].comp

  return (
    <div className="h-screen relative overflow-hidden">
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="bg-glow-2" />

      <div className="flex h-full relative z-10 p-3 gap-3">
        <Sidebar active={page} onChange={setPage} />
        <main className="flex-1 overflow-auto pr-1">
          <div key={page} className="page-enter">
            <PageComp />
          </div>
        </main>
      </div>
    </div>
  )
}
