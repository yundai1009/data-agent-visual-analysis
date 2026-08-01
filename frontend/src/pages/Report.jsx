import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Download, DownloadCloud, Sparkles, ChevronLeft, ChevronRight } from 'lucide-react';
import { useApp } from '../AppContext';
import { listReports, getReport, deleteReport } from '../api';
import EChartsChart from '../components/EChartsChart';

export default function Report() {
  const navigate = useNavigate();
  const { addReport } = useApp();
  const [reportMeta, setReportMeta] = useState([]); // [{报表ID, 标题, 图表类型}]
  const [currentIndex, setCurrentIndex] = useState(0);
  const [localReport, setLocalReport] = useState(null);
  const [tab, setTab] = useState('conclusion');

  // 挂载时：先读 sessionStorage 的刚生成报表，再拉后端历史列表
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listReports(50);
        const items = res?.报表列表 || [];
        if (cancelled) return;
        setReportMeta(items);
        // 若本地没有当前报表，从 sessionStorage 恢复刚生成的
        const cached = sessionStorage.getItem('report_cache');
        if (cached) {
          const parsed = JSON.parse(cached);
          sessionStorage.removeItem('report_cache');
          setLocalReport(parsed);
          addReport(parsed); // 同步到前端缓存
        } else if (items.length > 0) {
          const detail = await getReport(items[0].报表ID);
          if (!cancelled && detail?.报表) setLocalReport(detail.报表);
        }
      } catch { /* 后端不可用时静默 */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // 翻页时从后端拉详情
  const switchTo = async (index) => {
    if (index < 0 || index >= reportMeta.length) return;
    setCurrentIndex(index);
    try {
      const detail = await getReport(reportMeta[index].报表ID);
      if (detail?.报表) setLocalReport(detail.报表);
    } catch { /* ignore */ }
  };

  const prevReport = () => switchTo(currentIndex - 1);
  const nextReport = () => switchTo(currentIndex + 1);

  // 清空历史：删除后端全部报表
  const handleClearHistory = async () => {
    if (reportMeta.length === 0) return;
    for (const item of reportMeta) {
      try { await deleteReport(item.报表ID); } catch { /* ignore */ }
    }
    setReportMeta([]);
    setLocalReport(null);
    localStorage.removeItem('reports_cache');
  };

  const report = localReport;

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
  const recommendations = report.推荐说明?.理由 || [];
  const riskWarnings = report.风险提示 || [];
  const trace = report['Agent Trace'] || report.Agent_Trace || [];
  const conclusion = report.结论 || '';
  const chartTypeLabel = report.图表类型 || '柱状图';
  const chartTypeKey = chartConfig.类型 || 'bar';
  const intentSource = report.意图来源 || 'AI';
  const exportData = report.导出数据 || {};
  const dataProfile = report.数据画像 || {};

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-7">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">报表查看</h1>
          <p className="text-xs text-gray-400 mt-1">
            AI 自动生成的智能分析报告
            {dataProfile.行数 ? ` · 数据集共 ${dataProfile.行数} 行 ${dataProfile.列数} 列` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* 历史报表导航 */}
          {reportMeta.length > 1 && (
            <div className="flex items-center gap-1 mr-2">
              <button onClick={prevReport} disabled={currentIndex === 0}
                className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronLeft className="w-4 h-4 text-gray-500" />
              </button>
              <span className="text-xs text-gray-400 select-none">{currentIndex + 1} / {reportMeta.length}</span>
              <button onClick={nextReport} disabled={currentIndex >= reportMeta.length - 1}
                className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronRight className="w-4 h-4 text-gray-500" />
              </button>
              <button onClick={handleClearHistory}
                className="ml-2 text-xs text-gray-400 hover:text-red-500 transition-colors">
                清空
              </button>
            </div>
          )}
          <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-indigo-50 text-indigo-600 border border-indigo-200">
            <Sparkles className="w-3 h-3" /> {intentSource === 'LLM' ? 'AI 生成' : intentSource === '规则' ? '规则匹配' : '自动'}
          </span>
          <span className="px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200">{chartTypeLabel}</span>
        </div>
      </div>

      {/* ECharts Chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {chartTypeKey === 'table' ? (
          <div className="text-sm text-gray-400 text-center py-8">
            表格类数据请在下方「数据表」Tab 中查看
          </div>
        ) : (
          <EChartsChart key={report._historyId || currentIndex} chartType={chartTypeKey} chartConfig={chartConfig} height={360} />
        )}
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

      {/* 风险提示 */}
      {riskWarnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mt-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-amber-600 text-xs font-semibold">⚠ 注意事项</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {riskWarnings.map((w, i) => (
              <span key={i} className="px-2.5 py-1 rounded-full bg-amber-100 text-amber-700 text-xs border border-amber-200">{w}</span>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-gray-200 mt-5 overflow-hidden">
        <div className="flex items-center gap-6 px-5 pt-3.5 border-b border-gray-100">
          {['conclusion', 'table', 'trace'].map((t) => (
            <span key={t}
              className={`pb-3 text-sm cursor-pointer transition-all ${tab === t ? 'text-gray-900 font-medium border-b-2 border-gray-900' : 'text-gray-400 hover:text-gray-600'}`}
              onClick={() => setTab(t)}>
              {{ conclusion: '分析结论', table: '数据表', trace: '决策记录' }[t]}
            </span>
          ))}
        </div>

        {tab === 'conclusion' && (
          <div className="px-5 py-4 text-sm text-gray-600 leading-relaxed">
            {conclusion ? <div className="whitespace-pre-wrap">{conclusion}</div> : <p className="text-gray-400">暂无结论</p>}
          </div>
        )}

        {tab === 'table' && (
          <div className="overflow-auto max-h-56">
            {chartConfig.数据?.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-400 border-b border-gray-100">
                    {Object.keys(chartConfig.数据[0]).map((k) => (
                      <th key={k} className="text-left px-5 py-3 font-medium">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {chartConfig.数据.map((row, i) => (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="px-5 py-2.5 font-mono">{String(v ?? '')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-sm text-gray-400 text-center py-8">暂无数据</p>}
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
            )) : <p className="text-sm text-gray-400 text-center py-4">暂无决策记录</p>}
          </div>
        )}
      </div>

      {/* Export + 继续分析 */}
      <div className="flex gap-3 justify-end mt-4">
        <button
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-all"
          onClick={() => navigate('/analysis')}
        >
          继续分析
        </button>
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
