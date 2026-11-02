// 看板页（面试讲解）
//
// 做了什么：把多张已生成的报表组合成"看板"——新建/编辑看板
//   （名称 + 勾选报表）、网格/轮播展示、跳转原报表。
// 为什么这样设计：
//   - 看板 = 报表的"精选集"（名称 + 报表ID列表），数据都在后端
//     dashboards 接口，前端只做组合与展示，不复制报表内容；
//   - 展示用 EChartsChart 复用报表图表组件，同一套渲染逻辑。
// 删除它会怎样：用户失去"把分析结果汇总成一页"的能力。
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutDashboard, Plus, Trash2, Pencil, ExternalLink, X, ImageOff, ChevronLeft, ChevronRight, LayoutGrid, Network, Move, Download, FileText, Image as ImageIcon, RefreshCw, Bell } from 'lucide-react';
import { listDashboards, getDashboard, createDashboard, updateDashboard, deleteDashboard, listReports, listDatasets, exportDashboard } from '../api';
import EChartsChart from '../components/EChartsChart';
import LineageGraph from '../components/LineageGraph';
import LineageDrawer from '../components/LineageDrawer';
import { 构建血缘图 } from '../utils/看板血缘';
import { 计算拼接尺寸, 构建打印HTML } from '../utils/看板导出';
import { 取点击维度, 应用下钻 } from '../utils/看板联动';

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

  // 阶段 六十：网格 ↔ 关系 双视图 + 血缘数据；阶段八十四：自由画布视图
  const [视图, set视图] = useState('grid');            // 'grid' | 'lineage' | 'canvas'
  const [数据集列表, set数据集列表] = useState([]);     // listDatasets(200).数据集列表
  const [血缘提示, set血缘提示] = useState('');         // 数据集元信息加载失败时的降级提示
  const [选中节点ID, set选中节点ID] = useState('');
  // 阶段八十九：血缘图导出 PNG（LineageGraph 通过 ref 暴露 导出PNG()）
  const 血缘图Ref = useRef(null);
  const [导出血缘中, set导出血缘中] = useState(false);

  // 阶段八十五：看板全局筛选器（只对前端已加载的报表数据做客户端过滤/高亮，不影响后端）
  const [筛选维度, set筛选维度] = useState('');          // 选中的维度字段
  const [筛选值, set筛选值] = useState('');              // 选中的维度值
  // 注意：筛选选项**不建 state**。它是 reports 的纯派生值（useMemo 直接消费）；
  // 早期写成「useMemo + useEffect 同步进 state」时，detail 为 null 的那一帧
  // reports 是 `|| []` 新建的字面量数组，useMemo 每次渲染都重建 →
  // set筛选选项 每帧触发重渲染 → 无限渲染循环（vitest worker 直接烧到 4GB/874s CPU）。
  const [导出中, set导出中] = useState(false);
  // 阶段八十九 · B6：每张图独立的下钻条件栈（报表ID → [{维度,值}, …]）
  const [下钻集, set下钻集] = useState({});
  // 阶段八十九 · B7：看板刷新与订阅——手动刷新 + 每 30s 自动拉最新报表数据
  const [刷新中, set刷新中] = useState(false);
  const [自动刷新, set自动刷新] = useState(false);

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
      // 阶段八十四：layout 兼容旧看板（后端已保证是对象，这里再兜一层）
      const 布局 = (res?.布局 && typeof res.布局 === 'object') ? res.布局 : {};
      setDetail({ ...res, 布局 });
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
    set选中节点ID('');            // 阶段 六十：旧看板的节点在图里已不存在
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
      await updateDashboard(currentId, detail.名称, merged, detail.布局);
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
    // 同步清掉该报表的布局（否则留下悬空坐标）
    const nextLayout = { ...(detail.布局 || {}) };
    delete nextLayout[reportId];
    try {
      await updateDashboard(currentId, detail.名称, ids, nextLayout);
      await loadDetail(currentId);
    } catch (e) {
      setError('移除报表失败：' + (e.message || e));
    }
  };

  // 阶段八十四：自由画布——拖拽移动 / 右下角缩放，松手落库布局
  const [画布拖拽, set画布拖拽] = useState(null);   // { id, 起点X, 起点Y, 初始X, 初始Y, 初始W, 初始H, 模式 }
  const [画布布局, set画布布局] = useState(null);    // 拖拽过程中的实时布局（null = 未在拖拽）
  const 画布布局Ref = useRef(null);                 // 同步的最新布局，避免 effect 闭包里的陈旧值

  useEffect(() => { 画布布局Ref.current = 画布布局; }, [画布布局]);

  const 默认尺寸 = (chartTypeKey) => {
    const wide = new Set(['table', 'heatmap', 'sankey', 'sunburst', 'boxplot', 'treemap']);
    return wide.has(chartTypeKey) ? { w: 720, h: 400 } : { w: 440, h: 320 };
  };

  const 当前布局 = () => 画布布局 || (detail?.布局 || {});

  // 种子布局：进入画布视图时把「已存布局 + 自动网格」合并成一份完整坐标，
  // 保证每张卡都有显式 {x,y,w,h}（否则只拖过的那张有坐标，其余卡会与它重叠）
  const 种子布局 = () => {
    const base = { ...(detail?.布局 || {}) };
    (detail?.报表列表 || []).forEach((item, idx) => {
      if (base[item.报表ID]) return;
      const col = idx % 2;
      const row = Math.floor(idx / 2);
      const size = 默认尺寸(item.报表?.图表配置?.类型);
      base[item.报表ID] = { x: col * (size.w + 24), y: row * (size.h + 24), w: size.w, h: size.h };
    });
    return base;
  };

  useEffect(() => {
    if (视图 !== 'canvas' || !detail) return;
    set画布布局(种子布局());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [视图, currentId]);

  const 卡片位置 = (item) => {
    const pos = 当前布局()[item.报表ID];
    if (pos) return pos;
    // 无布局：回落自动网格（按列表顺序，2 列）
    const idx = (detail?.报表列表 || []).findIndex((r) => r.报表ID === item.报表ID);
    const col = idx % 2;
    const row = Math.floor((idx | 0) / 2);
    const size = 默认尺寸(item.报表?.图表配置?.类型);
    return { x: col * (size.w + 24), y: row * (size.h + 24), w: size.w, h: size.h };
  };

  const 落库布局 = async (nextLayout) => {
    if (!currentId || !detail) return;
    try {
      await updateDashboard(currentId, detail.名称, (detail.报表列表 || []).map((r) => r.报表ID), nextLayout);
      setDetail({ ...detail, 布局: nextLayout });
    } catch (e) {
      setError('保存画布布局失败：' + (e.message || e));
    }
  };

  const handleCardMouseDown = (e, item) => {
    if (视图 !== 'canvas') return;
    e.preventDefault();
    const pos = 卡片位置(item);
    set画布拖拽({ id: item.报表ID, 起点X: e.clientX, 起点Y: e.clientY, 初始X: pos.x, 初始Y: pos.y, 初始W: pos.w, 初始H: pos.h, 模式: 'move' });
  };

  const handleResizeMouseDown = (e, item) => {
    if (视图 !== 'canvas') return;
    e.preventDefault();
    e.stopPropagation();
    const pos = 卡片位置(item);
    set画布拖拽({ id: item.报表ID, 起点X: e.clientX, 起点Y: e.clientY, 初始X: pos.x, 初始Y: pos.y, 初始W: pos.w, 初始H: pos.h, 模式: 'resize' });
  };

  // 全局 mousemove / mouseup：拖拽与缩放都在 window 上跟手，避免卡片内 mouseleave 断流
  useEffect(() => {
    if (!画布拖拽) return;
    const onMove = (e) => {
      const dx = e.clientX - 画布拖拽.起点X;
      const dy = e.clientY - 画布拖拽.起点Y;
      const base = { ...(画布布局Ref.current || {}) };
      const 原 = base[画布拖拽.id] || { x: 画布拖拽.初始X, y: 画布拖拽.初始Y, w: 画布拖拽.初始W, h: 画布拖拽.初始H };
      let next;
      if (画布拖拽.模式 === 'resize') {
        next = { ...base, [画布拖拽.id]: { ...原, w: Math.max(240, 画布拖拽.初始W + dx), h: Math.max(180, 画布拖拽.初始H + dy) } };
      } else {
        next = { ...base, [画布拖拽.id]: { ...原, x: Math.max(0, 画布拖拽.初始X + dx), y: Math.max(0, 画布拖拽.初始Y + dy) } };
      }
      set画布布局(next);
    };
    const onUp = () => {
      const finalLayout = 画布布局Ref.current || {};
      set画布拖拽(null);
      set画布布局(null);
      落库布局(finalLayout);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [画布拖拽]);


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

  // ── 原生拖拽排序（HTML5 DnD，零依赖）──
  const [dragIndex, setDragIndex] = useState(null);   // 正在拖拽的卡片下标
  const [overIndex, setOverIndex] = useState(null);   // 悬停的目标下标（视觉反馈）

  const resetDrag = () => { setDragIndex(null); setOverIndex(null); };

  const handleDragStart = (e, index) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', String(index)); } catch { /* 兼容 */ }
  };

  const handleDragOver = (e, index) => {
    e.preventDefault();                       // 允许 drop（默认禁止）
    e.dataTransfer.dropEffect = 'move';
    if (overIndex !== index) setOverIndex(index);
  };

  // drop：把 dragIndex 的卡片插到目标位置，并持久化新顺序
  const handleDrop = async (e, index) => {
    e.preventDefault();
    const from = dragIndex;
    resetDrag();
    if (from === null || from === index) return;
    const list = [...(detail.报表列表 || [])];
    const [moved] = list.splice(from, 1);
    list.splice(index, 0, moved);
    try {
      await updateDashboard(currentId, detail.名称, list.map((r) => r.报表ID));
      await loadDetail(currentId);
    } catch (err) {
      setError('拖拽排序失败：' + (err.message || err));
    }
  };

  // 智能排版：按图表类型分配卡片宽度（xl 两列栅格下）
  // 宽图（表格/热力图/桑基/旭日/箱线）通栏占整行；标准图（饼图/折线/柱状等）并排占半行
  const spanClassFor = (chartTypeKey) => {
    const wide = new Set(['table', 'heatmap', 'sankey', 'sunburst', 'boxplot', 'treemap']);
    return wide.has(chartTypeKey) ? 'xl:col-span-2' : 'xl:col-span-1';
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

  // 阶段八十五：看板导出——打包当前看板全部报表为 ZIP（调 exportDashboard，浏览器触发下载）
  const handleExportBoard = async () => {
    if (!currentId) return;
    set导出中(true);
    setError('');
    try {
      const { blob, filename } = await exportDashboard(currentId, 'xlsx');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError('看板导出失败：' + (e.message || e));
    } finally {
      set导出中(false);
    }
  };

  // 阶段八十九 · B5：看板导出 PDF/图片。grid 视图每张图经 ref 暴露 导出PNG()（EChartsChart
  // 的 useImperativeHandle），收集全部 dataURL 后：图片 = canvas 拼接成一张 PNG 下载；
  // PDF = 打开打印窗口（浏览器/Electron 都可「另存为 PDF」）。
  const 图Refs = useRef(new Map());
  const 取图Ref = (id) => (node) => {
    if (node) 图Refs.current.set(id, node);
    else 图Refs.current.delete(id);
  };
  const 收集图dataURL = () =>
    reports
      .filter(r => (r.报表?.图表配置?.类型 || 'bar') !== 'table')
      .map(r => ({
        报表ID: r.报表ID,
        标题: r.标题 || '未命名图表',
        类型: r.图表类型 || r.报表?.图表配置?.类型 || '图表',
        结论: r.报表?.结论 || '',
        dataURL: 图Refs.current.get(r.报表ID)?.导出PNG?.() || null,
      }))
      .filter(c => c.dataURL);

  const handleExportImage = () => {
    const 卡片 = 收集图dataURL();
    if (!卡片.length) { setError('当前看板没有可导出的图表（表格类报表请到详情页导出）'); return; }
    try {
      const { 宽, 高, 格 } = 计算拼接尺寸(卡片.map(() => ({ w: 640, h: 400 })));
      const canvas = document.createElement('canvas');
      canvas.width = 宽; canvas.height = 高;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, 宽, 高);
      // 先画第一张，等其解码后再画后续（同源 dataURL，异步 load）
      let 已完成 = 0;
      卡片.forEach((c, i) => {
        const img = new Image();
        img.onload = () => {
          ctx.drawImage(img, 格[i].x, 格[i].y, 640, 400);
          已完成 += 1;
          if (已完成 === 卡片.length) 下载图片(canvas.toDataURL('image/png'), `${detail?.名称 || '看板'}-看板.png`);
        };
        img.src = c.dataURL;
      });
    } catch (e) {
      setError('看板导出图片失败：' + (e.message || e));
    }
  };

  const handleExportPdf = () => {
    const 卡片 = 收集图dataURL();
    if (!卡片.length) { setError('当前看板没有可导出的图表'); return; }
    try {
      const html = 构建打印HTML({ 看板名: detail?.名称, 卡片, 生成时间: new Date().toLocaleString('zh-CN') });
      const win = window.open('', '_blank');
      if (!win) { setError('浏览器拦截了打印窗口，请允许弹出后重试'); return; }
      win.document.open();
      win.document.write(html);
      win.document.close();
      win.focus();
      // 等图片加载完再触发打印，否则首屏可能缺图
      setTimeout(() => win.print(), 600);
    } catch (e) {
      setError('看板导出 PDF 失败：' + (e.message || e));
    }
  };

  // 下载工具：dataURL 转 blob 触发 <a download>
  const 下载图片 = (dataURL, 名称) => {
    const a = document.createElement('a');
    a.href = dataURL;
    a.download = 名称;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  // 阶段八十九 · B6：点图 → 联动 + 下钻。点中的 {维度, 值} 一分为二：
  //   · 联动：设全局筛选（其它图表按 命中筛选 灰显/高亮）；
  //   · 下钻：给本图追加一层 {维度, 值}，应用下钻() 把 X 轴切到下一维度（到底则只过滤）。
  const handleChartClick = (item, params) => {
    const 命中 = 取点击维度(item.报表?.图表配置 || {}, params);
    if (!命中) return;
    set筛选维度(命中.维度);
    set筛选值(命中.值);
    const id = item.报表ID;
    const 已有 = 下钻集[id] || [];
    // 同一维度重复点击 = 换值而非叠两层（保持栈清晰）
    const 去掉同维 = 已有.filter(c => c.维度 !== 命中.维度);
    set下钻集(prev => ({ ...prev, [id]: [...去掉同维, 命中] }));
  };
  const handleDrillBack = (id) => {
    set下钻集(prev => {
      const 栈 = prev[id] || [];
      const 新栈 = 栈.slice(0, -1);
      const 复制 = { ...prev };
      if (新栈.length) 复制[id] = 新栈;
      else delete 复制[id];
      return 复制;
    });
  };
  const handleDrillClear = (id) => {
    set下钻集(prev => { const 复制 = { ...prev }; delete 复制[id]; return 复制; });
  };

  // 阶段八十九 · B7：手动刷新——重拉当前看板详情（数据可能已被计划任务更新）与看板列表。
  const handleRefresh = async () => {
    if (!currentId || 刷新中) return;
    set刷新中(true);
    try {
      await loadBoards();
      await loadDetail(currentId);
    } finally {
      set刷新中(false);
    }
  };

  // 阶段八十九 · B7：订阅（自动刷新）。每 30s 静默重拉当前看板，不打断用户操作；
  // 切看板/卸载时清定时器；手动刷新时也顺带重置间隔（避免切回来瞬间重复请求）。
  useEffect(() => {
    if (!自动刷新 || !currentId) return;
    const timer = setInterval(() => { loadDetail(currentId); }, 30000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [自动刷新, currentId]);

  // 阶段 六十：数据集元信息（文件名/行数/列数）只在首次切到关系视图时拉，
  // 不让默认的网格视图为血缘多背一个请求
  useEffect(() => {
    if (视图 !== 'lineage' || 数据集列表.length > 0) return;
    let 已取消 = false;
    (async () => {
      try {
        const res = await listDatasets(200);
        if (!已取消) set数据集列表(res?.数据集列表 || []);
      } catch (e) {
        if (!已取消) set血缘提示('数据集信息加载失败（关系图将显示为未知数据集）：' + (e.message || e));
      }
    })();
    return () => { 已取消 = true; };
  }, [视图, 数据集列表.length]);

  // 血缘图数据：看板详情（含图表配置）× 报表列表（含数据集ID）× 数据集列表（含文件名）
  const 报表索引 = useMemo(() => new Map(allReports.map((r) => [r.报表ID, r])), [allReports]);
  const 数据集索引 = useMemo(() => new Map(数据集列表.map((d) => [d.数据集ID, d])), [数据集列表]);
  // 对比报表在 listReports 里只回了一个「首来源」数据集ID，完整来源在 看板详情.报表列表[i].报表.数据集ID列表。
  // 单报表没这个字段，取不到时回落到 [数据集ID]，行为和以前完全一致。
  const 报表源列表索引 = useMemo(() => {
    const m = new Map();
    (detail?.报表列表 || []).forEach((项) => {
      const 列表 = 项?.报表?.数据集ID列表;
      if (Array.isArray(列表) && 列表.length > 0) m.set(项.报表ID, 列表);
    });
    return m;
  }, [detail?.报表列表]);
  const 血缘 = useMemo(
    () => 构建血缘图({ 报表列表: detail?.报表列表 || [], 报表索引, 数据集索引, 报表源列表索引 }),
    [detail?.报表列表, 报表索引, 数据集索引, 报表源列表索引],
  );
  const 选中节点 = 选中节点ID ? 血缘.节点索引[选中节点ID] || null : null;

  const reports = detail?.报表列表 || [];
  const addedIds = new Set(reports.map((r) => r.报表ID));
  const addable = allReports.filter((r) => !addedIds.has(r.报表ID));

  // 阶段八十五：看板全局筛选器——维度取各报表 X轴 / 颜色 / 分组字段，取值取该维度的去重值。
  // 只做客户端过滤/高亮，不触发后端请求；选中后由 命中筛选() 决定每张卡片显示与否。
  // 注意：这里必须直接读 detail?.报表列表 作为依赖，不能依赖上面那行新建的 reports。
  // reports 在 detail===null 时每次渲染都是新的 [] 字面量，依赖它会让本 memo 每次渲染都重建，
  // 一旦结果再被 setState 镜像我（曾经的写法），就会变成无限重渲染——vitest worker 直接烧到 4GB/874s。
  const 筛选选项 = useMemo(() => {
    const 维度集 = new Map();   // 维度名 → Set(取值)
    (detail?.报表列表 || []).forEach((item) => {
      const cfg = item.报表?.图表配置 || {};
      const dims = [cfg.X轴, cfg.颜色, cfg.分组字段].filter(Boolean);
      // 阶段八十九 · B6：取值同时扫 报表数据 与 图表配置.数据——
      // 图表真正渲染的是 图表配置.数据，只看 报表数据 会让「图上能点到的值」在联动筛选里缺席。
      const 行集 = [...(item.报表?.报表数据 || []), ...(Array.isArray(cfg.数据) ? cfg.数据 : [])];
      dims.forEach((d) => {
        const vals = 维度集.get(d) || new Set();
        行集.forEach((row) => {
          if (row && row[d] !== undefined && row[d] !== null && row[d] !== '') vals.add(String(row[d]));
        });
        维度集.set(d, vals);
      });
    });
    const 维度 = [...维度集.keys()].sort();
    const 值 = (筛选维度 && 维度集.get(筛选维度)) ? [...维度集.get(筛选维度)].sort() : [];
    return { 维度, 值 };
  }, [detail?.报表列表, 筛选维度]);

  const 切换维度 = (d) => { set筛选维度(d); set筛选值(''); };

  // 未设筛选 → 全部命中；设了 → 该报表「报表数据 / 图表配置.数据」里有任意行满足 维度==值 才命中
  const 命中筛选 = (item) => {
    if (!筛选维度 || !筛选值) return true;
    const 行集 = [...(item.报表?.报表数据 || []), ...(Array.isArray(item.报表?.图表配置?.数据) ? item.报表.图表配置.数据 : [])];
    return 行集.some(
      (row) => String(row?.[筛选维度] ?? '') === 筛选值,
    );
  };

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
          {/* 阶段八十五：全局筛选器（客户端过滤/高亮，不请求后端） */}
          {筛选选项.维度.length > 0 && (
            <span className="flex items-center gap-1 text-xs">
              <span className="text-gray-400">筛选</span>
              <select
                data-testid="board-filter-dim"
                value={筛选维度}
                onChange={(e) => 切换维度(e.target.value)}
                className="border border-gray-200 rounded-md px-1.5 py-1 text-xs text-gray-600 bg-white focus:outline-none focus:border-accent"
              >
                <option value="">全部维度</option>
                {筛选选项.维度.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              {筛选维度 && (
                <select
                  data-testid="board-filter-value"
                  value={筛选值}
                  onChange={(e) => set筛选值(e.target.value)}
                  className="border border-gray-200 rounded-md px-1.5 py-1 text-xs text-gray-600 bg-white focus:outline-none focus:border-accent"
                >
                  <option value="">全部取值</option>
                  {筛选选项.值.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              )}
              {(筛选维度 || 筛选值) && (
                <button
                  onClick={() => { set筛选维度(''); set筛选值(''); }}
                  className="p-1 rounded hover:bg-gray-100 text-gray-300 hover:text-gray-500"
                  title="清空筛选"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {/* 阶段 六十：网格 / 关系 视图切换 */}
            <div className="flex items-center rounded-lg border border-gray-200 overflow-hidden">
              <button
                title="网格视图"
                aria-pressed={视图 === 'grid'}
                onClick={() => set视图('grid')}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs transition-all ${视图 === 'grid' ? 'bg-accent text-white' : 'text-gray-500 hover:bg-gray-50'}`}
              >
                <LayoutGrid className="w-3 h-3" /> 网格
              </button>
              <button
                title="关系视图"
                aria-pressed={视图 === 'lineage'}
                onClick={() => set视图('lineage')}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs border-l border-gray-200 transition-all ${视图 === 'lineage' ? 'bg-accent text-white' : 'text-gray-500 hover:bg-gray-50'}`}
              >
                <Network className="w-3 h-3" /> 关系
              </button>
              <button
                title="自由画布（拖拽移动 / 右下角缩放）"
                aria-pressed={视图 === 'canvas'}
                onClick={() => set视图('canvas')}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs border-l border-gray-200 transition-all ${视图 === 'canvas' ? 'bg-accent text-white' : 'text-gray-500 hover:bg-gray-50'}`}
              >
                <Move className="w-3 h-3" /> 画布
              </button>
            </div>
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
              data-testid="board-export"
              disabled={导出中 || reports.length === 0}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={handleExportBoard}
            >
              <ImageOff className="w-3 h-3" /> {导出中 ? '导出中…' : '导出看板'}
            </button>
            <button
              data-testid="board-refresh"
              disabled={刷新中}
              title="重新拉取看板数据"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={handleRefresh}
            >
              <RefreshCw className={`w-3 h-3 ${刷新中 ? 'animate-spin' : ''}`} /> {刷新中 ? '刷新中…' : '刷新'}
            </button>
            <button
              data-testid="board-subscribe"
              aria-pressed={自动刷新}
              title={自动刷新 ? '已开启每 30 秒自动刷新，点击关闭' : '开启后每 30 秒自动刷新看板数据'}
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs transition-all ${
                自动刷新 ? 'border-accent bg-accent text-white' : 'border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
              onClick={() => set自动刷新(v => !v)}
            >
              <Bell className="w-3 h-3" /> {自动刷新 ? '订阅中' : '订阅'}
            </button>
            <button
              data-testid="board-export-image"
              disabled={reports.length === 0}
              title="把当前看板所有图表拼成一张图片"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={handleExportImage}
            >
              <ImageIcon className="w-3 h-3" /> 导出图片
            </button>
            <button
              data-testid="board-export-pdf"
              disabled={reports.length === 0}
              title="打开打印视图，可另存为 PDF"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={handleExportPdf}
            >
              <FileText className="w-3 h-3" /> 导出 PDF
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

      {/* 图表网格（智能排版 + 拖拽排序） */}
      {reports.length > 0 && 视图 === 'grid' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* 阶段八十五：全局筛选未命中 → 该卡片灰显（保留位置，便于对比；拖拽排序仅在无筛选时生效） */}
          {reports.map((item, i) => {
            const cfg = item.报表?.图表配置 || {};
            const chartTypeKey = cfg.类型 || 'bar';
            const conclusion = item.报表?.结论 || '';
            // 阶段八十九 · B6：下钻状态（每张图独立）；cfg使用 是「应用下钻后」的配置
            const 下钻条件 = 下钻集[item.报表ID] || [];
            const cfg使用 = 下钻条件.length ? 应用下钻(cfg, 下钻条件) : cfg;
            const colSpan = spanClassFor(chartTypeKey);
            const 命中 = 命中筛选(item);
            const 有筛选 = Boolean(筛选维度 && 筛选值);
            // 拖拽视觉反馈：被拖卡片半透明，目标卡片加边框
            const isDragging = dragIndex === i;
            const isOver = overIndex === i && dragIndex !== null && dragIndex !== i;
            return (
              <div
                key={item.报表ID}
                className={`${colSpan} bg-white rounded-2xl shadow-[var(--shadow-card)] overflow-hidden transition-all duration-150 select-none ${
                  isDragging ? 'opacity-40 scale-[0.98]' : ''
                } ${isOver ? 'ring-2 ring-accent/60 ring-offset-2' : ''} ${有筛选 && !命中 ? 'opacity-30 grayscale' : ''}`}
                draggable={!有筛选}
                onDragStart={(e) => handleDragStart(e, i)}
                onDragOver={(e) => handleDragOver(e, i)}
                onDrop={(e) => handleDrop(e, i)}
                onDragEnd={resetDrag}
              >
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
                  <EChartsChart ref={取图Ref(item.报表ID)} key={item.报表ID} chartType={chartTypeKey} chartConfig={cfg使用} height={280} on点选={(p) => handleChartClick(item, p)} />
                )}
                {下钻条件.length > 0 && (
                  <div className="px-4 pb-2 flex items-center gap-1 flex-wrap text-[11px]">
                    <span className="text-gray-400">下钻：</span>
                    {下钻条件.map((c) => (
                      <span key={c.维度} className="px-1.5 py-0.5 rounded bg-accent-soft text-accent">
                        {c.维度}={c.值}
                      </span>
                    ))}
                    <button
                      title="返回上一级"
                      className="ml-1 px-1.5 py-0.5 rounded border border-gray-200 text-gray-500 hover:border-accent hover:text-accent transition-colors"
                      onClick={() => handleDrillBack(item.报表ID)}
                    >
                      返回
                    </button>
                    <button
                      title="清空下钻"
                      className="px-1.5 py-0.5 rounded border border-gray-200 text-gray-500 hover:border-red-300 hover:text-red-500 transition-colors"
                      onClick={() => handleDrillClear(item.报表ID)}
                    >
                      清空
                    </button>
                  </div>
                )}
                {conclusion && (
                  <p className="px-4 pb-3.5 text-[11px] text-gray-500 leading-relaxed line-clamp-2">{conclusion}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 阶段 六十：关系视图——当前看板的 数据集 → 报表 → 复用字段 血缘图 */}
      {reports.length > 0 && 视图 === 'lineage' && (
        <div className="bg-white rounded-2xl shadow-[var(--shadow-card)] p-4">
          {血缘提示 && <p className="mb-2 text-xs text-amber-600">{血缘提示}</p>}
          <div className="flex items-center gap-2 flex-wrap mb-1 text-[11px] text-gray-400">
            <Network className="w-3.5 h-3.5 text-accent" />
            <span>当前看板：{detail?.名称}</span>
            <span>· {血缘.统计.数据集数} 个数据集 → {血缘.统计.报表数} 张报表 → {血缘.统计.高价值字段.length} 个复用字段</span>
            <span className="ml-auto">单击节点看详情 · 可拖拽 / 滚轮缩放</span>
          </div>
          {/* 阶段八十九：血缘图导出 PNG —— 把当前关系图存成图片，可贴进文档/汇报 */}
          <div className="flex justify-end mb-1">
            <button
              onClick={() => {
                const url = 血缘图Ref.current?.导出PNG?.();
                if (!url) { setError('血缘图尚未渲染完成，请稍后再试'); return; }
                set导出血缘中(true);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${detail?.名称 || '看板'}-血缘关系图.png`;
                a.click();
                set导出血缘中(false);
              }}
              disabled={导出血缘中}
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-gray-200 text-gray-500 hover:text-accent hover:border-accent/40 transition-colors disabled:opacity-50"
              title="把血缘关系图导出为 PNG 图片"
            >
              <Download className="w-3 h-3" /> {导出血缘中 ? '导出中…' : '导出 PNG'}
            </button>
          </div>
          {/* 父容器必须给确定高度：h-auto 会让 echarts 拿到 0 高度画不出东西 */}
          <LineageGraph
            ref={血缘图Ref}
            图数据={血缘}
            高亮节点ID={选中节点ID}
            onSelectNode={set选中节点ID}
            height={520}
          />

          {血缘.统计.高价值字段.length > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-100">
              <p className="text-xs font-medium text-gray-700 mb-2">字段复用榜（被 ≥2 张报表引用 = 值得治理的核心字段）</p>
              <div className="flex flex-wrap gap-1.5">
                {血缘.统计.高价值字段.map((f) => (
                  <button
                    key={f.节点ID}
                    onClick={() => set选中节点ID(f.节点ID)}
                    className="text-[11px] px-2 py-1 rounded-md bg-amber-50 text-amber-700 border border-amber-100 hover:bg-amber-100 transition-colors"
                  >
                    {f.字段名} <span className="text-amber-500">×{f.报表数}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 阶段八十四：自由画布视图——绝对定位 + 拖拽移动 + 右下角缩放，松手落库 */}
      {reports.length > 0 && 视图 === 'canvas' && (
        <div
          data-testid="canvas-view"
          className="relative bg-white rounded-2xl shadow-[var(--shadow-card)] p-4 overflow-hidden"
          style={{ minHeight: 520 }}
        >
          <div className="flex items-center gap-2 mb-3 text-[11px] text-gray-400">
            <Move className="w-3.5 h-3.5 text-accent" />
            <span>自由画布：拖拽卡片移动 · 右下角手柄缩放 · 布局自动保存</span>
            <span className="ml-auto">未布局的卡片按顺序自动排布</span>
          </div>
          <div className="relative" style={{ minHeight: 440 }}>
            {reports.map((item) => {
              const pos = 卡片位置(item);
              const cfg = item.报表?.图表配置 || {};
              const chartTypeKey = cfg.类型 || 'bar';
              const isDraggingCard = 画布拖拽?.id === item.报表ID;
              return (
                <div
                  key={item.报表ID}
                  data-report-id={item.报表ID}
                  className={`absolute bg-white rounded-xl border border-gray-200 shadow-[var(--shadow-card)] overflow-hidden transition-shadow ${isDraggingCard ? 'z-20 ring-2 ring-accent/50 shadow-lg' : 'hover:shadow-[var(--shadow-card-lg)]'}`}
                  style={{ left: pos.x, top: pos.y, width: pos.w, height: pos.h, cursor: 'grab' }}
                >
                  <div
                    className="flex items-center gap-2 px-3 pt-2 select-none cursor-grab active:cursor-grabbing"
                    onMouseDown={(e) => handleCardMouseDown(e, item)}
                  >
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-soft text-accent font-medium shrink-0">{item.图表类型 || '图表'}</span>
                    <p className="text-[11px] font-medium text-gray-700 truncate flex-1">{item.标题}</p>
                    <button
                      title="查看完整报表"
                      className="p-1 rounded hover:bg-gray-100 text-gray-300 hover:text-accent transition-colors shrink-0"
                      onClick={(e) => { e.stopPropagation(); navigate(`/report/${item.报表ID}`); }}
                    >
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  </div>
                  <div data-card-body className="absolute inset-x-2 bottom-6 top-8">
                    {chartTypeKey === 'table' ? (
                      <p className="text-xs text-gray-400 text-center py-8">表格类报表请到详情页查看</p>
                    ) : (
                      <EChartsChart key={item.报表ID} chartType={chartTypeKey} chartConfig={cfg} height={Math.max(140, pos.h - 56)} />
                    )}
                  </div>
                  <div
                    title="拖拽右下角缩放"
                    className="absolute bottom-1 right-1 w-4 h-4 cursor-nwse-resize text-gray-300 hover:text-accent"
                    onMouseDown={(e) => handleResizeMouseDown(e, item)}
                  >
                    <svg viewBox="0 0 16 16" className="w-full h-full" fill="currentColor"><path d="M12 4v5.5L7.5 5H13V4z" transform="rotate(45 9 8)" /><path d="M14 10h-1v2h-2v1h3v-3z" /></svg>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 阶段 六十：节点详情抽屉（常驻挂载，节点为空时自身不渲染） */}
      {视图 === 'lineage' && 选中节点 && (
        <LineageDrawer
          节点={选中节点}
          onClose={() => set选中节点ID('')}
          onSelectNode={set选中节点ID}
          onOpenReport={(id) => navigate(`/report/${id}`)}
        />
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