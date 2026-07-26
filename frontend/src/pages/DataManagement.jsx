import { useState } from 'react';
import { Upload, Download, Database, FileText, AlertTriangle, Search, ChevronRight, Sparkles } from 'lucide-react';
import { uploadFile, loadExample, getDataset } from '../api';

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
  const [dataset, setDataset] = useState(null);
  const [profile, setProfile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [detailField, setDetailField] = useState(null);
  const [showMissing, setShowMissing] = useState(false);

  async function handleUpload(file) {
    setError('');
    setUploading(true);
    setProgress(0);
    const timer = setInterval(() => setProgress((v) => Math.min(v + Math.random() * 18 + 5, 95)), 200);
    try {
      const res = await uploadFile(file);
      clearInterval(timer);
      setProgress(100);
      setTimeout(() => {
        setDataset(res);
        setProfile(res.数据画像);
        setUploading(false);
      }, 400);
    } catch (e) {
      clearInterval(timer);
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
          <span className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />系统正常
          </span>
          <span className="flex items-center gap-1 text-xs text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded border border-indigo-200 cursor-default" title="开启后自动识别日期/分类/数值字段">
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
          dataset ? 'border border-emerald-200 bg-emerald-50/50 px-5 py-3' : 'border-2 border-dashed border-gray-300 hover:border-indigo-400 hover:bg-indigo-50/30 px-6 py-10'
        }`}
      >
        <input id="file-input" type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])} />
        {uploading ? (
          <div className="max-w-sm mx-auto">
            <div className="flex items-center gap-3 mb-2">
              <svg className="w-5 h-5 text-indigo-500 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
              <span className="text-sm text-gray-500">正在解析文件结构，请稍候...</span>
            </div>
            <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${progress}%` }} /></div>
          </div>
        ) : dataset ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-emerald-500" />
              <span className="text-sm text-gray-700">已加载数据集：{dataset.文件名}（{profile?.行数} 行）</span>
            </div>
            <div className="flex gap-2">
              <button className="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-white" onClick={(e) => { e.stopPropagation(); setDataset(null); setProfile(null); }}>重新上传</button>
            </div>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="text-sm text-gray-500 mb-1">点击上传或拖拽文件到此处</p>
            <p className="text-xs text-gray-400">支持 .csv / .xlsx / .xls 格式，单文件不超过 50MB</p>
          </>
        )}
        {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      </div>

      {/* Stats */}
      {profile && (
        <div className="grid grid-cols-4 gap-4 mt-6">
          <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow">
            <div className="flex items-center gap-2"><Database className="w-4 h-4 text-gray-400" /><span className="text-xs text-gray-400">总行数</span></div>
            <p className="text-2xl font-medium text-gray-900 mt-1">{profile.行数.toLocaleString()}</p>
            <p className="text-xs text-gray-400 mt-1">数据量正常，可流畅分析</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow">
            <div className="flex items-center gap-2"><FileText className="w-4 h-4 text-gray-400" /><span className="text-xs text-gray-400">字段数</span></div>
            <p className="text-2xl font-medium text-gray-900 mt-1">{profile.列数}</p>
            <p className="text-xs text-gray-400 mt-1">日期 {profile.日期字段?.length || 0} / 分类 {profile.分类字段?.length || 0} / 数值 {profile.数值字段?.length || 0}</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow relative overflow-hidden">
            <div className="absolute -top-4 -right-4 w-16 h-16 bg-gradient-to-br from-emerald-100 to-transparent opacity-60 rounded-full" />
            <div className="flex items-center gap-2"><span className="text-emerald-600 text-lg">✓</span><span className="text-xs text-gray-400">数据质量评级</span></div>
            <p className="text-2xl font-semibold text-emerald-700 mt-1">{qualityLevel}</p>
            <p className="text-xs text-gray-400 mt-1">{qualityDesc}</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow cursor-pointer" style={{ borderLeft: '3px solid #f97316' }} onClick={() => setShowMissing(true)}>
            <div className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-orange-500" /><span className="text-xs text-gray-400">缺失值数量</span></div>
            <p className="text-2xl font-medium text-orange-600 mt-1">{missingCount}</p>
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
                <input className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg bg-gray-50 focus:outline-none focus:border-indigo-400 focus:bg-white" placeholder="搜索字段名..." value={search} onChange={(e) => setSearch(e.target.value)} />
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
                    <button className="text-xs text-indigo-600 hover:bg-indigo-50 px-2 py-1 rounded" onClick={(e) => { e.stopPropagation(); setDetailField(field); }}>预览</button>
                    <button className="text-xs text-indigo-600 hover:bg-indigo-50 px-2 py-1 rounded">加入分析</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Quick actions */}
      {profile && (
        <div className="grid grid-cols-3 gap-4 mt-6">
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm">
            <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center text-lg">📊</div>
            <div><p className="text-sm font-medium text-gray-700">基于此数据集新建分析</p><p className="text-xs text-gray-400 mt-0.5">自动带入当前数据集上下文</p></div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm">
            <div className="w-10 h-10 rounded-lg bg-orange-50 flex items-center justify-center text-lg">🧹</div>
            <div><p className="text-sm font-medium text-gray-700">一键基础清洗</p><p className="text-xs text-gray-400 mt-0.5">去重 / 填充缺失 / 删除空行</p></div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50/50 transition-all hover:shadow-sm">
            <div className="w-10 h-10 rounded-lg bg-cyan-50 flex items-center justify-center text-lg">📋</div>
            <div><p className="text-sm font-medium text-gray-700">生成数据质量报告</p><p className="text-xs text-gray-400 mt-0.5">详细的数据完整性分析</p></div>
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
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">类型</p><p className="text-sm mt-1">{typeLabels[inferType(detailField, profile)]}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">唯一值</p><p className="text-sm mt-1 font-mono">{profile.行数}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">空值数量</p><p className="text-sm mt-1 font-mono">—</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">示例值</p><p className="text-sm mt-1 text-gray-500 truncate">数据预览中查看</p></div>
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
                    <button className="px-4 py-2 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-all">分析时自动忽略缺失行</button>
                    <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all">先进行数据清洗</button>
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-500 text-center py-4">暂无缺失值</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
