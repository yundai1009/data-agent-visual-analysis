// 数据管理页（面试讲解）
//
// 做了什么：数据资产的"仓库页"——上传/下载数据集、加载示例数据、
//   清洗、重命名、删除、预览；上传后立即展示字段画像与 LLM 字段
//   推荐（指明哪个字段适合做 X 轴/Y 轴/分组）。
// 为什么这样设计：
//   - 导入与导出走同一仓库（后端统一 exportUserData 打包下载）；
//   - DEMO_MODE（VITE_DEMO=1 构建）自动加载示例数据，给零基础
//     用户零门槛体验（正式模式该常量恒为 false）；
//   - 卡片用 typeColors/typeLabels 给日期/分类/数值字段着色，
//     字段类型一眼可辨，降低理解成本。
// 删除它会怎样：用户无法管理自己的数据，分析无从谈起。
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Download, FileDown, Database, FileText, AlertTriangle, Search, Sparkles, Loader2, BarChart3, LineChart, Pencil, Trash2, Lightbulb } from 'lucide-react';
import { uploadFileWithProgress, loadExample, cleanDataset, healthCheck, listDatasets, deleteDataset, renameDataset, mergeDatasets, getDataset, getDatasetRows, exportUserData } from '../api';
import { useApp } from '../AppContext';

// 演示模式（vite --mode demo 构建）：打开页面自动加载示例数据，零基础用户无需上传即可体验
const DEMO_MODE = import.meta.env.VITE_DEMO === '1';

const typeColors = {
  date: 'bg-accent-soft text-accent-deep border-accent/20',
  cat: 'bg-amber-50 text-amber-600 border-amber-200',
  num: 'bg-emerald-50 text-emerald-600 border-emerald-200',
};
const typeLabels = { date: '日期', cat: '分类', num: '数值' };

function inferType(field, profile) {
  if ((profile.日期字段 || []).includes(field)) return 'date';
  if ((profile.数值字段 || []).includes(field)) return 'num';
  if ((profile.分类字段 || []).includes(field)) return 'cat';
  return 'cat';
}

export default function DataManagement() {
  const navigate = useNavigate();
  const { dataset: globalDataset, setDataset: setAppDataset } = useApp();
  const [dataset, setDataset] = useState(globalDataset);
  const [profile, setProfile] = useState(globalDataset?.数据画像 || null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadNotice, setUploadNotice] = useState(''); // 黄色提示：部分成功
  const failedFilesRef = useRef([]); // 失败文件引用（供"重试失败文件"）
  const [backendOk, setBackendOk] = useState(true);
  const [error, setError] = useState('');
  // 优化③：数据集多选合并
  const [mergeSel, setMergeSel] = useState(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeName, setMergeName] = useState('');
  const [merging, setMerging] = useState(false);
  // 优化⑨：数据预览分页
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewRows, setPreviewRows] = useState([]);
  const [previewOffset, setPreviewOffset] = useState(0);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const PREVIEW_PAGE = 20;
  const [dsList, setDsList] = useState([]);          // 我的数据集列表
  const [dsOpen, setDsOpen] = useState(false);       // 数据集管理面板
  // 阶段 31：数据集管理增强——文件名搜索 + 排序 + 概览统计
  const [dsQ, setDsQ] = useState('');
  const [dsSort, setDsSort] = useState('created_at_desc');
  const [dsStats, setDsStats] = useState({ 总数: 0, 总行数: 0 });
  const [renaming, setRenaming] = useState(null);    // 正在重命名的数据集（ID）
  const [newName, setNewName] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [detailField, setDetailField] = useState(null);
  const [showMissing, setShowMissing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [cleanResult, setCleanResult] = useState(null);
  // 优化②：清洗另存为新数据集
  const [cleanAsNew, setCleanAsNew] = useState(false);
  const [cleanNewName, setCleanNewName] = useState('');
  // 清洗选项（阶段 7：可配置）
  const [cleanOps] = useState({
    deduplicate: true,
    fill_missing: true,
    fill_strategy: 'auto',
    drop_empty_rows: true,
  });

  // 演示模式：挂载时若还没有数据集，自动加载内置示例数据（sales_2024.csv）
  useEffect(() => {
    if (DEMO_MODE && !dataset) {
      handleLoadExample();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 真实健康检查：替换假的"系统正常"徽章
  useEffect(() => {
    let cancelled = false;
    healthCheck().then(() => { if (!cancelled) setBackendOk(true); })
      .catch(() => { if (!cancelled) setBackendOk(false); });
    return () => { cancelled = true; };
  }, []);

  // 加载我的数据集列表（阶段 31：带搜索/排序，返回概览统计）
  useEffect(() => {
    let cancelled = false;
    listDatasets(200, dsQ, dsSort).then(res => {
      if (cancelled) return;
      setDsList(res?.数据集列表 || []);
      setDsStats(res?.统计 || { 总数: 0, 总行数: 0 });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [dataset?.数据集ID, dsQ, dsSort]);

  // 切换数据集
  // F-M7：switchSeqRef 序号守卫（照抄 Dashboard.jsx:60-73 模式）——
  // 快速切换两个数据集时，旧响应不得覆盖新选择
  const switchSeqRef = useRef(0);
  const handleSwitchDataset = async (id) => {
    const seq = ++switchSeqRef.current;
    try {
      const res = await getDataset(id);
      if (switchSeqRef.current !== seq) return; // 已有更新的切换，丢弃旧响应
      setDataset({ 数据集ID: id, 文件名: res.文件名, 数据画像: res.数据画像, 来源数据集ID: res.来源数据集ID });
      setAppDataset({ 数据集ID: id, 文件名: res.文件名, 数据画像: res.数据画像, 来源数据集ID: res.来源数据集ID });
      setProfile(res.数据画像);
      setDsOpen(false);
    } catch (e) {
      if (switchSeqRef.current !== seq) return;
      setError(e.message || '切换失败');
    }
  };

  // 删除数据集
  const handleDeleteDataset = async (id, name) => {
    if (!window.confirm(`删除数据集「${name}」？此操作不可恢复。`)) return;
    try {
      await deleteDataset(id);
      setDsList(prev => prev.filter(d => d.数据集ID !== id));
      if (dataset?.数据集ID === id) {
        setDataset(null); setProfile(null); setAppDataset(null);
      }
    } catch (e) { setError(e.message || '删除失败'); }
  };

  // 重命名数据集
  const handleRenameDataset = async (id) => {
    if (!newName.trim()) return;
    try {
      await renameDataset(id, newName.trim());
      setDsList(prev => prev.map(d => d.数据集ID === id ? { ...d, 文件名: newName.trim() } : d));
      if (dataset?.数据集ID === id) {
        setDataset(d => ({ ...d, 文件名: newName.trim() }));
        setAppDataset(d => ({ ...d, 文件名: newName.trim() }));
      }
      setRenaming(null); setNewName('');
    } catch (e) { setError(e.message || '重命名失败'); }
  };

  async function handleUpload(files, retryOnly = false) {
    let targets = files;
    if (retryOnly) {
      targets = failedFilesRef.current;
      failedFilesRef.current = [];
      if (targets.length === 0) { setUploading(false); return; }
    }
    setError('');
    setUploadNotice('');
    setUploading(true);
    setUploadProgress(0);
    try {
      // uploadFileWithProgress 支持单文件（File）与多文件（FileList / File[]），并回报上传进度
      const res = await uploadFileWithProgress(targets, setUploadProgress);
      const 成功列表 = res.上传成功 || [];
      const 失败列表 = res.上传失败 || [];
      // 保留失败文件的 File 引用（按文件名匹配），供"重试失败文件"复用
      failedFilesRef.current = [];
      if (失败列表.length > 0) {
        const failNames = new Set(失败列表.map(f => f.文件名));
        const targetArr = targets instanceof File ? [targets] : Array.from(targets);
        failedFilesRef.current = targetArr.filter(f => failNames.has(f.name));
      }
      // 设置当前数据集为最后一个成功的文件
      if (成功列表.length > 0) {
        const last = 成功列表[成功列表.length - 1];
        setDataset(last);
        setProfile(last.数据画像);
        setAppDataset({ 数据集ID: last.数据集ID, 文件名: last.文件名, 行数: last.行数, 数据画像: last.数据画像 });
      }
      // 部分成功 → 黄色提示（不走红色错误条）；全部失败 → 红色错误
      if (成功列表.length > 0 && 失败列表.length > 0) {
        setUploadNotice(`成功上传 ${成功列表.length} 个文件，失败 ${失败列表.length} 个：${失败列表.map(f => f.文件名 + '（' + f.错误 + '）').join('；')}`);
      } else if (失败列表.length > 0 && 成功列表.length === 0) {
        setError(`全部上传失败：${失败列表.map(f => f.文件名 + '（' + f.错误 + '）').join('；')}`);
      }
      setUploading(false);
      setUploadProgress(100);
    } catch (e) {
      setError(e.message);
      setUploading(false);
    }
  }

  async function handleLoadExample() {
    setError('');
    setUploading(true);
    try {
      const res = await loadExample();
      setDataset(res);
      setProfile(res.数据画像);
      setAppDataset({ 数据集ID: res.数据集ID, 文件名: res.文件名, 行数: res.行数, 数据画像: res.数据画像 });
    } catch (e) {
      setError(e.message);
    }
    setUploading(false);
  }

  // D 合规：导出我的全部数据（个人资料 + 数据集元数据 + 报表全文 + 看板，JSON 下载）
  async function handleExportAllData() {
    try {
      const { blob, filename } = await exportUserData();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError('导出失败：' + (e.message || e));
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) handleUpload(files);
  }

  const fields = profile?.字段列表 || [];
  const filteredFields = fields.filter((f) => {
    const matchSearch = !search || f.includes(search);
    const matchType = typeFilter === 'all' || inferType(f, profile) === typeFilter;
    return matchSearch && matchType;
  });

  const missingCount = profile?.总缺失值 || 0;
  const quality = profile?.数据质量 || {};
  const qualityLevel = quality?.评级 || '—';
  const qualityDesc = quality?.等级说明 || '';
  const missingFields = quality?.缺失字段 || [];

  async function handleClean() {
    if (!dataset) return;
    setCleaning(true);
    try {
      const res = await cleanDataset(dataset.数据集ID, {
        deduplicate: cleanOps.deduplicate,
        fill_missing: cleanOps.fill_missing,
        fill_strategy: cleanOps.fill_strategy,
        drop_empty_rows: cleanOps.drop_empty_rows,
        // 优化②：另存为新数据集（保留原始数据对照）
        新文件名: cleanAsNew ? (cleanNewName.trim() || `${dataset.文件名}-已清洗`) : '',
      });
      setCleanResult(res);
      // 另存时：选中新数据集 + 刷新列表；覆盖时：原地更新画像
      if (cleanAsNew) {
        setDataset(prev => ({ ...prev, 数据集ID: res.数据集ID, 文件名: res.文件名 || prev?.文件名, 数据画像: res.数据画像 }));
        setProfile(res.数据画像);
        setAppDataset(prev => ({ ...prev, 数据集ID: res.数据集ID, 文件名: res.文件名 || prev?.文件名, 数据画像: res.数据画像 }));
        listDatasets(200, dsQ, dsSort).then(r2 => { setDsList(r2?.数据集列表 || []); setDsStats(r2?.统计 || {}); }).catch(() => {});
      } else {
        setProfile(res.数据画像);
        setDataset(prev => ({ ...prev, 行数: res.清洗后行数, 数据画像: res.数据画像 }));
        // 同步 AppContext，让分析页使用清洗后数据
        setAppDataset(prev => prev ? { ...prev, 行数: res.清洗后行数, 数据画像: res.数据画像 } : prev);
      }
    } catch (e) {
      setError('清洗失败: ' + e.message);
    }
    setCleaning(false);
  }

  function handleJoinAnalysis() {
    if (!dataset) return;
    // B22 修复：移除无消费方的 focusField 死数据；按钮跳转分析页保持功能
    navigate('/analysis');
  }

  // 优化③：合并所选数据集（列对齐 + 行追加），成功后选中新数据集
  const handleMerge = async () => {
    const ids = Array.from(mergeSel);
    if (ids.length < 2) return;
    setMerging(true);
    setError('');
    try {
      const res = await mergeDatasets(ids, mergeName.trim());
      setDataset(res);
      setProfile(res.数据画像);
      setAppDataset({ 数据集ID: res.数据集ID, 文件名: res.文件名, 行数: res.行数, 数据画像: res.数据画像 });
      setMergeSel(new Set());
      setMergeOpen(false);
      setMergeName('');
      listDatasets(200, dsQ, dsSort).then(r2 => { setDsList(r2?.数据集列表 || []); setDsStats(r2?.统计 || {}); }).catch(() => {});
    } catch (e) {
      setError(e.message || '合并失败');
    }
    setMerging(false);
  };

  // 优化③：批量删除所选数据集（复用多选 checkbox）
  const handleDeleteSelected = async () => {
    const ids = Array.from(mergeSel);
    if (ids.length === 0) return;
    if (!window.confirm(`确定删除所选 ${ids.length} 个数据集？此操作不可恢复。`)) return;
    setMerging(true);
    setError('');
    const failed = [];
    for (const id of ids) {
      try { await deleteDataset(id); } catch { failed.push(id); }
    }
    setMergeSel(new Set());
    if (failed.length > 0) setError(`有 ${failed.length} 个数据集删除失败，已保留`);
    if (dataset && ids.includes(dataset.数据集ID)) {
      setDataset(null); setProfile(null); setAppDataset(null);
    }
    listDatasets(200, dsQ, dsSort).then(r2 => { setDsList(r2?.数据集列表 || []); setDsStats(r2?.统计 || {}); }).catch(() => {});
    setMerging(false);
  };

  // 优化⑨：打开/翻页数据预览
  const handlePreview = async (offset = 0) => {
    if (!dataset?.数据集ID) return;
    setPreviewLoading(true);
    setError('');
    try {
      const res = await getDatasetRows(dataset.数据集ID, offset, PREVIEW_PAGE);
      setPreviewRows(res.数据 || []);
      setPreviewTotal(res.总行数 || 0);
      setPreviewOffset(res.偏移 || 0);
      setPreviewOpen(true);
    } catch (e) {
      setError('预览加载失败：' + (e.message || e));
    }
    setPreviewLoading(false);
  };

  function handleNewAnalysis() {
    if (!dataset) return;
    navigate('/analysis');
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-7">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">数据管理</h1>
          <p className="text-xs text-gray-400 mt-1">支持 CSV / Excel 上传，自动识别字段类型与数据质量</p>
        </div>
        <div className="flex items-center gap-3">
          {/* D 合规：导出我的全部数据 */}
          <button onClick={handleExportAllData} title="导出我的全部数据（JSON）" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">
            <FileDown className="w-3.5 h-3.5" />导出数据
          </button>
          {/* 我的数据集（多数据集切换/删除/重命名） */}
          <div className="relative">
            <button onClick={() => setDsOpen(!dsOpen)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">
              <Database className="w-3.5 h-3.5" />我的数据集{dsList.length > 0 ? `（${dsList.length}）` : ''}
            </button>
            {dsOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setDsOpen(false)} />
                <div className="absolute right-0 top-full mt-2 z-20 w-80 popup-surface bg-white border border-gray-200 rounded-xl shadow-xl p-3">
                  <p className="text-xs font-semibold text-gray-700 mb-1">我的数据集</p>
                  {/* 阶段 31：概览统计 + 文件名搜索 + 排序 */}
                  <p className="text-[11px] text-gray-400 mb-2">共 {dsStats.总数} 个数据集 · 总行数 {dsStats.总行数.toLocaleString()} 行</p>
                  <div className="flex items-center gap-1.5 mb-2">
                    <input
                      className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-[11px] bg-gray-50 focus:outline-none focus:border-accent"
                      placeholder="搜索文件名…"
                      value={dsQ}
                      onChange={(e) => setDsQ(e.target.value)}
                    />
                    <select
                      className="border border-gray-200 rounded-lg px-2 py-1.5 text-[11px] bg-white focus:outline-none focus:border-accent"
                      value={dsSort}
                      onChange={(e) => setDsSort(e.target.value)}
                    >
                      <option value="created_at_desc">最新上传</option>
                      <option value="rows_desc">行数最多</option>
                      <option value="file_name_asc">名称排序</option>
                    </select>
                  </div>
                  {dsList.length === 0 ? (
                    <p className="text-xs text-gray-400 py-3 text-center">暂无数据集，上传一个吧</p>
                  ) : (
                    <div className="space-y-1 max-h-64 overflow-y-auto">
                      {dsList.map(d => (
                        <div key={d.数据集ID} className="flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-gray-50 transition-colors">
                          {/* 优化③：多选以合并 */}
                          <input
                            type="checkbox"
                            checked={mergeSel.has(d.数据集ID)}
                            onChange={(e) => {
                              const next = new Set(mergeSel);
                              if (e.target.checked) next.add(d.数据集ID); else next.delete(d.数据集ID);
                              setMergeSel(next);
                            }}
                            title="勾选后可合并"
                            className="accent-accent shrink-0"
                          />
                          {renaming === d.数据集ID ? (
                            <div className="flex-1 flex gap-1.5">
                              <input className="flex-1 border border-gray-200 rounded-md px-2 py-1 text-xs focus:outline-none focus:border-accent" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus />
                              <button className="text-[11px] text-accent hover:text-accent-deep" onClick={() => handleRenameDataset(d.数据集ID)}>保存</button>
                            </div>
                          ) : (
                            <>
                              <button className="flex-1 text-left min-w-0" onClick={() => handleSwitchDataset(d.数据集ID)}>
                                <p className={`text-xs truncate ${dataset?.数据集ID === d.数据集ID ? 'text-accent font-medium' : 'text-gray-700'}`}>{d.文件名}</p>
                                <p className="text-[10px] text-gray-400">{d.行数} 行 · {d.列数} 列</p>
                              </button>
                              <button className="text-gray-300 hover:text-accent transition-colors" title="重命名" onClick={() => { setRenaming(d.数据集ID); setNewName(d.文件名); }}>
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              <button className="text-gray-300 hover:text-red-500 transition-colors" title="删除" onClick={() => handleDeleteDataset(d.数据集ID, d.文件名)}>
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {/* 优化③：合并所选按钮 */}
                  {mergeSel.size >= 2 && (
                    <button
                      onClick={() => setMergeOpen(true)}
                      className="mt-2 w-full py-1.5 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
                    >合并所选（{mergeSel.size} 个数据集）</button>
                  )}
                  {/* 优化③：批量删除所选 */}
                  {mergeSel.size >= 1 && (
                    <button
                      onClick={handleDeleteSelected}
                      disabled={merging}
                      className="mt-1.5 w-full py-1.5 rounded-lg border border-red-200 text-red-500 text-xs font-medium hover:bg-red-50 transition-all disabled:opacity-50"
                    >删除所选（{mergeSel.size} 个）</button>
                  )}
                  {/* 优化③：合并命名弹窗 */}
                  {mergeOpen && (
                    <>
                      <div className="fixed inset-0 z-20" onClick={() => { if (!merging) setMergeOpen(false); }} />
                      <div className="absolute right-0 top-full mt-2 z-30 w-80 bg-white border border-gray-200 rounded-xl shadow-xl p-4">
                        <p className="text-xs font-semibold text-gray-700 mb-2">合并 {mergeSel.size} 个数据集</p>
                        <p className="text-[11px] text-gray-400 mb-2">列自动对齐（并集），行追加合并；缺失列填空。</p>
                        <input
                          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent mb-3"
                          placeholder="新数据集名称（留空自动命名）"
                          value={mergeName}
                          onChange={(e) => setMergeName(e.target.value)}
                          maxLength={120}
                          autoFocus
                        />
                        <div className="flex gap-2">
                          <button
                            className="flex-1 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
                            onClick={handleMerge}
                            disabled={merging}
                          >{merging ? '合并中…' : '确认合并'}</button>
                          <button className="px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50" onClick={() => setMergeOpen(false)}>取消</button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
          <button onClick={handleLoadExample} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">
            <Download className="w-3.5 h-3.5" />导入示例数据
          </button>
          <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border ${backendOk ? 'text-emerald-600 bg-emerald-50 border-emerald-200' : 'text-red-600 bg-red-50 border-red-200'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${backendOk ? 'bg-emerald-500' : 'bg-red-500'}`} />{backendOk ? '系统正常' : '后端不可用'}
          </span>
          <span className="flex items-center gap-1 text-xs text-accent bg-accent-soft px-2.5 py-1 rounded border border-accent/20 cursor-default" title="开启后自动识别日期/分类/数值字段">
            <Sparkles className="w-3 h-3" /> 自动类型推断
          </span>
        </div>
      </div>

      {/* Upload zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => !uploading && document.getElementById('file-input').click()}
        className={`rounded-xl text-center cursor-pointer transition-all ${
          dataset ? 'border border-emerald-200 bg-emerald-50/50 px-5 py-3' : 'border-2 border-dashed border-gray-300 hover:border-accent hover:bg-accent-soft/30 px-6 py-10'
        }`}
      >
        <input id="file-input" type="file" accept=".csv,.xlsx,.xls" multiple className="hidden" onChange={(e) => { if (e.target.files.length > 0) handleUpload(e.target.files); e.target.value = ''; }} />
        {uploading ? (
          <div className="max-w-sm mx-auto w-full">
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-accent animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
              <span className="text-sm text-gray-500">正在上传解析 {uploadProgress < 100 ? `${uploadProgress}%` : '完成'}</span>
            </div>
            {/* 优化②：上传进度条 */}
            <div className="mt-3 h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
              <div className="h-full bg-accent transition-all duration-200" style={{ width: `${Math.max(4, uploadProgress)}%` }} />
            </div>
          </div>
        ) : dataset ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-emerald-500" />
              <span className="text-sm text-gray-700">已加载数据集：{dataset.文件名}（{profile?.行数} 行）</span>
              {dataset.来源数据集ID && <span className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">源自清洗/合并</span>}
            </div>
            <div className="flex gap-2">
              <button className="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-white" onClick={(e) => { e.stopPropagation(); handlePreview(0); }} title="查看原始数据">数据预览</button>
              <button className="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-white" onClick={(e) => { e.stopPropagation(); setDataset(null); setProfile(null); setAppDataset(null); }}>重新上传</button>
            </div>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 mx-auto text-gray-400 mb-3" />
            <p className="text-sm text-gray-500 mb-1">点击上传或拖拽文件到此处</p>
            <p className="text-xs text-gray-400">支持 .csv / .xlsx / .xls 格式，单文件不超过 50MB</p>
          </>
        )}
        {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      {/* 优化②：部分成功的黄色提示 + 失败文件重试 */}
      {uploadNotice && (
        <div className="mt-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700 flex items-center gap-2">
          <span className="flex-1">{uploadNotice}</span>
          {failedFilesRef.current.length > 0 && (
            <button
              className="px-2 py-1 rounded border border-amber-300 text-amber-700 hover:bg-amber-100 transition-all whitespace-nowrap"
              onClick={(e) => { e.stopPropagation(); handleUpload(null, true); }}
            >重试失败文件（{failedFilesRef.current.length}）</button>
          )}
          <button className="text-amber-400 hover:text-amber-600" onClick={() => setUploadNotice('')}>✕</button>
        </div>
      )}
      {/* 优化⑨：数据预览分页表格 */}
      {previewOpen && (
        <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-700">数据预览（共 {previewTotal.toLocaleString()} 行）</p>
            <button className="text-gray-400 hover:text-gray-600 text-sm leading-none" onClick={() => setPreviewOpen(false)}>✕</button>
          </div>
          {previewLoading ? (
            <p className="text-center text-xs text-gray-400 py-8">加载中…</p>
          ) : previewRows.length === 0 ? (
            <p className="text-center text-xs text-gray-400 py-8">暂无数据</p>
          ) : (
            <>
              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-50">
                    <tr className="text-gray-400 border-b border-gray-100">
                      <th className="text-left px-4 py-2 font-medium">#</th>
                      {Object.keys(previewRows[0]).map((k) => (
                        <th key={k} className="text-left px-3 py-2 font-medium whitespace-nowrap">{k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {previewRows.map((row, i) => (
                      <tr key={previewOffset + i} className="hover:bg-gray-50/60">
                        <td className="px-4 py-2 text-gray-400">{previewOffset + i + 1}</td>
                        {Object.values(row).map((v, j) => (
                          <td key={j} className="px-3 py-2 text-gray-600 font-mono max-w-[240px] truncate">{String(v ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-5 py-2.5 border-t border-gray-100 flex items-center justify-between">
                <span className="text-[11px] text-gray-400">第 {previewOffset + 1}-{Math.min(previewOffset + PREVIEW_PAGE, previewTotal)} 行 / 共 {previewTotal} 行</span>
                <div className="flex gap-2">
                  <button
                    className="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
                    disabled={previewOffset === 0 || previewLoading}
                    onClick={() => handlePreview(Math.max(0, previewOffset - PREVIEW_PAGE))}
                  >上一页</button>
                  <button
                    className="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
                    disabled={previewOffset + PREVIEW_PAGE >= previewTotal || previewLoading}
                    onClick={() => handlePreview(previewOffset + PREVIEW_PAGE)}
                  >下一页</button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
      </div>

      {/* Stats：主次分明（质量卡放大 + 藏青强调，去千篇一律 border+shadow） */}
      {profile && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
          <div className="bg-card rounded-xl p-4" style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)' }}>
            <div className="flex items-center gap-2"><Database className="w-4 h-4 text-muted" /><span className="text-xs text-gray-400">总行数</span></div>
            <p className="text-2xl font-bold text-ink mt-1" style={{ fontVariantNumeric: 'tabular-nums' }}>{profile.行数.toLocaleString()}</p>
            <p className="text-xs text-gray-400 mt-1">数据量正常，可流畅分析</p>
          </div>
          <div className="bg-card rounded-xl p-4" style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)' }}>
            <div className="flex items-center gap-2"><FileText className="w-4 h-4 text-muted" /><span className="text-xs text-gray-400">字段数</span></div>
            <p className="text-2xl font-bold text-ink mt-1" style={{ fontVariantNumeric: 'tabular-nums' }}>{profile.列数}</p>
            <p className="text-xs text-gray-400 mt-1">日期 {profile.日期字段?.length || 0} / 分类 {profile.分类字段?.length || 0} / 数值 {profile.数值字段?.length || 0}</p>
          </div>
          <div className="rounded-xl p-4 lg:col-span-2 relative overflow-hidden"
               style={{ background: 'linear-gradient(135deg, #e8eef5 0%, #f8fafc 100%)', boxShadow: '0 8px 16px -8px rgba(15,76,129,.12)' }}>
            <div className="absolute -top-4 -right-4 w-20 h-20 bg-accent/5 rounded-full" />
            <div className="flex items-center gap-2"><span className="text-lg" style={{ color: '#0f4c81' }}>✓</span><span className="text-xs text-gray-400">数据质量评级</span></div>
            <p className="text-3xl font-bold mt-1" style={{ color: '#0f4c81' }}>{qualityLevel}</p>
            <p className="text-xs text-gray-400 mt-1">{qualityDesc}</p>
          </div>
          <div className="bg-card rounded-xl p-4 cursor-pointer" style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)', borderLeft: '3px solid #b45309' }} onClick={() => setShowMissing(true)}>
            <div className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-orange-500" /><span className="text-xs text-gray-400">缺失值数量</span></div>
            <p className="text-2xl font-bold mt-1" style={{ color: '#b45309', fontVariantNumeric: 'tabular-nums' }}>{missingCount}</p>
            <p className="text-xs text-orange-600 mt-1">{missingFields.length > 0 ? `共 ${missingFields.length} 个字段存在缺失` : '无缺失值'}</p>
          </div>
        </div>
      )}

      {/* Field list */}
      {profile && (
        <div className="bg-white rounded-xl border border-gray-200 mt-6 overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-3.5 border-b border-gray-100">
            <span className="text-sm font-semibold text-gray-700">字段列表</span>
            <div className="flex-1 max-w-[200px]">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg bg-gray-50 focus:outline-none focus:border-accent focus:bg-white" placeholder="搜索字段名..." value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
            </div>
            <select className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">全部类型</option>
              <option value="date">日期</option>
              <option value="cat">分类</option>
              <option value="num">数值</option>
            </select>
            <span className="text-xs text-gray-400">共 {fields.length} 个字段</span>
          </div>
          <div>
            {filteredFields.map((field) => {
              const type = inferType(field, profile);
              const fieldAdvice = (profile.字段建议 || []).find((a) => a.字段 === field);
              return (
                <div key={field} className="flex items-center gap-3 px-5 py-2.5 border-b border-gray-50 last:border-b-0 hover:bg-gray-50/50 group cursor-pointer">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <span className="text-sm text-gray-700 truncate">{field}</span>
                    <span className={`inline-flex items-center h-5 px-2 rounded text-xs font-medium border ${typeColors[type]}`}>{typeLabels[type]}</span>
                  </div>
                  <div className="flex-1 text-xs text-gray-400 truncate hidden md:block">{fieldAdvice?.理由 || ''}</div>
                  <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button className="text-xs text-accent hover:bg-accent-soft px-2 py-1 rounded" onClick={(e) => { e.stopPropagation(); setDetailField(field); }}>预览</button>
                    <button className="text-xs text-accent hover:bg-accent-soft px-2 py-1 rounded" onClick={(e) => { e.stopPropagation(); handleJoinAnalysis(field); }}>加入分析</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 数据洞察（自动生成：异常值/相关性/分布集中度） */}
      {profile?.自动洞察?.length > 0 && (
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-3">
            <Lightbulb className="w-4 h-4 text-amber-500" />
            <p className="text-xs font-semibold text-gray-700">数据洞察</p>
            <span className="text-[10px] text-gray-400">AI 自动发现 · {profile.自动洞察.length} 条</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {profile.自动洞察.map((ins, i) => (
              <div key={i} className="bg-white rounded-xl border border-gray-200 p-3.5 transition-all hover:shadow-sm">
                <span className={`inline-block text-[10px] px-2 py-0.5 rounded font-medium ${
                  ins.类型 === '异常值' ? 'bg-amber-50 text-amber-600' : ins.类型 === '相关' ? 'bg-accent-soft text-accent' : 'bg-emerald-50 text-emerald-600'
                }`}>{ins.类型}</span>
                <p className="text-xs text-gray-700 mt-2 leading-relaxed">{ins.说明}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick actions */}
      {profile && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-6">
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm" onClick={handleNewAnalysis}>
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center"><BarChart3 className="w-5 h-5 text-accent" /></div>
            <div><p className="text-sm font-medium text-gray-700">基于此数据集新建分析</p><p className="text-xs text-gray-400 mt-0.5">自动带入当前数据集上下文</p></div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm" onClick={handleClean}>
            <div className="w-10 h-10 rounded-lg bg-orange-50 flex items-center justify-center">{cleaning ? <Loader2 className="w-5 h-5 animate-spin text-orange-500" /> : <Sparkles className="w-5 h-5 text-orange-500" />}</div>
            <div><p className="text-sm font-medium text-gray-700">一键基础清洗</p><p className="text-xs text-gray-400 mt-0.5">去重 / 填充缺失 / 删除空行</p></div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm" onClick={() => navigate('/report')}>
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center"><LineChart className="w-5 h-5 text-accent" /></div>
            <div><p className="text-sm font-medium text-gray-700">查看报表</p><p className="text-xs text-gray-400 mt-0.5">浏览已生成的智能分析报告</p></div>
          </div>
        </div>
      )}

      {/* Field detail modal */}
      {detailField && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={() => setDetailField(null)}>
          <div className="bg-white popup-surface rounded-xl shadow-xl max-w-lg w-full mx-4 overflow-hidden animate-in" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">字段详情：{detailField}</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none" onClick={() => setDetailField(null)}>✕</button>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">字段类型</p><p className="text-sm mt-1 font-medium">{typeLabels[inferType(detailField, profile)]}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">空值数量</p><p className="text-sm mt-1 font-mono">{(profile.缺失值 || {})[detailField] ?? '0'}</p></div>
              </div>
              <div className="bg-accent-soft rounded-lg p-3 text-xs text-accent leading-relaxed">
                <p className="font-medium mb-1">💡 字段建议</p>
                <p>{(profile.字段建议 || []).find(a => a.字段 === detailField)?.理由 || '该字段可按需用于分析'}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Missing values modal */}
      {showMissing && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={() => setShowMissing(false)}>
          <div className="bg-white popup-surface rounded-xl shadow-xl max-w-lg w-full mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">缺失值详情</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none" onClick={() => setShowMissing(false)}>✕</button>
            </div>
            <div className="p-5">
              {missingFields.length > 0 ? (
                <>
                  <table className="w-full text-sm">
                    <thead><tr className="text-xs text-gray-400 border-b border-gray-100"><th className="text-left py-2 font-medium">字段名</th><th className="text-left py-2 font-medium">缺失率</th></tr></thead>
                    <tbody>
                      {missingFields.map((mf, i) => (
                        <tr key={i}><td className="py-2.5">{mf.split('（')[0]}</td><td className="py-2.5 text-orange-600">{mf.split('（')[1]?.replace('）', '') || '—'}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex gap-3 mt-5">
                    <button className="px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all" onClick={() => { setShowMissing(false); navigate('/analysis'); }}>分析时自动忽略缺失行</button>
                    <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => { setShowMissing(false); handleClean(); }}>先进行数据清洗</button>
                  </div>
                  {/* 优化②：清洗另存为新数据集（保留原始数据） */}
                  <label className="flex items-center gap-2 mt-3 text-xs text-gray-500 cursor-pointer select-none">
                    <input type="checkbox" className="accent-accent" checked={cleanAsNew} onChange={(e) => setCleanAsNew(e.target.checked)} />
                    另存为新数据集（保留原始数据）
                  </label>
                  {cleanAsNew && (
                    <input
                      className="mt-2 w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                      placeholder={`新数据集名称（默认：${dataset?.文件名}-已清洗）`}
                      value={cleanNewName}
                      onChange={(e) => setCleanNewName(e.target.value)}
                      maxLength={120}
                    />
                  )}
                </>
              ) : (
                <p className="text-sm text-gray-500 text-center py-4">暂无缺失值</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 清洗结果弹窗 */}
      {cleanResult && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={() => setCleanResult(null)}>
          <div className="bg-white popup-surface rounded-xl shadow-xl max-w-md w-full mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">清洗完成</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none" onClick={() => setCleanResult(null)}>✕</button>
            </div>
            <div className="p-5 text-sm space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">清洗前</p><p className="text-sm mt-1 font-mono">{cleanResult.原行数} 行</p></div>
                <div className="bg-green-50 rounded-lg p-3"><p className="text-xs text-green-600">清洗后</p><p className="text-sm mt-1 font-mono text-green-700">{cleanResult.清洗后行数} 行</p></div>
              </div>
              <div className="bg-accent-soft rounded-lg p-3 text-xs text-accent">
                <p className="font-medium mb-1">操作摘要</p>
                <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(cleanResult.操作摘要, null, 2)}</pre>
              </div>
              <button className="w-full py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all" onClick={() => { setCleanResult(null); navigate('/analysis'); }}>前往分析</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
