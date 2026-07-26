import { useState } from 'react'

const templates = {
  '占比分布': '按【地区】统计【销售额】占比',
  '趋势变化': '按【月份】统计【销售额】趋势变化',
  '分组对比': '按【地区】分组对比【销售额】平均值',
  '交叉分析': '按【地区】和【岗位类型】做【销售额】交叉分析',
}

const chartTypes = [
  { label: '柱状图', icon: 'M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z' },
  { label: '折线图', icon: null },
  { label: '饼图', icon: null },
  { label: '散点图', icon: null },
  { label: '热力图', icon: null },
  { label: '表格', icon: null },
  { label: '堆积图', icon: null },
]

export default function PageAnalysis() {
  const [input, setInput] = useState('')
  const [activeChart, setActiveChart] = useState(0)
  const [generating, setGenerating] = useState(false)

  function handleGenerate() {
    setGenerating(true)
    setTimeout(() => {
      setGenerating(false)
      // 跳转到报表页 — 实际应用中用 router
      window.selectedTab = 'result'
      window.dispatchEvent(new CustomEvent('nav', { detail: 'result' }))
    }, 2000)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-gray-600">智能分析</h1>
        <p className="text-xs text-gray-400 mt-1">用自然语言描述分析需求，AI 自动生成报表</p>
      </div>

      {/* 输入区 */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4">
          <textarea
            rows={3}
            className="w-full bg-transparent border-0 text-sm text-gray-600 resize-none outline-none placeholder:text-gray-300 leading-relaxed"
            placeholder="输入分析需求，例如：按【地区】统计【销售额】占比…"
            value={input}
            onChange={e => setInput(e.target.value)}
          />
        </div>
        <div className="flex items-center justify-between px-5 py-3 bg-gray-50/80 border-t border-gray-100">
          <div className="flex gap-1.5 flex-wrap">
            {Object.entries(templates).map(([label, text]) => (
              <span
                key={label}
                className="px-2.5 py-1.5 rounded-lg bg-white text-xs text-gray-500 cursor-pointer hover:bg-gray-100 hover:text-gray-700 transition-all border border-gray-200"
                onClick={() => setInput(text)}
              >
                {label}
              </span>
            ))}
          </div>
          <button
            onClick={handleGenerate}
            className="h-9 px-4 rounded-lg bg-gray-600 text-white text-sm font-medium hover:bg-gray-700 transition-all cursor-pointer flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            开始分析
          </button>
        </div>
      </div>

      {/* 图表类型 */}
      <div className="mt-5">
        <p className="text-xs font-semibold text-gray-500 mb-3">图表类型</p>
        <div className="grid grid-cols-7 gap-2">
          {chartTypes.map((ct, i) => (
            <div
              key={ct.label}
              className={`rounded-xl p-3 text-center cursor-pointer transition-all ${
                i === activeChart
                  ? 'border-2 border-accent bg-accent-light/30'
                  : 'border border-gray-200 bg-white hover:border-accent/40 hover:shadow-sm'
              }`}
              onClick={() => setActiveChart(i)}
            >
              <div className="flex items-center justify-center h-8 mb-1 text-gray-300">
                {ct.label === '柱状图' && (
                  <div className="flex items-end justify-center gap-0.5 w-full h-full">
                    <div className="w-2 bg-accent rounded-t" style={{ height: '75%' }} />
                    <div className="w-2 bg-accent rounded-t" style={{ height: '45%' }} />
                    <div className="w-2 bg-accent rounded-t" style={{ height: '60%' }} />
                  </div>
                )}
                {ct.label === '折线图' && (
                  <svg className="w-full h-5" viewBox="0 0 60 20"><polyline fill="none" stroke="currentColor" strokeWidth="2" points="2,18 12,10 22,14 32,4 42,8 58,6" /></svg>
                )}
                {ct.label === '饼图' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M12 2A10 10 0 0 0 2 12h10V2Z" fill="currentColor" /></svg>
                )}
                {ct.label === '散点图' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24"><circle cx="8" cy="8" r="2" fill="currentColor" /><circle cx="16" cy="12" r="2" fill="currentColor" /><circle cx="12" cy="18" r="2" fill="currentColor" /></svg>
                )}
                {ct.label === '热力图' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" fill="currentColor" opacity=".6" /><rect x="14" y="3" width="7" height="7" rx="1" fill="currentColor" opacity=".3" /><rect x="3" y="14" width="7" height="7" rx="1" fill="currentColor" opacity=".8" /><rect x="14" y="14" width="7" height="7" rx="1" fill="currentColor" opacity=".4" /></svg>
                )}
                {ct.label === '表格' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24"><path d="M3 4h18v2H3V4zm0 5h18v2H3V9zm0 5h18v2H3v-2zm0 5h18v2H3v-2z" fill="currentColor" /></svg>
                )}
                {ct.label === '堆积图' && (
                  <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" /></svg>
                )}
              </div>
              <p className={`text-xs ${i === activeChart ? 'text-accent font-medium' : 'text-gray-500'}`}>{ct.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* 字段配置 */}
      <div className="grid grid-cols-4 gap-3 mt-5">
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">X 轴</label>
          <select className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-accent/50">
            <option>月份</option><option selected>地区</option><option>工作经验要求</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Y 轴</label>
          <select className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-accent/50">
            <option selected>销售额</option><option>订单数</option><option>平均薪资</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">分组字段</label>
          <select className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-accent/50">
            <option selected>无</option><option>地区</option><option>岗位类型</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">聚合方式</label>
          <select className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-accent/50">
            <option selected>求和</option><option>平均值</option><option>计数</option><option>最大值</option><option>最小值</option>
          </select>
        </div>
      </div>

      {/* loading */}
      {generating && (
        <div className="card p-5 mt-5 text-center">
          <div className="flex items-center justify-center gap-2 mb-3">
            <svg className="w-4 h-4 text-accent animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
            <span className="text-sm text-gray-500">AI 正在分析数据，请稍候…</span>
          </div>
          <div className="max-w-xs mx-auto space-y-1.5">
            <div className="skeleton h-2.5 w-3/4" />
            <div className="skeleton h-2.5 w-1/2" />
            <div className="skeleton h-2.5 w-5/6" />
          </div>
        </div>
      )}
    </div>
  )
}
