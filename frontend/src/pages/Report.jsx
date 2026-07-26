import { useState } from 'react';
import { Download, DownloadCloud, Sparkles, Clock } from 'lucide-react';

const mockData = [
  { city: '北京', revenue: 12389, orders: 1204, growth: '+12.4%' },
  { city: '上海', revenue: 9847, orders: 987, growth: '+8.7%' },
  { city: '广州', revenue: 7214, orders: 654, growth: '-2.1%' },
  { city: '深圳', revenue: 5623, orders: 521, growth: '+15.3%' },
  { city: '杭州', revenue: 4120, orders: 398, growth: '+6.8%' },
  { city: '成都', revenue: 3280, orders: 312, growth: '+4.2%' },
];

const maxRevenue = Math.max(...mockData.map((d) => d.revenue));

const bars = [
  { label: '北京', value: 12389, pct: 80 },
  { label: '上海', value: 9847, pct: 63 },
  { label: '广州', value: 7214, pct: 46 },
  { label: '深圳', value: 5623, pct: 36 },
  { label: '杭州', value: 4120, pct: 26 },
  { label: '成都', value: 3280, pct: 20 },
];

export default function Report({ loading }) {
  const [tab, setTab] = useState('table');

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-7">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">报表查看</h1>
          <p className="text-xs text-gray-400 mt-1">AI 自动生成的智能分析报告</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-indigo-50 text-indigo-600 border border-indigo-200">
            <Sparkles className="w-3 h-3" /> AI 生成
          </span>
          <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200 font-mono">
            <Clock className="w-3 h-3" /> 1.2 秒
          </span>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-5 text-center">
          <div className="flex items-center justify-center gap-3 mb-3">
            <svg className="w-5 h-5 text-indigo-500 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
            <span className="text-sm text-gray-500">AI 正在分析数据，请稍候…</span>
          </div>
          <div className="max-w-md mx-auto space-y-2">
            <div className="h-3 bg-gray-100 rounded animate-pulse w-3/4" />
            <div className="h-3 bg-gray-100 rounded animate-pulse w-1/2" />
            <div className="h-3 bg-gray-100 rounded animate-pulse w-5/6" />
          </div>
        </div>
      )}

      {/* Chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-medium text-gray-700">各城市销售额分布</span>
          <span className="text-xs text-gray-400">数据集: sales_2024.csv</span>
        </div>
        <div className="flex items-end justify-around h-56 gap-3 px-2">
          {bars.map((bar) => (
            <div key={bar.label} className="flex-1 flex flex-col items-center gap-1.5">
              <span className="text-xs text-gray-400 font-mono">{bar.value.toLocaleString()}</span>
              <div
                className="w-full rounded-t-lg bg-gradient-to-t from-indigo-500 to-indigo-400 hover:from-indigo-600 hover:to-indigo-500 transition-all cursor-pointer"
                style={{ height: `${bar.pct}%` }}
              />
              <span className="text-xs text-gray-500">{bar.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recommendation */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mt-4">
        <div className="flex items-center gap-2 mb-2.5">
          <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
          <span className="text-xs font-semibold text-gray-500">推荐依据</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-600 text-xs border border-indigo-200">字段「地区」为分类字段，适合做 X 轴</span>
          <span className="px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-600 text-xs border border-indigo-200">「销售额」为数值字段，适合聚合统计</span>
          <span className="px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-600 text-xs border border-indigo-200">需求包含占比语义，优先推荐柱状图</span>
        </div>
      </div>

      {/* Tabs: table / conclusion / trace */}
      <div className="bg-white rounded-xl border border-gray-200 mt-5 overflow-hidden">
        <div className="flex items-center gap-6 px-5 pt-3.5 border-b border-gray-100">
          {['table', 'conclusion', 'trace'].map((t) => (
            <span
              key={t}
              className={`pb-3 text-sm cursor-pointer transition-all ${
                tab === t ? 'text-gray-900 font-medium border-b-2 border-gray-900' : 'text-gray-400 hover:text-gray-600'
              }`}
              onClick={() => setTab(t)}
            >
              {{ table: '数据表', conclusion: '分析结论', trace: '决策记录' }[t]}
            </span>
          ))}
        </div>

        {tab === 'table' && (
          <div className="overflow-auto max-h-56">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b border-gray-100">
                  <th className="text-left px-5 py-3 font-medium">城市</th>
                  <th className="text-left px-5 py-3 font-medium">销售额</th>
                  <th className="text-left px-5 py-3 font-medium">订单数</th>
                  <th className="text-left px-5 py-3 font-medium">增长率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {mockData.map((d) => (
                  <tr key={d.city} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-2.5">{d.city}</td>
                    <td className="px-5 py-2.5 font-mono">{d.revenue.toLocaleString()}</td>
                    <td className="px-5 py-2.5 font-mono">{d.orders}</td>
                    <td className={`px-5 py-2.5 font-mono ${d.growth.startsWith('+') ? 'text-emerald-600' : 'text-amber-600'}`}>{d.growth}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'conclusion' && (
          <div className="px-5 py-4 text-sm text-gray-600 leading-relaxed space-y-2">
            <p>📌 基于上传数据生成「柱状图」，原始数据共 2,847 行、12 列。</p>
            <p>📊 分析需求：按工作经验要求统计各岗位的平均薪资占比。</p>
            <p>🔍 关键发现：</p>
            <ul className="list-disc list-inside space-y-1 text-gray-500">
              <li>「北京」地区销售额最高，达 12,389，领先其他城市约 26%</li>
              <li>「深圳」增长率最高（+15.3%），市场潜力较大</li>
              <li>「广州」出现小幅下滑（-2.1%），建议关注</li>
            </ul>
          </div>
        )}

        {tab === 'trace' && (
          <div className="divide-y divide-gray-100 px-5 py-3">
            {[
              { step: '1', title: 'LLM 意图识别', desc: '已将自然语言解析为结构化报表意图', status: 'done' },
              { step: '2', title: '字段白名单校验', desc: '所有字段均在数据画像范围内，校验通过', status: 'done' },
              { step: '3', title: '数据聚合计算', desc: '按地区分组对销售额执行求和聚合', status: 'done' },
              { step: '✓', title: '报表生成完成', desc: '生成柱状图 + 数据表 + 分析结论', status: 'success' },
            ].map((item) => (
              <div key={item.title} className="flex gap-3 py-2.5">
                <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  item.status === 'success' ? 'bg-emerald-100 text-emerald-600' : 'bg-indigo-100 text-indigo-600'
                }`}>
                  {item.step}
                </span>
                <div>
                  <p className="text-sm text-gray-700">{item.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Export */}
      <div className="flex gap-3 justify-end mt-4">
        <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">
          <Download className="w-3.5 h-3.5" /> 导出 HTML 报告
        </button>
        <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">
          <DownloadCloud className="w-3.5 h-3.5" /> 导出 JSON 数据
        </button>
      </div>
    </div>
  );
}
