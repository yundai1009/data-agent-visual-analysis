import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Download, DownloadCloud, Sparkles, Loader2 } from 'lucide-react';
import { useApp } from '../AppContext';
import EChartsChart from '../components/EChartsChart';

const CHART_TYPE_LABELS = {
  bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图',
  heatmap: '热力图', stacked_bar: '堆积图', area: '面积图',
  radar: '雷达图', histogram: '直方图', auto: '自动', table: '表格',
};

export default function Report() {
  const navigate = useNavigate();
  const { report, loading } = useApp();
  const [tab, setTab] = useState('conclusion');

  if (!report) {
    return (
      <div className="p-8 max-w-5xl mx-auto text-center">
        <p className="text-gray-400 text-sm mb-4">暂无报表数据</p>
        <button className="px-5 py-2 rounded-lg bg-gray-900 text-white text-sm hover:bg-gray-800 transition-all" onClick={() => navigate('/analysis')}>
          前往分析
        </button>
      </div>
    );
  }

  const chartConfig = report.图表配置 || {};
  const chartData = chartConfig.数据 || [];
  const recommendations = report.推荐说明?.理由 || [];
  const trace = report['Agent Trace'] || report.Agent_Trace || [];
  const conclusion = report.结论 || '';
  const chartTypeLabel = report.图表类型 || '柱状图';
  const chartTypeKey = chartConfig.类型 || 'bar';
  const intentSource = report.意图来源 || 'AI';
  const exportData = report.导出数据 || {};

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
            <Sparkles className="w-3 h-3" /> {intentSource === 'LLM' ? 'AI 生成' : intentSource === '规则' ? '规则匹配' : '自动'}
          </span>
          <span className="px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200">{chartTypeLabel}</span>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-5 text-center">
          <div className="flex items-center justify-center gap-3 mb-3">
            <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
            <span className="text-sm text-gray-500">AI 正在分析数据，请稍候…</span>
          </div>
          <div className="max-w-md mx-auto space-y-2">
            <div className="h-3 bg-gray-100 rounded animate-pulse w-3/4" />
            <div className="h-3 bg-gray-100 rounded animate-pulse w-1/2" />
            <div className="h-3 bg-gray-100 rounded animate-pulse w-5/6" />
          </div>
        </div>
      )}

      {/* ECharts Chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <EChartsChart key={report.报表ID || 'chart'} chartType={chartTypeKey} chartConfig={chartConfig} height={360} />
      </div>

      {/* Recommendation */}
      {recommendations.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 mt-4">
          <div className="flex items-center gap-2 mb-2.5">
            <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
            <span className="text-xs font-semibold text-gray-500">推荐依据</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {recommendations.map((r, i) => (
              <span key={i} className="px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-600 text-xs border border-indigo-200">{r}</span>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-gray-200 mt-5 overflow-hidden">
        <div className="flex items-center gap-6 px-5 pt-3.5 border-b border-gray-100">
          {['conclusion', 'table', 'trace'].map((t) => (
            <span
              key={t}
              className={`pb-3 text-sm cursor-pointer transition-all ${tab === t ? 'text-gray-900 font-medium border-b-2 border-gray-900' : 'text-gray-400 hover:text-gray-600'}`}
              onClick={() => setTab(t)}
            >
              {{ conclusion: '分析结论', table: '数据表', trace: '决策记录' }[t]}
            </span>
          ))}
        </div>

        {tab === 'conclusion' && (
          <div className="px-5 py-4 text-sm text-gray-600 leading-relaxed">
            {conclusion ? (
              <div className="whitespace-pre-wrap">{conclusion}</div>
            ) : (
              <p className="text-gray-400">暂无结论</p>
            )}
          </div>
        )}

        {tab === 'table' && (
          <div className="overflow-auto max-h-56">
            {chartData.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-400 border-b border-gray-100">
                    {Object.keys(chartData[0]).map((k) => (
                      <th key={k} className="text-left px-5 py-3 font-medium">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {chartData.slice(0, 50).map((row, i) => (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="px-5 py-2.5 font-mono">{String(v ?? '')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-gray-400 text-center py-8">暂无数据</p>
            )}
          </div>
        )}

        {tab === 'trace' && (
          <div className="divide-y divide-gray-100 px-5 py-3">
            {trace.length > 0 ? trace.map((step, i) => (
              <div key={i} className="flex gap-3 py-2.5">
                <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  step.状态 === '成功' || step.状态 === '完成' ? 'bg-emerald-100 text-emerald-600' : 'bg-indigo-100 text-indigo-600'
                }`}>
                  {step.状态 === '成功' || step.状态 === '完成' ? '✓' : i + 1}
                </span>
                <div>
                  <p className="text-sm text-gray-700">{step.步骤 || step.说明 || `步骤 ${i + 1}`}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{step.说明 || step.理由 || ''}</p>
                </div>
              </div>
            )) : (
              <p className="text-sm text-gray-400 text-center py-4">暂无决策记录</p>
            )}
          </div>
        )}
      </div>

      {/* Export */}
      <div className="flex gap-3 justify-end mt-4">
        {exportData.HTML && (
          <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => {
            const blob = new Blob([exportData.HTML], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'report.html'; a.click();
          }}>
            <Download className="w-3.5 h-3.5" /> 导出 HTML 报告
          </button>
        )}
        {exportData.JSON && (
          <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => {
            const blob = new Blob([exportData.JSON], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'report.json'; a.click();
          }}>
            <DownloadCloud className="w-3.5 h-3.5" /> 导出 JSON 数据
          </button>
        )}
      </div>
    </div>
  );
}
