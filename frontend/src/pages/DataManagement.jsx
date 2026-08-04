import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Download, Database, FileText, AlertTriangle, Search, Sparkles, Loader2, BarChart3, LineChart } from 'lucide-react';
import { uploadFile, loadExample, cleanDataset, healthCheck } from '../api';
import { useApp } from '../AppContext';

// 演示模式（vite --mode demo 构建）：打开页面自动加载示例数据，零基础用户无需上传即可体验
const DEMO_MODE = import.meta.env.VITE_DEMO === '1';

const typeColors = {
  date: 'bg-cyan-50 text-cyan-600 border-cyan-200',
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
  const [backendOk, setBackendOk] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [detailField, setDetailField] = useState(null);
  const [showMissing, setShowMissing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [cleanResult, setCleanResult] = useState(null);
  // 清洗选项（阶段 7：可配置）
  const [cleanOps, setCleanOps] = useState({
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

  async function handleUpload(file) {
    setError('');
    setUploading(true);
    try {
      const res = await uploadFile(file);
      setDataset(res);
      setProfile(res.数据画像);
      setAppDataset({ 数据集ID: res.数据集ID, 文件名: res.文件名, 行数: res.行数, 数据画像: res.数据画像 });
      setUploading(false);
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

  function handleDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
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
      });
      setCleanResult(res);
      setProfile(res.数据画像);
      setDataset(prev => ({ ...prev, 行数: res.清洗后行数, 数据画像: res.数据画像 }));
      // 同步 AppContext，让分析页使用清洗后数据
      setAppDataset(prev => prev ? { ...prev, 行数: res.清洗后行数, 数据画像: res.数据画像 } : prev);
    } catch (e) {
      setError('清洗失败: ' + e.message);
    }
    setCleaning(false);
  }

  function handleJoinAnalysis(field) {
    if (!dataset) return;
    setAppDataset(prev => ({ ...prev, focusField: field }));
    navigate('/analysis');
  }

  function handleNewAnalysis() {
    if (!dataset) return;
    navigate('/analysis');
  }

  function handleCleanIgnore() {
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
        <input id="file-input" type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])} />
        {uploading ? (
          <div className="max-w-sm mx-auto">
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-accent-soft0 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
              <span className="text-sm text-gray-500">正在解析文件结构，请稍候...</span>
            </div>
          </div>
        ) : dataset ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-emerald-500" />
              <span className="text-sm text-gray-700">已加载数据集：{dataset.文件名}（{profile?.行数} 行）</span>
            </div>
            <div className="flex gap-2">
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
            <div className="w-10 h-10 rounded-lg bg-cyan-50 flex items-center justify-center"><LineChart className="w-5 h-5 text-cyan-600" /></div>
            <div><p className="text-sm font-medium text-gray-700">查看报表</p><p className="text-xs text-gray-400 mt-0.5">浏览已生成的智能分析报告</p></div>
          </div>
        </div>
      )}

      {/* Field detail modal */}
      {detailField && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={() => setDetailField(null)}>
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 overflow-hidden animate-in" onClick={(e) => e.stopPropagation()}>
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
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-900">缺失值详情</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none" onClick={() => setShowMissing(false)}>✕</button>
            </div>
            <div className="p-5">
              {missingFields.length > 0 ? (
                <>
                  <table className="w-full text-sm">
                    <thead><tr className="text-xs text-gray-400 border-b border-gray-100"><th className="text-left py-2 font-medium">字段名</th><th className="text-left py-2 font-medium">缺失数量</th></tr></thead>
                    <tbody>
                      {missingFields.map((mf, i) => (
                        <tr key={i}><td className="py-2.5">{mf.split('（')[0]}</td><td className="py-2.5 text-orange-600">{mf.split('（')[1]?.replace('）', '') || '—'}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex gap-3 mt-5">
                    <button className="px-4 py-2 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-all" onClick={() => { setShowMissing(false); navigate('/analysis'); }}>分析时自动忽略缺失行</button>
                    <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => { setShowMissing(false); handleClean(); }}>先进行数据清洗</button>
                  </div>
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
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
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
              <button className="w-full py-2 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-all" onClick={() => { setCleanResult(null); navigate('/analysis'); }}>前往分析</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
