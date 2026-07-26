import { useState } from 'react';
import { Zap, BarChart3, LineChart, PieChart, ScatterChart, Table, Layers } from 'lucide-react';

const chartTypes = [
  { id: 'bar', icon: BarChart3, label: '柱状图' },
  { id: 'line', icon: LineChart, label: '折线图' },
  { id: 'pie', icon: PieChart, label: '饼图' },
  { id: 'scatter', icon: ScatterChart, label: '散点图' },
  { id: 'heatmap', icon: Layers, label: '热力图' },
  { id: 'table', icon: Table, label: '表格' },
  { id: 'stacked', icon: Layers, label: '堆积图' },
];

const templates = [
  { label: '📊 占比分布', text: '按【地区】统计【销售额】占比' },
  { label: '📈 趋势变化', text: '按【月份】统计【销售额】趋势变化' },
  { label: '📊 分组对比', text: '按【地区】分组对比【销售额】平均值' },
  { label: '🔀 交叉分析', text: '按【地区】和【岗位类型】做【销售额】交叉分析' },
];

export default function Analysis({ datasetId }) {
  const [nlInput, setNlInput] = useState('按【工作经验要求】统计各岗位的【平均薪资】占比');
  const [chartType, setChartType] = useState('bar');

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-7">
        <h1 className="text-lg font-semibold text-gray-900">智能分析</h1>
        <p className="text-xs text-gray-400 mt-1">用自然语言描述分析需求，AI 自动生成报表</p>
      </div>

      {/* Input */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4">
          <textarea
            rows={3}
            className="w-full bg-transparent border-0 text-sm text-gray-700 resize-none focus:outline-none placeholder:text-gray-300 leading-relaxed"
            placeholder="输入分析需求，例如：按【地区】统计【销售额】占比…"
            value={nlInput}
            onChange={(e) => setNlInput(e.target.value)}
          />
        </div>
        <div className="flex items-center justify-between px-5 py-3 bg-gray-50/80 border-t border-gray-100">
          <div className="flex gap-1.5 flex-wrap">
            {templates.map((t) => (
              <span
                key={t.label}
                className="px-3 py-1.5 rounded-lg bg-white text-xs text-gray-500 cursor-pointer hover:bg-gray-100 hover:text-gray-700 transition-all border border-gray-200"
                onClick={() => setNlInput(t.text)}
              >
                {t.label}
              </span>
            ))}
          </div>
          <button className="flex items-center gap-2 px-5 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 transition-all active:scale-[.98]">
            <Zap className="w-4 h-4" />开始分析
          </button>
        </div>
      </div>

      {/* Chart type */}
      <div className="mt-6">
        <p className="text-xs font-semibold text-gray-500 mb-3">图表类型</p>
        <div className="grid grid-cols-7 gap-2">
          {chartTypes.map((ct) => {
            const Icon = ct.icon;
            const active = chartType === ct.id;
            return (
              <div
                key={ct.id}
                className={`rounded-xl p-3 text-center cursor-pointer transition-all ${
                  active
                    ? 'border-2 border-indigo-500 bg-indigo-50'
                    : 'border border-gray-200 hover:border-indigo-300 hover:bg-gray-50'
                }`}
                onClick={() => setChartType(ct.id)}
              >
                <Icon className={`w-6 h-6 mx-auto mb-1 ${active ? 'text-indigo-500' : 'text-gray-300'}`} />
                <p className={`text-xs ${active ? 'text-indigo-600 font-medium' : 'text-gray-500'}`}>{ct.label}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Config fields */}
      <div className="grid grid-cols-4 gap-3 mt-6">
        {['X 轴', 'Y 轴', '分组字段', '聚合方式'].map((label, i) => (
          <div key={label}>
            <label className="text-xs text-gray-400 mb-1.5 block">{label}</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-indigo-400 focus:bg-white">
              <option>{['地区', '销售额', '无', '求和'][i]}</option>
              <option>{['月份', '订单数', '岗位类型', '平均值'][i]}</option>
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}
