import { useState } from 'react'

const bars = [
  { label: '北京', value: 12389, pct: 80 },
  { label: '上海', value: 9847, pct: 63 },
  { label: '广州', value: 7214, pct: 46 },
  { label: '深圳', value: 5623, pct: 36 },
  { label: '杭州', value: 4102, pct: 26 },
  { label: '成都', value: 3210, pct: 20 },
]

const tableData = [
  { city: '北京', sales: '12,389', orders: '1,204', growth: '+12.4%', growthCls: 'text-emerald-600' },
  { city: '上海', sales: '9,847', orders: '987', growth: '+8.7%', growthCls: 'text-emerald-600' },
  { city: '广州', sales: '7,214', orders: '654', growth: '-2.1%', growthCls: 'text-amber-600' },
  { city: '深圳', sales: '5,623', orders: '521', growth: '+15.3%', growthCls: 'text-emerald-600' },
  { city: '杭州', sales: '4,102', orders: '389', growth: '+6.8%', growthCls: 'text-emerald-600' },
]

const traces = [
  { step: '1', label: 'LLM 意图识别', desc: '已将自然语言解析为结构化报表意图', status: 'done' },
  { step: '2', label: '字段白名单校验', desc: '所有字段均在数据画像范围内，校验通过', status: 'done' },
  { step: '3', label: '数据聚合计算', desc: '按地区分组对销售额执行求和聚合', status: 'done' },
  { step: '✓', label: '报表生成完成', desc: '生成柱状图 + 数据表 + 分析结论', status: 'success' },
]

export default function PageResult() {
  const [tab, setTab] = useState('table')

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* 页面头部 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-gray-600">报表查看</h1>
          <p className="text-xs text-gray-400 mt-1">AI 自动生成的智能分析报告</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-accent bg-accent-light/30 px-2.5 py-1 rounded border border-accent/20">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
            AI 生成
          </span>
          <span className="text-xs text-gray-400 bg-gray-100 px-2.5 py-1 rounded border border-gray-200 font-mono">⏱ 1.2 秒</span>
        </div>
      </div>

      {/* 图表 */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-medium text-gray-600">各城市销售额分布</span>
          <span className="text-xs text-gray-400">数据集: sales_2024.csv</span>
        </div>
        <div className="flex items-end justify-around h-48 gap-3 px-2">
          {bars.map(b => (
            <div key={b.label} className="flex-1 flex flex-col items-center gap-1">
              <span className="text-[10px] text-gray-400 font-mono">{b.value.toLocaleString()}</span>
              <div
                className="w-full rounded-t-md transition-all duration-200 hover:shadow-md hover:shadow-accent/20"
                style={{
                  height: `${b.pct}%`,
                  background: 'linear-gradient(180deg, #6366f1, #4f46e5)',
                  minHeight: 4,
                }}
              />
              <span className="text-[11px] text-gray-500">{b.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 推荐依据 */}
      <div className="card p-4 mt-4">
        <div className="flex items-center gap-1.5 mb-2.5">
          <svg className="w-4 h-4 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
          <span className="text-xs font-semibold text-gray-500">推荐依据</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {['字段「地区」为分类字段，适合做 X 轴', '「销售额」为数值字段，适合聚合统计', '需求包含占比语义，优先推荐柱状图'].map((r, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full bg-accent-light/30 text-accent text-xs border border-accent/15">{r}</span>
          ))}
        </div>
      </div>

      {/* 选项卡 */}
      <div className="card mt-5">
        <div className="flex items-center gap-5 px-5 pt-3.5 border-b border-gray-100">
          {['table', 'conclusion', 'trace'].map(t => (
            <span
              key={t}
              className={`text-sm cursor-pointer pb-3 transition-all ${
                tab === t ? 'text-gray-600 font-medium border-b-2 border-gray-600' : 'text-gray-400 hover:text-gray-500'
              }`}
              onClick={() => setTab(t)}
            >
              {t === 'table' ? '数据表' : t === 'conclusion' ? '分析结论' : '决策记录'}
            </span>
          ))}
        </div>

        {/* 数据表 */}
        {tab === 'table' && (
          <div className="overflow-auto max-h-48">
            <table className="w-full text-sm">
              <thead><tr className="text-xs text-gray-400 border-b border-gray-100"><th className="text-left px-5 py-3 font-medium">城市</th><th className="text-left px-5 py-3 font-medium">销售额</th><th className="text-left px-5 py-3 font-medium">订单数</th><th className="text-left px-5 py-3 font-medium">增长率</th></tr></thead>
              <tbody className="divide-y divide-gray-50">
                {tableData.map(r => (
                  <tr key={r.city} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-2.5">{r.city}</td>
                    <td className="px-5 py-2.5 font-mono text-xs">{r.sales}</td>
                    <td className="px-5 py-2.5 font-mono text-xs">{r.orders}</td>
                    <td className={`px-5 py-2.5 font-mono text-xs ${r.growthCls}`}>{r.growth}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 结论 */}
        {tab === 'conclusion' && (
          <div className="px-5 py-4 text-sm text-gray-500 leading-relaxed space-y-2">
            <p>📌 基于上传数据生成「柱状图」，原始数据共 2,847 行、12 列。</p>
            <p>📊 分析需求：按工作经验要求统计各岗位的平均薪资占比。</p>
            <p>🔍 关键发现：</p>
            <ul className="list-disc list-inside space-y-1 text-gray-400">
              <li>「北京」地区销售额最高，达 12,389，领先其他城市约 26%</li>
              <li>「深圳」增长率最高（+15.3%），市场潜力较大</li>
              <li>「广州」出现小幅下滑（-2.1%），建议关注</li>
            </ul>
          </div>
        )}

        {/* 决策记录 */}
        {tab === 'trace' && (
          <div className="divide-y divide-gray-100 px-5 py-3">
            {traces.map(t => (
              <div key={t.step} className="flex gap-3 py-2.5">
                <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  t.status === 'success' ? 'bg-emerald-100 text-emerald-600' : 'bg-accent-light/30 text-accent'
                }`}>{t.step}</span>
                <div><p className="text-sm text-gray-600">{t.label}</p><p className="text-xs text-gray-400 mt-0.5">{t.desc}</p></div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 导出 */}
      <div className="flex gap-3 justify-end mt-4">
        <button className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 transition-all cursor-pointer">📄 导出 HTML 报告</button>
        <button className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 transition-all cursor-pointer">📦 导出 JSON 数据</button>
      </div>
    </div>
  )
}
