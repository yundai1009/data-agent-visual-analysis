import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Download, DownloadCloud, Sparkles, ChevronLeft, ChevronRight } from 'lucide-react';
import { listReports, getReport, deleteReport } from '../api';
import EChartsChart from '../components/EChartsChart';

export default function Report() {
  const navigate = useNavigate();
  const { reportId } = useParams();
  const [reportMeta, setReportMeta] = useState([]); // [{报表ID, 标题, 图表类型}]
  const [currentIndex, setCurrentIndex] = useState(0);
  const [localReport, setLocalReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('conclusion');
  const [loadError, setLoadError] = useState('');

  // 挂载时：报表状态只来自后端 —— 历史列表 GET /reports/，详情 GET /reports/{id}
  // reportId（路由参数）优先展示指定报表，否则展示最新一张
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await listReports(50);
        const items = res?.报表列表 || [];
        if (cancelled) return;
        setReportMeta(items);
        const targetId = reportId || items[0]?.报表ID;
        if (targetId) {
          const detail = await getReport(targetId);
          if (!cancelled && detail?.报表) {
            setLocalReport(detail.报表);
            const idx = items.findIndex((i) => i.报表ID === targetId);
            if (idx >= 0) setCurrentIndex(idx);
          }
        }
      } catch (e) {
        console.error('报表列表加载失败:', e);
        setLoadError('报表加载失败，请检查后端服务是否可用');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [reportId]);

  // 翻页时从后端拉详情
  const switchTo = async (index) => {
    if (index < 0 || index >= reportMeta.length) return;
    setCurrentIndex(index);
    try {
      const detail = await getReport(reportMeta[index].报表ID);
      if (detail?.报表) setLocalReport(detail.报表);
    } catch (e) {
      console.error('报表详情加载失败:', e);
      setLoadError('报表详情加载失败，请稍后重试');
    }
  };

  const prevReport = () => switchTo(currentIndex - 1);
  const nextReport = () => switchTo(currentIndex + 1);

  // 清空历史：删除后端全部报表；删除失败项保留（不误清 UI），带确认框
  const handleClearHistory = async () => {
    if (reportMeta.length === 0) return;
    if (!window.confirm(`确定删除全部 ${reportMeta.length} 份报表？此操作不可恢复。`)) return;
    const failed = [];
    for (const item of reportMeta) {
      try { await deleteReport(item.报表ID); } catch (e) { failed.push(item.报表ID); console.error('报表删除失败:', item.报表ID, e); }
    }
    if (failed.length > 0) {
      setLoadError(`有 ${failed.length} 份报表删除失败，已保留`);
      setReportMeta(prev => prev.filter(item => !failed.includes(item.报表ID)));
    } else {
      setReportMeta([]);
      setLocalReport(null);
    }
  };

  const report = localReport;

  // 骨架屏（加载中且无数据）
  if (loading && !report) {
    return (
      <div className="p-8 max-w-5xl mx-auto space-y-4">
        <div className="h-6 w-48 bg-gray-200 rounded-lg animate-pulse" />
        <div className="h-[360px] bg-gray-100 rounded-xl animate-pulse" />
        <div className="h-4 w-1/3 bg-gray-200 rounded-lg animate-pulse" />
        <div className="h-3 w-2/3 bg-gray-200 rounded-lg animate-pulse" />
        <div className="h-3 w-1/2 bg-gray-200 rounded-lg animate-pulse" />
      </div>
    );
  }

  if (!report) {
    return (
      <div className="p-8 max-w-5xl mx-auto text-center">
        <p className="text-gray-400 text-sm mb-4">暂无报表数据</p>
        <button className="px-5 py-2 rounded-lg bg-accent text-white text-sm hover:bg-accent-deep transition-all" onClick={() => navigate('/analysis')}>
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
          {loadError && <p className="mt-1.5 text-xs text-red-500">{loadError}</p>}
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
          <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-accent-soft text-accent border border-accent/20">
            <Sparkles className="w-3 h-3" /> {intentSource === 'LLM' ? 'AI 生成' : intentSource === '规则' ? '规则匹配' : '自动'}
          </span>
          <span className="px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200">{chartTypeLabel}</span>
        </div>
      </div>

      {/* ECharts Chart：藏青光晕舞台 */}
      <div className="rounded-xl p-5"
           style={{ background: 'radial-gradient(120% 100% at 50% 0%, #eef3f9 0%, #f8fafc 55%, #f1f5f9 100%)' }}>
        {chartTypeKey === 'table' ? (
          <div className="text-sm text-gray-400 text-center py-8">
            表格类数据请在下方「数据表」Tab 中查看
          </div>
        ) : (
          <EChartsChart key={report._historyId || currentIndex} chartType={chartTypeKey} chartConfig={chartConfig} height={360} />
        )}
      </div>

      {/* 洞察面板：一句话结论 */}
      {conclusion && (
        <div className="mt-4 bg-white rounded-xl p-5"
             style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)', borderLeft: '4px solid var(--color-accent, #0f4c81)' }}>
          <p className="text-xs text-gray-400 font-semibold tracking-wide mb-2">分析结论</p>
          <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">{conclusion}</p>
        </div>
      )}

      {/* 洞察面板：关键发现 */}
      {recommendations.length > 0 && (
        <div className="mt-3 grid sm:grid-cols-2 gap-3">
          {recommendations.slice(0, 4).map((r, i) => (
            <div key={i} className="bg-white rounded-xl p-4"
                 style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)' }}>
              <p className="text-xs font-semibold text-ink mb-1">发现 {i + 1}</p>
              <p className="text-xs text-gray-500 leading-relaxed">{r}</p>
            </div>
          ))}
        </div>
      )}

      {/* 风险提示 */}
      {riskWarnings.length > 0 && (
        <div className="mt-3 rounded-xl p-4 flex gap-3 items-start" style={{ background: '#fef3c7' }}>
          <span className="text-xs font-semibold shrink-0" style={{ color: '#b45309' }}>⚠ 数据提示</span>
          <div className="flex flex-wrap gap-1.5">
            {riskWarnings.map((w, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md"
                    style={{ background: '#fff7ed', color: '#92400e', border: '1px solid #fed7aa' }}>{w}</span>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-gray-200 mt-5 overflow-hidden">
        <div className="flex items-center gap-6 px-5 pt-3.5 border-b border-gray-100">
          {['table', 'trace'].map((t) => (
            <span key={t}
              className={`pb-3 text-sm cursor-pointer transition-all ${tab === t ? 'text-gray-900 font-medium border-b-2 border-accent' : 'text-gray-400 hover:text-gray-600'}`}
              onClick={() => setTab(t)}>
              {{ table: '数据表', trace: '决策记录' }[t]}
            </span>
          ))}
        </div>

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
                  step.状态 === '成功' || step.状态 === '完成' ? 'bg-emerald-100 text-emerald-600' : 'bg-accent-soft text-accent'
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
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
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
