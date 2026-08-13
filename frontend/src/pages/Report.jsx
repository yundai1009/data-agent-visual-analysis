/* =============================================================================
 * 文件：frontend/src/pages/Report.jsx —— 报表历史页（路由 /report 或 /report/:reportId）
 * 功能：
 *   1. 历史列表加载（后端 GET /reports/）+ 分页加载更多 + 清空历史
 *   2. 报表详情展示：ECharts 图表 + 分析结论 + 发现 + 风险提示 + 数据表/决策记录 Tab
 *   3. 导出：统一下载弹窗支持 xlsx/csv/pdf/png/trace/html/json，saveWithPicker 选保存位置
 *   4. 分享：生成带权限只读链接 + 访问密码 + 撤销 + 复制
 *   5. 历史重放：用原报表参数重新执行分析（生成新报表）
 *   6. 多轮追问溯源：显示“追问自：XXX”链接，可跳转父报表
 * 依赖：
 *   - api.js：listReports / getReport / deleteReport / exportReport / createShare / listShares / revokeShare / replayReport
 *   - components/EChartsChart —— 图表渲染组件
 * ============================================================================= */
import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Download, Sparkles, ChevronLeft, ChevronRight, AlertTriangle, Share2, Copy, Check, Clock, Link2, X, RotateCcw, GitBranch, Filter, Star, Search } from 'lucide-react';
import { listReports, getReport, deleteReport, exportReport, exportFullReport, createShare, listShares, revokeShare, replayReport, toggleFavorite } from '../api';
import EChartsChart from '../components/EChartsChart';

// Report 报表历史页主组件
// 路由参数：reportId（可选）= URL 里指定的报表 ID，无则展示最新一张
// 业务定位：平台三大主页面之一，报表的查看、导出、分享、重放均在此页完成
export default function Report() {
  const navigate = useNavigate();
  const { reportId } = useParams();
  // 历史列表（元数据索引）：从后端 GET /reports/ 获取，包含所有报表的 ID + 标题 + 类型
  const [reportMeta, setReportMeta] = useState([]); // [{报表ID, 标题, 图表类型}]
  const [currentIndex, setCurrentIndex] = useState(0);
  // 当前展示的完整报表对象（含 图表配置 / 结论 / 推荐说明 / Agent Trace / 导出数据）
  const [localReport, setLocalReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('conclusion');
  const [loadError, setLoadError] = useState('');
  // 追问溯源：上一份报表标题（展示“追问自：XXX”）
  const [prevTitle, setPrevTitle] = useState('');
  // 分享弹窗状态
  // 分享弹窗状态（有效期 + 密码 + 已有链接列表 + 提示信息）
  const [showShare, setShowShare] = useState(false);
  // 阶段 31：收藏 + 历史检索（搜索/只看收藏）
  const [isFav, setIsFav] = useState(false);
  const [favOnly, setFavOnly] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const [shareHours, setShareHours] = useState(24);
  const [sharePassword, setSharePassword] = useState('');
  const [shareCollaborators, setShareCollaborators] = useState(''); // 阶段31：协作者 username（逗号分隔）
  const chartContainerRef = useRef(null); // 图表容器 DOM 引用：用于导出当前图表为 PNG
  // 统一下载弹窗状态（格式选择 + loading）
  const [showDl, setShowDl] = useState(false);
  const [dlFmt, setDlFmt] = useState('xlsx');
  const [dlBusy, setDlBusy] = useState(false);
  const [shareLinks, setShareLinks] = useState([]);
  const [shareMsg, setShareMsg] = useState(''); // 成功提示（绿）
  const [shareErr, setShareErr] = useState(''); // B14：失败提示（红）
  const [copied, setCopied] = useState(false);
  // 历史重放状态
  const [replaying, setReplaying] = useState(false);
  // B4 修复：当前正在查看的报表 ID（直接访问旧 URL 时列表下标推断会错对象）
  const [viewingReportId, setViewingReportId] = useState('');
  // B19 修复：翻页序号守卫（快速连续切换时旧响应不覆盖新页面）
  const switchSeqRef = useRef(0);
  // 分页：是否有更多历史 + 加载更多中
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const PAGE_SIZE = 50;

  // 挂载时：报表状态只来自后端 —— 历史列表 GET /reports/，详情 GET /reports/{id}
  // reportId（路由参数）优先展示指定报表，否则展示最新一张
  // 挂载时从后端加载报表列表与详情：reportId（路由参数）优先展示指定报表，否则展示最新一张
  // 设计：列表与详情分两次请求（列表只含元数据），避免单次返回过大
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await listReports(PAGE_SIZE, 0, { favorites: favOnly ? 1 : 0, q: searchQ });
        const items = res?.报表列表 || [];
        if (cancelled) return;
        setReportMeta(items);
        setHasMore(items.length >= PAGE_SIZE);
        const targetId = reportId || items[0]?.报表ID;
        if (targetId) {
          const idx = items.findIndex((i) => i.报表ID === targetId);
          if (idx >= 0) setIsFav(items[idx].is_favorited ?? false); // 阶段 31：星标状态
          const detail = await getReport(targetId);
          if (!cancelled && detail?.报表) {
            setLocalReport(detail.报表);
            setViewingReportId(detail.报表ID); // B4：以详情响应为准
            setPrevTitle(detail.上一报表标题 || '');
            if (idx >= 0) setCurrentIndex(idx);
          }
        }
      } catch (e) {
        console.error('报表列表加载失败:', e);
        setLoadError('报表加载失败，请检查后端服务是否可用');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [reportId, favOnly, searchQ]);

  // 翻页（上一张/下一张）：从后端拉对应报表的详情
  // B19 修复：switchSeqRef 序号守卫——快速连续切换时，旧响应不覆盖新页面
  const switchTo = async (index) => {
    if (index < 0 || index >= reportMeta.length) return;
    const seq = ++switchSeqRef.current; // B19：本次切换序号
    setCurrentIndex(index);
    setIsFav(reportMeta[index]?.is_favorited ?? false); // 阶段 31：翻页同步星标状态
    try {
      const detail = await getReport(reportMeta[index].报表ID);
      if (switchSeqRef.current !== seq) return; // 已有更新的切换，丢弃本次结果
      if (detail?.报表) {
        setLocalReport(detail.报表);
        setViewingReportId(detail.报表ID); // B4
        setPrevTitle(detail.上一报表标题 || '');
        setLoadError(''); // B17：成功翻页后清理残留错误
      }
    } catch (e) {
      console.error('报表详情加载失败:', e);
      setLoadError('报表详情加载失败，请稍后重试');
    }
  };

  const prevReport = () => switchTo(currentIndex - 1);
  const nextReport = () => switchTo(currentIndex + 1);

  // 加载更多历史报表：以当前列表长度作为 offset 向后翻页，追加到列表尾部
  const handleLoadMore = async () => {
    if (loadingMore) return; // 防重复点击并发请求
    setLoadingMore(true);
    try {
      const res = await listReports(PAGE_SIZE, reportMeta.length);
      const extra = res?.报表列表 || [];
      setReportMeta((prev) => [...prev, ...extra]);
      setHasMore(extra.length >= PAGE_SIZE); // 这次没满页说明到底了
    } catch (e) {
      setLoadError('加载更多报表失败：' + (e.message || e));
    } finally {
      setLoadingMore(false);
    }
  };

  // 清空历史：逐条删除后端报表；删除失败项保留（不误清 UI），带确认框防误操作
  const handleClearHistory = async () => {
    if (reportMeta.length === 0) return;
    if (!window.confirm(`确定删除全部 ${reportMeta.length} 份报表？此操作不可恢复。`)) return;
    const failed = [];
    // 逐条调 DELETE：失败的不从 UI 移除，避免“UI 删了后端还在”的不一致
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
  // B4 修复：操作目标 = 当前实际查看的报表，而非列表下标推断（直访旧 URL 不再错对象）
  const currentReportId = viewingReportId;
  // 统一保存：优先用 File System Access API 弹系统"另存为"让用户选位置（Chrome/Edge）；
  // 不支持或用户取消时，回退到浏览器默认下载目录（a[download] 触发）
  // 入参：blob（文件内容）、filename（建议文件名）
  async function saveWithPicker(blob, filename) {
    try {
      // 【关键行】检测浏览器是否支持 showSaveFilePicker（File System Access API）。
      // 为什么：默认下载目录会按浏览器设置乱放文件，用户找不到；
      //   原生"另存为"对话框让用户主动选位置，符合桌面软件的使用习惯。
      // 删除后果：导出永远下载到默认目录，用户找不到文件，体验断崖式下降。
      // 替代方案：只用 a[download]（兼容性最好但无法选位置）；或引入第三方库
      //   file-saver（同样不支持选位置）；原生 API 是唯一能弹保存框的方案。
      if (window.showSaveFilePicker) {
        // 从文件名解析扩展名，用于保存对话框的文件类型过滤
        const ext = '.' + ((filename.split('.').pop()) || 'bin');
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: [{ description: '导出文件', accept: { [blob.type || 'application/octet-stream']: [ext] } }],
        });
        // 拿到文件句柄后：创建可写流 → 写入 blob → 关闭（三步完成磁盘写入）
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        return;
      }
    } catch (e) {
      if (e?.name === 'AbortError') return; // 用户在保存对话框中取消（不算错误，静默退出）
      // 其他异常（权限/浏览器限制）静默回退默认下载
    }
    // 【关键行】回退方案：Object URL + 隐藏 a 标签点击下载。
    // 为什么：不支持 File System API 的浏览器（Firefox/Safari）必须还能下载；
    //   URL.createObjectURL 把 blob 变成临时 URL，a.download 指定文件名触发下载。
    // 删除后果：Firefox/Safari 用户完全无法导出任何格式。
    // 替代方案：跳转 blob URL（window.open）——无法指定文件名且会新开标签页；
    //   a[download] 是标准做法，1 秒后 revokeObjectURL 释放内存防泄漏。
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // 统一导出入口：按弹窗选择的格式生成 blob，再统一走 saveWithPicker 保存
  // 入参 fmt：'xlsx'/'csv'/'pdf'/'png'/'trace'/'html'/'json'
  // 设计：7 种格式共用一套下载/保存链路，格式差异只体现在 blob 生成这一段
  const handleExportFormat = async (fmt) => {
    try {
      let blob, filename;
      if (fmt === 'xlsx' || fmt === 'csv') {
        // 走后端导出端点：带 token 下载，返回 { blob, filename }（文件名由后端 Content-Disposition 给出）
        if (!currentReportId) return;
        ({ blob, filename } = await exportReport(currentReportId, fmt));
      } else if (fmt === 'pdf') {
        // 阶段 30：完整 PDF 报告——先截当前 ECharts 图表为 PNG（浏览器本地能力），
        // 再连同图表图片交给后端 reportlab 排版成"图文并茂"的单文件报告
        if (!currentReportId) return;
        const canvas = chartContainerRef.current?.querySelector('canvas');
        const chartPng = canvas ? canvas.toDataURL('image/png') : '';
        ({ blob, filename } = await exportFullReport(currentReportId, chartPng));
      } else if (fmt === 'png') {
        // PNG 不走后端：直接截当前 ECharts canvas（浏览器本地能力，无需请求）
        const canvas = chartContainerRef.current?.querySelector('canvas');
        if (!canvas) { alert('图表尚未渲染完成，请稍后再试'); return; }
        blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
        // 文件名用报表标题，非法文件名字符替换成下划线（Windows 不允许 \/:*?"<>|）
        filename = `${(report?.标题 || '报表').replace(/[\\/:*?"<>|]/g, '_')}.png`;
      } else if (fmt === 'trace') {
        // Agent 决策记录：前端本地拼 Markdown（步骤 + 说明），无需后端参与
        if (trace.length === 0) return;
        const lines = [
          `# Agent 决策记录 — ${report.标题 || '数据分析报表'}`,
          '',
          ...trace.map((step, i) => `## ${i + 1}. ${step.步骤 || step.说明 || `步骤 ${i + 1}`}${step.状态 === '成功' || step.状态 === '完成' ? ' ✓' : ''}\n${step.说明 || step.理由 || ''}`),
        ];
        blob = new Blob([lines.join('\n\n')], { type: 'text/markdown;charset=utf-8' });
        filename = `Agent决策记录-${(report.标题 || '报表').replace(/[\\/:*?"<>|]/g, '_')}.md`;
      } else if (fmt === 'html') {
        // HTML 报告：直接用后端导出数据里预生成的 HTML 字符串
        blob = new Blob([exportData.HTML], { type: 'text/html' });
        filename = 'report.html';
      } else if (fmt === 'json') {
        // JSON 数据：后端导出的结构化 JSON 字符串
        blob = new Blob([exportData.JSON], { type: 'application/json' });
        filename = 'report.json';
      }
      if (blob) await saveWithPicker(blob, filename); // 统一走保存位置选择逻辑
    } catch (e) {
      alert(`导出失败：${e.message || e}`);
    }
  };




  // 分享：打开弹窗并加载当前报表已有的分享链接列表
  const openShareModal = async () => {
    setShowShare(true);
    setShareMsg('');
    setShareErr('');
    setCopied(false);
    if (!currentReportId) return;
    try {
      const res = await listShares(currentReportId);
      setShareLinks(res?.分享列表 || []);
    } catch (e) {
      setShareErr('加载分享列表失败：' + (e.message || e));
    }
  };
  // 刷新分享列表：生成/撤销成功后调用，保证列表与后端一致
  const reloadShares = async () => {
    try {
      const res = await listShares(currentReportId);
      setShareLinks(res?.分享列表 || []);
    } catch (e) {
      // B15 修复：列表刷新失败不影响生成成功的提示（否则误报"生成失败"）
      setShareErr('分享列表刷新失败：' + (e.message || e));
    }
  };
  // 生成分享链接：有效期 + 可选访问密码 + 阶段31 协作者白名单
  const handleCreateShare = async () => {
    if (!currentReportId) return;
    try {
      const res = await createShare(currentReportId, shareHours, sharePassword.trim(), shareCollaborators.trim());
      setShareMsg(`已生成，有效期 ${shareHours} 小时${res.需密码 ? '，需访问密码' : ''}${res.协作者?.length ? `，协作者 ${res.协作者.length} 人` : ''}`);
      setShareErr('');
      setSharePassword(''); // 生成完清空密码输入框，下次默认不带密码
      setShareCollaborators('');
      await reloadShares();
    } catch (e) {
      setShareMsg('');
      setShareErr('生成失败：' + (e.message || e));
    }
  };
  // 撤销分享链接：确认后调后端 DELETE，链接立即失效
  const handleRevokeShare = async (shareId) => {
    if (!window.confirm('撤销后链接立即失效，确定？')) return;
    try {
      await revokeShare(currentReportId, shareId);
      setShareMsg('已撤销');
      setShareErr('');
      await reloadShares();
    } catch (e) {
      setShareErr('撤销失败：' + (e.message || e));
    }
  };
  // 复制分享链接到剪贴板：拼上站点域名才是完整可访问链接，1.6 秒后恢复图标
  const handleCopyShare = async (link) => {
    try {
      await navigator.clipboard.writeText(window.location.origin + link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setShareErr('复制失败，请手动复制链接');
    }
  };
  // 格式化过期时间为本地时间（中文格式，24 小时制）
  const fmtExpire = (iso) => {
    try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch { return iso; }
  };

  // 历史重放：用原报表参数重新执行分析（复现过程 → 生成全新报表并跳转过去）
  const handleReplay = async () => {
    if (!currentReportId || replaying) return;
    setReplaying(true);
    setLoadError('');
    try {
      const res = await replayReport(currentReportId);
      navigate(`/report/${res.报表ID}`); // 跳转到新生成的报表
    } catch (e) {
      setLoadError('重放失败：' + (e.message || e));
    } finally {
      setReplaying(false);
    }
  };

  // 阶段 31：收藏切换（乐观更新 UI，失败回滚）
  const handleToggleFav = async () => {
    if (!currentReportId) return;
    const prev = isFav;
    setIsFav(!prev);
    try {
      const res = await toggleFavorite(currentReportId);
      setIsFav(res?.is_favorited ?? !prev);
    } catch (e) {
      setIsFav(prev);
      setLoadError('收藏操作失败：' + (e.message || e));
    }
  };

  const report = localReport;

  // 骨架屏：首次加载且还没数据时展示占位动画，避免白屏闪烁
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

  // 空状态：加载完成但没有任何报表时展示引导按钮
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

  // 从报表对象中解出各区块数据：图表配置 / 推荐理由 / 风险提示 / 决策记录 / 结论等
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
      {/* Header：标题 + 元信息 + 翻页导航 + 分享/重放/导出入口 */}
      <div className="flex items-center justify-between mb-7">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900">报表查看</h1>
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
        <div className="flex items-center gap-2 flex-wrap">
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
              {/* 阶段 31：历史检索——标题搜索 + 只看收藏 */}
              <div className="ml-2 flex items-center gap-1.5">
                <div className="relative">
                  <Search className="w-3 h-3 text-gray-400 absolute left-2 top-1/2 -translate-y-1/2" />
                  <input
                    className="pl-6 pr-2 py-0.5 w-32 text-[11px] border border-gray-200 rounded-md bg-gray-50 focus:outline-none focus:border-accent"
                    placeholder="搜索标题…"
                    value={searchQ}
                    onChange={(e) => setSearchQ(e.target.value)}
                  />
                </div>
                <button
                  onClick={() => setFavOnly(!favOnly)}
                  className={`flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded transition-colors ${favOnly ? 'text-amber-500 bg-amber-50' : 'text-gray-400 hover:text-gray-600'}`}
                  title="只看收藏的报表"
                >
                  <Star className={`w-3 h-3 ${favOnly ? 'fill-amber-400' : ''}`} /> 收藏
                </button>
              </div>
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
          {Array.isArray(chartConfig?.筛选说明) && chartConfig.筛选说明.length > 0 && (
            <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-violet-50 text-violet-600 border border-violet-200"
                  title="本报表基于以下筛选条件生成（只统计筛选后的数据）">
              <Filter className="w-3 h-3" /> {chartConfig.筛选说明.join(' 且 ')}
            </span>
          )}
          {chartConfig?.TopN && (
            <span className="px-2.5 py-1 rounded text-xs bg-violet-50 text-violet-600 border border-violet-200"
                  title="只保留聚合结果中数值最大的前 N 行">Top {chartConfig.TopN}</span>
          )}
          {/* 阶段 31：收藏星标（乐观更新） */}
          <button
            onClick={handleToggleFav}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs border transition-all ${isFav ? 'bg-amber-50 text-amber-500 border-amber-200 hover:bg-amber-100' : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100 hover:text-amber-500'}`}
            title={isFav ? '取消收藏' : '收藏这份报表'}
          >
            <Star className={`w-3 h-3 ${isFav ? 'fill-amber-400' : ''}`} /> {isFav ? '已收藏' : '收藏'}
          </button>
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
            title="数据有更新？用同一分析参数读取最新数据重新生成（产生一份新报表）"
          >
            <RotateCcw className={`w-3 h-3 ${replaying ? 'animate-spin' : ''}`} /> {replaying ? '重跑中…' : '用最新数据重跑'}
          </button>
        </div>
      </div>

      {/* ECharts Chart：藏青光晕舞台；表格类图表不渲染 ECharts，提示去下方 Tab 查看 */}
      <div ref={chartContainerRef} className="rounded-xl p-5"
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
      <div className="bg-white rounded-xl shadow-[var(--shadow-card)] mt-5 overflow-hidden">
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

      {/* 导出 + 继续分析：所有格式统一收进下载弹窗 */}
      <div className="flex flex-wrap gap-2 justify-end mt-4 items-center">
        <button
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all"
          onClick={() => { setDlFmt('xlsx'); setShowDl(true); }}
        >
          <Download className="w-3.5 h-3.5" /> 导出
        </button>
        <button
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
          onClick={() => navigate('/analysis')}
        >
          继续分析
        </button>
      </div>

      {/* 统一下载弹窗：选择格式 → 确认下载（Chrome/Edge 可选保存位置）
          每种格式带 available 标记，不满足条件（如图表未渲染/无数据）的置灰不可选 */}
      {showDl && (() => {
        const dlOptions = [
          { key: 'xlsx', label: 'Excel 表格', desc: '数据明细（.xlsx）' },
          { key: 'csv', label: 'CSV 数据', desc: '数据明细（.csv）' },
          { key: 'pdf', label: 'PDF 报告', desc: '结论 + 数据表（.pdf）' },
          { key: 'png', label: '图表图片', desc: '当前可视化图表（.png）', available: chartTypeKey !== 'table' },
          { key: 'trace', label: 'Agent 决策记录', desc: '分析过程（.md）', available: trace.length > 0 },
          { key: 'html', label: 'HTML 报告', desc: '静态网页（.html）', available: !!exportData?.HTML },
          { key: 'json', label: 'JSON 数据', desc: '结构化数据（.json）', available: !!exportData?.JSON },
        ];
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setShowDl(false)}>
            <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                  <Download className="w-4 h-4 text-accent" /> 导出报表
                </h3>
                <button onClick={() => setShowDl(false)} className="p-1 rounded hover:bg-gray-100 text-gray-400"><X className="w-4 h-4" /></button>
              </div>
              <div className="space-y-1.5 max-h-72 overflow-y-auto">
                {dlOptions.filter(o => o.available !== false).map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => setDlFmt(opt.key)}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-all ${dlFmt === opt.key ? 'border-accent bg-accent-soft' : 'border-gray-200 hover:bg-gray-50'}`}
                  >
                    <span>
                      <span className={`block text-sm ${dlFmt === opt.key ? 'text-accent-deep' : 'text-gray-700'}`}>{opt.label}</span>
                      <span className="block text-[11px] text-gray-400">{opt.desc}</span>
                    </span>
                    <span className={`w-3.5 h-3.5 rounded-full border-2 shrink-0 ${dlFmt === opt.key ? 'border-accent bg-accent' : 'border-gray-300'}`} />
                  </button>
                ))}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={() => setShowDl(false)} className="flex-1 py-2 rounded-lg border border-gray-200 text-sm text-gray-500 hover:bg-gray-50 transition-all">取消</button>
                <button
                  onClick={async () => { setDlBusy(true); await handleExportFormat(dlFmt); setDlBusy(false); setShowDl(false); }}
                  disabled={dlBusy}
                  className="flex-1 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all disabled:opacity-50"
                >
                  {dlBusy ? '下载中…' : '确认下载'}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* 分享弹窗：生成带权限的只读链接 + 管理已有链接 */}
      {showShare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setShowShare(false)}>
          <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
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
            {/* 阶段 31：协作者白名单——填了则只有这些登录用户可看，公开访客 401 */}
            <input
              value={shareCollaborators}
              onChange={(e) => setShareCollaborators(e.target.value)}
              placeholder="协作者 username（逗号分隔，留空 = 公开链接）"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent mb-3"
            />
            <p className="text-[11px] text-gray-400 mb-4">
              任何人凭链接可查看本报表（只读）；设置密码后需输入密码访问；指定协作者后仅白名单内登录用户可看；到期或撤销后立即失效
            </p>

            {shareMsg && <p className="text-xs text-emerald-600 mb-3">{shareMsg}</p>}
            {shareErr && <p className="text-xs text-red-500 mb-3">{shareErr}</p>}

            {/* 已有链接列表 */}
            {shareLinks.length > 0 && (
              <div className="space-y-2 max-h-56 overflow-auto">
                {shareLinks.map((s) => {
                  const link = `${window.location.origin}/s/${s.链接ID}`;
                  return (
                    <div key={s.链接ID} className="flex items-center gap-2 bg-surface rounded-lg px-3 py-2">
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
            {shareLinks.length === 0 && !shareMsg && !shareErr && (
              <p className="text-xs text-gray-400 text-center py-4">还没有分享链接</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
