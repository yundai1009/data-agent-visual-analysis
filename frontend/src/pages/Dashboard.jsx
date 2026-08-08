import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutDashboard, Plus, Trash2, Pencil, ExternalLink, X, ImageOff, ChevronLeft, ChevronRight } from 'lucide-react';
import { listDashboards, getDashboard, createDashboard, updateDashboard, deleteDashboard, listReports } from '../api';
import EChartsChart from '../components/EChartsChart';

// ---- 通用弹窗（名称 + 多选报表）----

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-[var(--shadow-card-lg)] w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400"><X className="w-4 h-4" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [boards, setBoards] = useState([]);          // [{看板ID, 名称, 报表数}]
  const [currentId, setCurrentId] = useState(null);  // 当前选中看板ID
  const [detail, setDetail] = useState(null);        // { 名称, 报表列表: [{报表ID, 标题, 图表类型, 报表}] }
  const [allReports, setAllReports] = useState([]);  // 全部历史报表（供添加）
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 弹窗状态
  const [showCreate, setShowCreate] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [newName, setNewName] = useState('');
  const [selectedIds, setSelectedIds] = useState([]);

  const loadBoards = async () => {
    try {
      const res = await listDashboards();
      const list = res?.看板列表 || [];
      setBoards(list);
      return list;
    } catch (e) {
      setError('看板列表加载失败：' + (e.message || e));
      return [];
    }
  };

  // B19 修复：看板切换序号守卫（快速切换时旧响应不覆盖当前看板）
  const loadSeqRef = useRef(0);
  const loadDetail = async (id) => {
    const seq = ++loadSeqRef.current;
    try {
      const res = await getDashboard(id);
      if (loadSeqRef.current !== seq) return;
      setDetail(res);
    } catch (e) {
      if (loadSeqRef.current !== seq) return;
      setError('看板详情加载失败：' + (e.message || e));
      setDetail(null);
    }
  };

  // 挂载：加载看板列表 + 报表列表（供添加弹窗使用）
  useEffect(() => {
    (async () => {
      setLoading(true);
      const list = await loadBoards();
      try {
        const r = await listReports(100);
        setAllReports(r?.报表列表 || []);
      } catch { /* 报表列表失败不阻塞看板 */ }
      if (list.length > 0) {
        setCurrentId(list[0].看板ID);
        await loadDetail(list[0].看板ID);
      }
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchBoard = async (id) => {
    setCurrentId(id);
    await loadDetail(id);
  };

  // 新建看板：名称 + 首次选择报表
  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      await createDashboard(name, selectedIds);
      setNewName('');
      setSelectedIds([]);
      setShowCreate(false);
      const list = await loadBoards();
      // 选中新看板（列表按创建时间倒序，第一条即最新）
      if (list.length > 0) {
        setCurrentId(list[0].看板ID);
        await loadDetail(list[0].看板ID);
      }
    } catch (e) {
      setError('新建看板失败：' + (e.message || e));
    }
  };

  // 添加报表到当前看板
  const handleAdd = async () => {
    if (!currentId) return;
    const existed = new Set((detail?.报表列表 || []).map((r) => r.报表ID));
    const merged = [...existed, ...selectedIds.filter((id) => !existed.has(id))];
    try {
      await updateDashboard(currentId, detail.名称, merged);
      setSelectedIds([]);
      setShowAdd(false);
      await loadDetail(currentId);
    } catch (e) {
      setError('添加报表失败：' + (e.message || e));
    }
  };

  // 移除报表
  const handleRemove = async (reportId) => {
    if (!currentId || !detail) return;
    const ids = (detail.报表列表 || []).map((r) => r.报表ID).filter((id) => id !== reportId);
    try {
      await updateDashboard(currentId, detail.名称, ids);
      await loadDetail(currentId);
    } catch (e) {
      setError('移除报表失败：' + (e.message || e));
    }
  };

  // 调整顺序（左移/右移），持久化到后端
  const handleMove = async (index, dir) => {
    if (!currentId || !detail) return;
    const list = [...(detail.报表列表 || [])];
    const j = index + dir;
    if (j < 0 || j >= list.length) return;
    [list[index], list[j]] = [list[j], list[index]];
    try {
      await updateDashboard(currentId, detail.名称, list.map((r) => r.报表ID));
      await loadDetail(currentId);
    } catch (e) {
      setError('调整顺序失败：' + (e.message || e));
    }
  };

  // 重命名
  const handleRename = async () => {
    if (!currentId || !detail) return;
    const name = newName.trim();
    if (!name) return;
    try {
      await updateDashboard(currentId, name, (detail.报表列表 || []).map((r) => r.报表ID));
      setShowRename(false);
      setNewName('');
      await loadBoards();
      await loadDetail(currentId);
    } catch (e) {
      setError('重命名失败：' + (e.message || e));
    }
  };

  // 删除看板
  const handleDelete = async () => {
    if (!currentId || !detail) return;
    if (!window.confirm(`确定删除看板「${detail.名称}」？此操作不可恢复。`)) return;
    try {
      await deleteDashboard(currentId);
      const list = await loadBoards();
      if (list.length > 0) {
        setCurrentId(list[0].看板ID);
        await loadDetail(list[0].看板ID);
      } else {
        setCurrentId(null);
        setDetail(null);
      }
    } catch (e) {
      setError('删除看板失败：' + (e.message || e));
    }
  };

  const reports = detail?.报表列表 || [];
  const addedIds = new Set(reports.map((r) => r.报表ID));
  const addable = allReports.filter((r) => !addedIds.has(r.报表ID));

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900 flex items-center gap-2">
            <LayoutDashboard className="w-5 h-5 text-accent" /> 图表看板
          </h1>
          <p className="text-xs text-gray-400 mt-1">把多份报表放到同一页面对比查看</p>
          {error && <p className="mt-1.5 text-xs text-red-500">{error}</p>}
        </div>
        <button
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
          onClick={() => { setNewName(''); setSelectedIds([]); setShowCreate(true); }}
        >
          <Plus className="w-3.5 h-3.5" /> 新建看板
        </button>
      </div>

      {/* 看板切换栏 */}
      {boards.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-4">
          {boards.map((b) => (
            <button
              key={b.看板ID}
              onClick={() => switchBoard(b.看板ID)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-all border ${
                currentId === b.看板ID
                  ? 'bg-accent text-white border-accent font-medium'
                  : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50'
              }`}
            >
              {b.名称} <span className={currentId === b.看板ID ? 'text-accent-soft' : 'text-gray-400'}>({b.报表数})</span>
            </button>
          ))}
        </div>
      )}

      {/* 当前看板工具条 */}
      {detail && (
                <div className="flex items-center gap-2 flex-wrap mb-4 px-4 py-2.5 rounded-xl bg-white shadow-[var(--shadow-card)]">
          <span className="text-sm font-medium text-gray-800">{detail.名称}</span>
          <span className="text-[11px] text-gray-400">共 {reports.length} 张图</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all"
              onClick={() => { setNewName(detail.名称); setShowRename(true); }}
            >
              <Pencil className="w-3 h-3" /> 重命名
            </button>
            <button
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all"
              onClick={() => { setSelectedIds([]); setShowAdd(true); }}
            >
              <Plus className="w-3 h-3" /> 添加报表
            </button>
            <button
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-red-100 text-xs text-red-500 hover:bg-red-50 transition-all"
              onClick={handleDelete}
            >
              <Trash2 className="w-3 h-3" /> 删除
            </button>
          </div>
        </div>
      )}

      {/* 空状态 */}
      {!loading && boards.length === 0 && (
                <div className="bg-white rounded-2xl shadow-[var(--shadow-card)] p-14 text-center">
          <ImageOff className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500 mb-1">还没有看板</p>
          <p className="text-xs text-gray-400 mb-5">先在「智能分析」生成报表，再挑选多份报表建看板对比</p>
          <div className="flex gap-2 justify-center">
            <button className="px-4 py-2 rounded-lg bg-accent text-white text-xs hover:bg-accent-deep transition-all" onClick={() => navigate('/analysis')}>
              去生成报表
            </button>
            <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => { setNewName(''); setSelectedIds([]); setShowCreate(true); }}>
              直接新建看板
            </button>
          </div>
        </div>
      )}

      {/* 图表网格 */}
      {reports.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {reports.map((item, i) => {
            const cfg = item.报表?.图表配置 || {};
            const chartTypeKey = cfg.类型 || 'bar';
            const conclusion = item.报表?.结论 || '';
            return (
                            <div key={item.报表ID} className="bg-white rounded-2xl shadow-[var(--shadow-card)] overflow-hidden">
                <div className="flex items-center gap-2 px-4 pt-3.5">
                  <span className="text-[11px] px-2 py-0.5 rounded-md bg-accent-soft text-accent font-medium shrink-0">{item.图表类型 || '图表'}</span>
                  <p className="text-xs font-medium text-gray-700 truncate">{item.标题}</p>
                  <div className="ml-auto flex items-center gap-0.5">
                    <button
                      title="左移"
                      disabled={i === 0}
                      className="p-1 rounded hover:bg-gray-100 text-gray-300 hover:text-accent transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
                      onClick={() => handleMove(i, -1)}
                    >
                      <ChevronLeft className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="右移"
                      disabled={i >= reports.length - 1}
                      className="p-1 rounded hover:bg-gray-100 text-gray-300 hover:text-accent transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
                      onClick={() => handleMove(i, 1)}
                    >
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="移除本图"
                      className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-500 transition-colors"
                      onClick={() => handleRemove(item.报表ID)}
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="查看完整报表"
                      className="p-1 rounded hover:bg-gray-100 text-gray-300 hover:text-accent transition-colors"
                      onClick={() => navigate(`/report/${item.报表ID}`)}
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
                {chartTypeKey === 'table' ? (
                  <p className="text-xs text-gray-400 text-center py-10">表格类报表请到详情页查看</p>
                ) : (
                  <EChartsChart key={i} chartType={chartTypeKey} chartConfig={cfg} height={280} />
                )}
                {conclusion && (
                  <p className="px-4 pb-3.5 text-[11px] text-gray-500 leading-relaxed line-clamp-2">{conclusion}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 新建看板弹窗 */}
      {showCreate && (
        <Modal title="新建看板" onClose={() => setShowCreate(false)}>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="看板名称，如：销售月度对比"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent mb-3"
          />
          <p className="text-xs text-gray-400 mb-2">选择要放入看板的报表（可稍后添加）</p>
          <div className="max-h-56 overflow-auto border border-gray-100 rounded-lg divide-y divide-gray-50 mb-4">
            {allReports.length === 0 && <p className="text-xs text-gray-400 text-center py-6">暂无历史报表，请先到「智能分析」生成</p>}
            {allReports.map((r) => (
              <label key={r.报表ID} className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-gray-50 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-[#0f4c81]"
                  checked={selectedIds.includes(r.报表ID)}
                  onChange={(e) => setSelectedIds((prev) => e.target.checked ? [...prev, r.报表ID] : prev.filter((id) => id !== r.报表ID))}
                />
                <span className="text-xs text-gray-700 truncate flex-1">{r.标题}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 shrink-0">{r.图表类型}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50" onClick={() => setShowCreate(false)}>取消</button>
            <button className="px-4 py-2 rounded-lg bg-accent text-white text-xs hover:bg-accent-deep disabled:opacity-40" disabled={!newName.trim()} onClick={handleCreate}>
              创建
            </button>
          </div>
        </Modal>
      )}

      {/* 添加报表弹窗 */}
      {showAdd && (
        <Modal title={`添加报表到「${detail?.名称}」`} onClose={() => setShowAdd(false)}>
          <div className="max-h-56 overflow-auto border border-gray-100 rounded-lg divide-y divide-gray-50 mb-4">
            {addable.length === 0 && <p className="text-xs text-gray-400 text-center py-6">所有报表都已加入，或暂无更多报表</p>}
            {addable.map((r) => (
              <label key={r.报表ID} className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-gray-50 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-[#0f4c81]"
                  checked={selectedIds.includes(r.报表ID)}
                  onChange={(e) => setSelectedIds((prev) => e.target.checked ? [...prev, r.报表ID] : prev.filter((id) => id !== r.报表ID))}
                />
                <span className="text-xs text-gray-700 truncate flex-1">{r.标题}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 shrink-0">{r.图表类型}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50" onClick={() => setShowAdd(false)}>取消</button>
            <button className="px-4 py-2 rounded-lg bg-accent text-white text-xs hover:bg-accent-deep disabled:opacity-40" disabled={selectedIds.length === 0} onClick={handleAdd}>
              添加 {selectedIds.length > 0 ? `(${selectedIds.length})` : ''}
            </button>
          </div>
        </Modal>
      )}

      {/* 重命名弹窗 */}
      {showRename && (
        <Modal title="重命名看板" onClose={() => setShowRename(false)}>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleRename()}
            placeholder="新名称"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent mb-4"
          />
          <div className="flex justify-end gap-2">
            <button className="px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50" onClick={() => setShowRename(false)}>取消</button>
            <button className="px-4 py-2 rounded-lg bg-accent text-white text-xs hover:bg-accent-deep disabled:opacity-40" disabled={!newName.trim()} onClick={handleRename}>
              保存
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}