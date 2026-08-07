import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Download, DownloadCloud, Sparkles, ChevronLeft, ChevronRight, AlertTriangle, Share2, Copy, Check, Clock, Link2, X, RotateCcw, GitBranch } from 'lucide-react';
import { listReports, getReport, deleteReport, exportReport, createShare, listShares, revokeShare, replayReport } from '../api';
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
  const [prevTitle, setPrevTitle] = useState(''); // 追问来源报表标题（溯源显示）
  // 分享弹窗状态
  const [showShare, setShowShare] = useState(false);
  const [shareHours, setShareHours] = useState(24);
  const [sharePassword, setSharePassword] = useState('');
  const [shareLinks, setShareLinks] = useState([]);
  const [shareMsg, setShareMsg] = useState('');
  const [copied, setCopied] = useState(false);
  // 历史重放状态
  const [replaying, setReplaying] = useState(false);
  // 分页：是否有更多历史 + 加载更多中
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const PAGE_SIZE = 50;

  // 挂载时：报表状态只来自后端 —— 历史列表 GET /reports/，详情 GET /reports/{id}
  // reportId（路由参数）优先展示指定报表，否则展示最新一张
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await listReports(PAGE_SIZE, 0);
        const items = res?.报表列表 || [];
        if (cancelled) return;
        setReportMeta(items);
        setHasMore(items.length >= PAGE_SIZE);
        const targetId = reportId || items[0]?.报表ID;
        if (targetId) {
          const detail = await getReport(targetId);
          if (!cancelled && detail?.报表) {
            setLocalReport(detail.报表);
            setPrevTitle(detail.上一报表标题 || '');
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
      if (detail?.报表) {
        setLocalReport(detail.报表);
        setPrevTitle(detail.上一报表标题 || '');
      }
    } catch (e) {
      console.error('报表详情加载失败:', e);
      setLoadError('报表详情加载失败，请稍后重试');
    }
  };

  const prevReport = () => switchTo(currentIndex - 1);
  const nextReport = () => switchTo(currentIndex + 1);

  // 加载更多历史报表（追加到列表尾部）
  const handleLoadMore = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await listReports(PAGE_SIZE, reportMeta.length);
      const extra = res?.报表列表 || [];
      setReportMeta((prev) => [...prev, ...extra]);
      setHasMore(extra.length >= PAGE_SIZE);
    } catch (e) {
      setLoadError('加载更多报表失败：' + (e.message || e));
    } finally {
      setLoadingMore(false);
    }
  };

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

  // 导出：Excel / CSV / PDF 走后端端点（带 token），Trace 前端本地生成 Markdown
  const currentReportId = reportMeta[currentIndex]?.报表ID || localReport?._id;
  const handleExport = async (format) => {
    if (!currentReportId) return;
    try {
      const { blob, filename } = await exportReport(currentReportId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`导出 ${format.toUpperCase()} 失败：${e.message || e}`);
    }
  };
  const handleExportTrace = () => {
    if (trace.length === 0) return;
    const lines = [
      `# Agent 决策记录 — ${report.标题 || '数据分析报表'}`,
      '',
      ...trace.map((step, i) => `## ${i + 1}. ${step.步骤 || step.说明 || `步骤 ${i + 1}`}${step.状态 === '成功' || step.状态 === '完成' ? ' ✓' : ''}\n${step.说明 || step.理由 || ''}`),
    ];
    const blob = new Blob([lines.join('\n\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `Agent决策记录-${(report.标题 || '报表').replace(/[\\/:*?"<>|]/g, '_')}.md`; a.click();
    URL.revokeObjectURL(url);
  };

  // 分享：打开弹窗并加载已有链接
  const openShareModal = async () => {
    setShowShare(true);
    setShareMsg('');
    setCopied(false);
    if (!currentReportId) return;
    try {
      const res = await listShares(currentReportId);
      setShareLinks(res?.分享列表 || []);
    } catch (e) {
      setShareMsg('加载分享列表失败：' + (e.message || e));
    }
  };
  const reloadShares = async () => {
    const res = await listShares(currentReportId);
    setShareLinks(res?.分享列表 || []);
  };
  const handleCreateShare = async () => {
    if (!currentReportId) return;
    try {
      const res = await createShare(currentReportId, shareHours, sharePassword.trim());
      setShareMsg(`已生成，有效期 ${shareHours} 小时${res.需密码 ? '，需访问密码' : ''}`);
      setSharePassword('');
      await reloadShares();
    } catch (e) {
      setShareMsg('生成失败：' + (e.message || e));
    }
  };
  const handleRevokeShare = async (shareId) => {
    if (!window.confirm('撤销后链接立即失效，确定？')) return;
    try {
      await revokeShare(currentReportId, shareId);
      await reloadShares();
    } catch (e) {
      setShareMsg('撤销失败：' + (e.message || e));
    }
  };
  const handleCopyShare = async (link) => {
    try {
      await navigator.clipboard.writeText(window.location.origin + link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setShareMsg('复制失败，请手动复制链接');
    }
  };
  const fmtExpire = (iso) => {
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch { return iso; }
  };

  // 历史重放：用原报表参数重新执行分析（复现过程 → 新报表）
  const handleReplay = async () => {
    if (!currentReportId || replaying) return;
    setReplaying(true);
    setLoadError('');
    try {
      const res = await replayReport(currentReportId);
      navigate(`/report/${res.报表ID}`);
    } catch (e) {
      setLoadError('重放失败：' + (e.message || e));
    } finally {
      setReplaying(false);
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
          {report.上一报表ID && (
            <button
              onClick={() => navigate(`/report/${report.上一报表ID}`)}
              className="mt-1.5 flex items-center gap-1 text-xs text-accent hover:underline transition-colors"
              title="查看这份报表追问自哪一份"
            >
              <GitBranch className="w-3 h-3" /> 追问自：{prevTitle || '上一份报表'}
            </button>
          )}
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
              {hasMore && (
                <button onClick={handleLoadMore} disabled={loadingMore}
                  className="ml-2 text-xs text-accent hover:underline transition-colors disabled:opacity-50">
                  {loadingMore ? '加载中…' : '加载更多'}
                </button>
              )}
            </div>
          )}
          <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-accent-soft text-accent border border-accent/20">
            <Sparkles className="w-3 h-3" /> {intentSource === 'LLM' ? 'AI 生成' : intentSource === '规则' ? '规则匹配' : '自动'}
          </span>
          <span className="px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200">{chartTypeLabel}</span>
          <button
            onClick={openShareModal}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-emerald-50 text-emerald-600 border border-emerald-200 hover:bg-emerald-100 transition-all"
            title="生成带权限的分享链接"
          >
            <Share2 className="w-3 h-3" /> 分享
          </button>
          <button
            onClick={handleReplay}
            disabled={replaying}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100 transition-all disabled:opacity-50"
            title="用本报表的分析参数重新执行（生成新报表）"
          >
            <RotateCcw className={`w-3 h-3 ${replaying ? 'animate-spin' : ''}`} /> {replaying ? '重放中…' : '重放'}
          </button>
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

      {/* LLM 失败原因：降级到规则时明示（不再静默回退让用户困惑） */}
      {report.LLM失败原因 && intentSource !== 'LLM' && (
        <div className="mt-3 rounded-xl p-4 flex gap-3 items-start bg-red-50 border border-red-200">
          <AlertTriangle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <div className="text-xs text-red-700 leading-relaxed">
            <p className="font-semibold mb-0.5">AI 智能解析未生效，本次使用规则匹配</p>
            <p>{report.LLM失败原因}</p>
            <p className="mt-1 opacity-80">配置有效的 AI Key 后（「+ AI 模型」），可生成更符合需求的图表。</p>
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
      <div className="flex flex-wrap gap-2 justify-end mt-4 items-center">
        <span className="flex items-center gap-1 text-xs text-gray-400 mr-1"><Download className="w-3.5 h-3.5" /> 导出</span>
        <button className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => handleExport('xlsx')}>
          Excel
        </button>
        <button className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => handleExport('csv')}>
          CSV
        </button>
        <button className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => handleExport('pdf')}>
          PDF
        </button>
        {trace.length > 0 && (
          <button className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={handleExportTrace}>
            决策记录
          </button>
        )}
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
            <Download className="w-3.5 h-3.5" /> HTML 报告
          </button>
        )}
        {exportData.JSON && (
          <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => {
            const blob = new Blob([exportData.JSON], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'report.json'; a.click();
          }}>
            <DownloadCloud className="w-3.5 h-3.5" /> JSON 数据
          </button>
        )}
      </div>

      {/* 分享弹窗：生成带权限的只读链接 + 管理已有链接 */}
      {showShare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setShowShare(false)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <Share2 className="w-4 h-4 text-emerald-600" /> 分享报表
              </h3>
              <button onClick={() => setShowShare(false)} className="p-1 rounded hover:bg-gray-100 text-gray-400">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 生成区 */}
            <div className="flex items-center gap-2 mb-2">
              <select
                value={shareHours}
                onChange={(e) => setShareHours(Number(e.target.value))}
                className="border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent"
              >
                <option value={1}>1 小时</option>
                <option value={24}>24 小时</option>
                <option value={72}>3 天</option>
                <option value={168}>7 天</option>
              </select>
              <input
                value={sharePassword}
                onChange={(e) => setSharePassword(e.target.value)}
                placeholder="访问密码（可选，留空无需密码）"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent"
              />
              <button
                onClick={handleCreateShare}
                className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-all whitespace-nowrap"
              >
                <Link2 className="w-3.5 h-3.5" /> 生成分享链接
              </button>
            </div>
            <p className="text-[11px] text-gray-400 mb-4">
              任何人凭链接可查看本报表（只读）；设置密码后需输入密码访问；到期或撤销后立即失效
            </p>

            {shareMsg && <p className="text-xs text-emerald-600 mb-3">{shareMsg}</p>}

            {/* 已有链接列表 */}
            {shareLinks.length > 0 && (
              <div className="space-y-2 max-h-56 overflow-auto">
                {shareLinks.map((s) => {
                  const link = `${window.location.origin}/s/${s.链接ID}`;
                  return (
                    <div key={s.链接ID} className="flex items-center gap-2 border border-gray-100 rounded-lg px-3 py-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] text-gray-700 font-mono truncate">{link}</p>
                        <p className="text-[10px] text-gray-400 flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3" /> 有效期至 {fmtExpire(s.过期时间)}
                        </p>
                      </div>
                      <button
                        className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-accent transition-colors"
                        title="复制链接"
                        onClick={() => handleCopyShare(`/s/${s.链接ID}`)}
                      >
                        {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                      <button
                        className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors"
                        title="撤销链接"
                        onClick={() => handleRevokeShare(s.链接ID)}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
            {shareLinks.length === 0 && !shareMsg && (
              <p className="text-xs text-gray-400 text-center py-4">还没有分享链接</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
