// 对比分析页（面试讲解）
//
// 做了什么：把"多份同结构数据横向比"做成三步向导——
//   ① 勾选 2~10 个数据集 → ② 确认来源标签 / 来源轴 → ③ 选主体轴+指标+口径后生成对比报表。
// 为什么这样设计：
//   - 对比的难点不在画图，而在"对齐口径"：哪一列是主体（地区）、哪个维度是来源
//     （1月/2月/10月）、指标怎么聚合。所以先调只读预检 /reports/compare/preview
//     拿候选与推荐口径，让"默认值就能直接生成"，用户只在推荐不对时才动手；
//   - 来源标签默认取文件名去扩展名（销售1月.csv → 销售1月）；只要用户改过任意一个，
//     就整组按"手动标签"下发（后端优先级：手动标签 > 指定列 > 自动恒定列 > 文件名）；
//     全都没改 → 传空数组交给后端推导，此时"来源轴"下拉才生效；
//   - 预检只是辅助，失败不阻塞生成（页面提示 + 用户仍可手填后生成）。
// 删除它会怎样：用户只能一次分析一份数据，跨月/跨区的同比环比得手工拼 Excel。
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GitCompare, Layers, Sparkles, Loader2, AlertTriangle, Check } from 'lucide-react';
import { listDatasets, previewCompare, compareReport } from '../api';

const 最少数据集 = 2;
const 最多数据集 = 10;
const 聚合选项 = ['求和', '平均值', '最大值', '最小值', '计数'];
const 图表选项 = ['自动推荐', '堆积柱状图', '柱状图', '表格'];
// 预检防抖：连续勾选时只发最后一次请求（300ms 足够覆盖连续点击）
const 预检防抖毫秒 = 300;

// 文件名去扩展名 → 默认来源标签（"销售1月.csv" → "销售1月"）
function 去扩展名(文件名) {
  return String(文件名 || '').replace(/\.[^.]+$/, '');
}

export default function Compare() {
  const navigate = useNavigate();

  // ---- 第一步：数据集多选 ----
  const [dsList, setDsList] = useState([]);        // [{数据集ID, 文件名, 行数, 列数}]
  const [dsLoading, setDsLoading] = useState(true);
  const [dsError, setDsError] = useState('');      // 列表加载失败（红色提示）
  const [selected, setSelected] = useState([]);    // 勾选顺序 = 对比顺序（数组而非 Set）
  const [selNotice, setSelNotice] = useState('');  // 超过 10 个时的黄色提示

  // ---- 第二步：来源标签 / 来源轴 ----
  const [labels, setLabels] = useState({});        // {数据集ID: 手写标签}，空串=未改
  const [来源轴, set来源轴] = useState('');        // '' = 自动推导

  // ---- 第三步：对比口径 ----
  const [维度, set维度] = useState('');
  const [指标, set指标] = useState('');
  const [聚合方式, set聚合方式] = useState('求和');
  const [图表类型, set图表类型] = useState('自动推荐');
  const [分析需求, set分析需求] = useState('');

  // ---- 预检 / 生成状态 ----
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewErr, setPreviewErr] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genErr, setGenErr] = useState('');

  // 挂载：拉数据集列表（与数据管理页同一个 200 条上限）
  useEffect(() => {
    let cancelled = false;
    setDsLoading(true);
    listDatasets(200, '', 'created_at_desc')
      .then((res) => {
        if (cancelled) return;
        setDsList(res?.数据集列表 || []);
        setDsError('');
      })
      .catch((e) => {
        if (cancelled) return;
        setDsList([]);
        setDsError('数据集列表加载失败：' + (e.message || e));
      })
      .finally(() => { if (!cancelled) setDsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // 数据集表：按 ID 反查文件名/行数（勾选顺序与列表顺序无关）
  const 数据集表 = useMemo(() => {
    const m = new Map();
    dsList.forEach((d) => m.set(d.数据集ID, d));
    return m;
  }, [dsList]);

  // 阶段七十四 · B：从数据管理页带 ?datasets=ID,ID 过来时按顺序预选。
  // 刻意等列表加载完（依赖 dsList）再解析：列表为空时解析会静默失败，
  // 用户看到的是"没选上"，比报错更难排查。未匹配到的 ID 直接忽略，
  // 已被删除的数据集不该让整个页面报错。
  const 预选签名 = useMemo(() => new URLSearchParams(window.location.search).get('datasets') || '', []);
  useEffect(() => {
    if (!预选签名 || dsList.length === 0) return;
    const 要选 = 预选签名.split(',').filter((id) => 数据集表.has(id));
    if (要选.length) setSelected(要选);
  }, [预选签名, dsList, 数据集表]);

  const 勾选数据集 = (id) => {
    setSelNotice('');
    if (selected.includes(id)) {
      setSelected(selected.filter((x) => x !== id));
      return;
    }
    if (selected.length >= 最多数据集) {
      setSelNotice(`最多同时对比 ${最多数据集} 个数据集，请先取消一个再选`);
      return;
    }
    setSelected([...selected, id]);
  };

  // 构造"对比标签"：全都没手改 → 空数组（交给后端按恒定列/文件名推导）；
  // 只要有一个改过 → 整组下发，没改的用文件名兜底（保证个数与勾选数一致且非空）。
  const 构造对比标签 = () => {
    const 有人手改 = selected.some((id) => (labels[id] || '').trim());
    if (!有人手改) return [];
    return selected.map((id) => (labels[id] || '').trim() || 去扩展名(数据集表.get(id)?.文件名));
  };

  // 预检：勾选变化 / 来源轴变化后防抖调用；序号守卫丢弃过期响应（快速勾选时旧结果不覆盖）
  const previewSeqRef = useRef(0);
  const 选择签名 = selected.join('|');
  useEffect(() => {
    if (selected.length < 最少数据集) {
      setPreview(null);
      setPreviewErr('');
      setPreviewing(false);
      return undefined;
    }
    const seq = ++previewSeqRef.current;
    setPreviewing(true);
    const timer = setTimeout(async () => {
      try {
        const res = await previewCompare({
          数据集ID列表: selected,
          对比标签: 构造对比标签(),
          来源轴: 来源轴 || null,
        });
        if (previewSeqRef.current !== seq) return; // 已有更新的预检，丢弃本次
        setPreview(res || null);
        setPreviewErr('');
        // 推荐值作为默认选中：每次预检都重置口径，避免上一次选择在新数据组合下失效
        const 推荐 = res?.推荐 || {};
        if (推荐.主体轴) set维度(推荐.主体轴);
        if (推荐.指标) set指标(推荐.指标);
        if (推荐.聚合方式) set聚合方式(推荐.聚合方式);
      } catch (e) {
        if (previewSeqRef.current !== seq) return;
        setPreview(null);
        setPreviewErr('预检没成功（不影响生成报表）：' + (e.message || e));
      } finally {
        if (previewSeqRef.current === seq) setPreviewing(false);
      }
    }, 预检防抖毫秒);
    return () => clearTimeout(timer);
    // 只在"勾了哪些数据集 / 来源轴"变化时预检；标签是本地手写值，边打字边预检没有意义
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [选择签名, 来源轴]);

  const 可生成 = selected.length >= 最少数据集 && !generating;

  const handleGenerate = async () => {
    if (!可生成) return;
    setGenerating(true);
    setGenErr('');
    try {
      const res = await compareReport({
        数据集ID列表: selected,
        对比标签: 构造对比标签(),
        分析需求: 分析需求.trim(),
        维度: 维度 || null,
        指标: 指标 || null,
        聚合方式,
        图表类型,
        来源轴: 来源轴 || null,
        筛选条件: [],
      });
      const 报表ID = res?.报表ID;
      if (!报表ID) {
        setGenErr('生成成功但返回里没有报表ID，请到「报表历史」查看');
        return;
      }
      navigate('/report/' + 报表ID);
    } catch (e) {
      setGenErr('生成失败：' + (e.message || e));
    } finally {
      setGenerating(false);
    }
  };

  const 主体轴候选 = preview?.主体轴候选 || [];
  const 指标候选 = preview?.指标候选 || [];
  const 来源轴候选 = (preview?.来源轴候选 || []).filter((c) => c?.列);
  const 警告 = preview?.警告 || [];

  const inputCls = 'border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:border-accent';

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center gap-2">
        <GitCompare className="w-5 h-5 text-accent" />
        <h1 className="text-lg font-semibold text-gray-900">对比分析</h1>
      </div>
      <p className="text-xs text-gray-400 mt-1 mb-5">
        勾选多份同结构数据（如 1月 / 2月 / 10月销售），一次看清同一批地区、同一批产品的变化。
      </p>

      {dsError && (
        <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-xs text-red-600">{dsError}</div>
      )}

      {/* ---- 第一步：选数据集 ---- */}
      <section className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
            <Layers className="w-3.5 h-3.5 text-accent" /> 第一步 · 选择数据集
          </div>
          <span className="text-[11px] text-gray-400">已选 {selected.length}/{最多数据集}（至少 {最少数据集} 个）</span>
        </div>

        {dsLoading ? (
          <p className="text-xs text-gray-400">数据集加载中…</p>
        ) : dsList.length === 0 ? (
          <p className="text-xs text-gray-400">还没有数据集——先去「数据管理」上传文件或加载示例数据。</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-72 overflow-y-auto">
            {dsList.map((d) => {
              const 选中 = selected.includes(d.数据集ID);
              return (
                <label
                  key={d.数据集ID}
                  className={`flex items-start gap-2 rounded-xl border p-3 cursor-pointer transition-all ${选中 ? 'border-accent bg-accent-soft/60' : 'border-gray-200 hover:bg-gray-50/60'}`}
                >
                  <input
                    type="checkbox"
                    className="accent-accent mt-0.5 shrink-0"
                    aria-label={d.文件名}
                    checked={选中}
                    onChange={() => 勾选数据集(d.数据集ID)}
                  />
                  <div className="min-w-0 flex-1">
                    <p className={`text-xs truncate ${选中 ? 'text-accent-deep font-medium' : 'text-gray-700'}`} title={d.文件名}>
                      {d.文件名}
                    </p>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      {d.行数 ?? '—'} 行 · {d.列数 ?? '—'} 列
                    </p>
                  </div>
                  {选中 && <Check className="w-3.5 h-3.5 text-accent shrink-0 mt-0.5" />}
                </label>
              );
            })}
          </div>
        )}

        {selNotice && (
          <p className="text-[11px] text-amber-600 mt-2 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />{selNotice}
          </p>
        )}
      </section>

      {/* ---- 第二步：来源标签 + 来源轴 ---- */}
      {selected.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-5 mt-3">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
              <GitCompare className="w-3.5 h-3.5 text-accent" /> 第二步 · 来源标签
            </div>
            <span className="text-[11px] text-gray-400">默认取文件名，可改成「1月 / 2月 / 10月」这类更好读的名字</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {selected.map((id, i) => (
              <div key={id} className="flex items-center gap-2">
                <span className="w-4 shrink-0 text-[11px] text-gray-400">{i + 1}</span>
                <input
                  className={`flex-1 min-w-0 ${inputCls}`}
                  aria-label={`来源标签 ${i + 1}`}
                  placeholder={去扩展名(数据集表.get(id)?.文件名) || `数据集 ${i + 1}`}
                  value={labels[id] ?? ''}
                  onChange={(e) => setLabels((prev) => ({ ...prev, [id]: e.target.value }))}
                  maxLength={30}
                />
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <span className="text-xs text-gray-500 shrink-0">来源轴</span>
            <select
              className={inputCls}
              aria-label="来源轴"
              value={来源轴}
              onChange={(e) => set来源轴(e.target.value)}
            >
              <option value="">自动（按文件名 / 恒定列推导）</option>
              {来源轴候选.map((c) => (
                <option key={c.列} value={c.列}>{c.列}（{c.类型}）</option>
              ))}
            </select>
            {preview?.推荐?.推导方式 && (
              <span className="text-[11px] text-gray-400">
                当前推导：{preview.推荐.推导方式}
                {preview.推荐.来源轴 ? ` · ${preview.推荐.来源轴}` : ''}
                {预览标签摘要(preview)}
              </span>
            )}
          </div>
        </section>
      )}

      {/* ---- 第三步：对比口径 ---- */}
      <section className="bg-white rounded-xl border border-gray-200 p-5 mt-3">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
            <Sparkles className="w-3.5 h-3.5 text-accent" /> 第三步 · 对比口径
          </div>
          {previewing && (
            <span className="flex items-center gap-1 text-[11px] text-gray-400">
              <Loader2 className="w-3 h-3 animate-spin" /> 正在预检…
            </span>
          )}
        </div>

        {previewErr && <p className="text-[11px] text-amber-600 mb-2">{previewErr}</p>}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] text-gray-500 mb-1" htmlFor="cmp-dim">主体轴（按哪一列对比）</label>
            <select id="cmp-dim" aria-label="主体轴" className={`w-full ${inputCls}`} value={维度} onChange={(e) => set维度(e.target.value)}>
              <option value="">自动选择主体轴</option>
              {主体轴候选.map((c) => (
                <option key={c.列} value={c.列}>{c.列}（{c.基数} 个取值）</option>
              ))}
              {/* 推荐值不在候选里时仍保留当前选择，避免"选中项消失" */}
              {维度 && !主体轴候选.some((c) => c.列 === 维度) && <option value={维度}>{维度}</option>}
            </select>
          </div>

          <div>
            <label className="block text-[11px] text-gray-500 mb-1" htmlFor="cmp-metric">指标</label>
            <select id="cmp-metric" aria-label="指标" className={`w-full ${inputCls}`} value={指标} onChange={(e) => set指标(e.target.value)}>
              <option value="">自动选择指标</option>
              {指标候选.map((m) => <option key={m} value={m}>{m}</option>)}
              {指标 && !指标候选.includes(指标) && <option value={指标}>{指标}</option>}
            </select>
          </div>

          <div>
            <label className="block text-[11px] text-gray-500 mb-1" htmlFor="cmp-agg">聚合方式</label>
            <select id="cmp-agg" aria-label="聚合方式" className={`w-full ${inputCls}`} value={聚合方式} onChange={(e) => set聚合方式(e.target.value)}>
              {聚合选项.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-[11px] text-gray-500 mb-1" htmlFor="cmp-chart">图表类型</label>
            <select id="cmp-chart" aria-label="图表类型" className={`w-full ${inputCls}`} value={图表类型} onChange={(e) => set图表类型(e.target.value)}>
              {图表选项.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>

        <div className="mt-3">
          <label className="block text-[11px] text-gray-500 mb-1" htmlFor="cmp-need">分析需求（选填）</label>
          <textarea
            id="cmp-need"
            aria-label="分析需求"
            className={`w-full ${inputCls} min-h-[64px]`}
            placeholder="想重点看什么？例如：哪个地区 10 月跌得最厉害、哪几个地区连续两个月下滑"
            value={分析需求}
            onChange={(e) => set分析需求(e.target.value)}
            maxLength={200}
          />
        </div>

        {警告.length > 0 && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 space-y-0.5">
            {警告.map((w, i) => (
              <p key={i} className="text-[11px] text-amber-700 flex items-start gap-1">
                <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />{w}
              </p>
            ))}
          </div>
        )}

        <div className="flex items-center gap-3 mt-4 flex-wrap">
          <button
            onClick={handleGenerate}
            disabled={!可生成}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitCompare className="w-3.5 h-3.5" />}
            {generating ? '生成中…' : '生成对比报表'}
          </button>
          <span className="text-[11px] text-gray-400">
            {selected.length < 最少数据集
              ? `至少选择 ${最少数据集} 个数据集才能对比（已选 ${selected.length} 个）`
              : `将对比 ${selected.length} 份数据${preview?.行数 ? ` · 合计 ${preview.行数} 行` : ''}`}
          </span>
        </div>

        {genErr && (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{genErr}</div>
        )}
      </section>
    </div>
  );
}

// 预检推荐里带了整份来源标签（1月/2月/10月），这里只按来源轴是否正确展示一小段摘要
function 预览标签摘要(preview) {
  const 标签 = preview?.推荐?.来源标签 || [];
  if (!标签.length) return '';
  return ` · ${标签.slice(0, 6).join(' / ')}${标签.length > 6 ? ' …' : ''}`;
}
