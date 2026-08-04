import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, Sparkles, BarChart3, LineChart, PieChart, ScatterChart, Table, Layers, Loader2, Cpu, GitBranch, X, Brain, Wrench, Eye, AlertTriangle } from 'lucide-react';
import LLMConfig from '../components/LLMConfig';
import { generateReportStream } from '../api';
import { useApp } from '../AppContext';

const chartMap = {
  auto: '自动推荐', bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图',
  heatmap: '热力图', table: '表格', stacked: '堆积柱状图',
  histogram: '直方图', area: '面积图', radar: '雷达图', wordcloud: '词云图',
  funnel: '漏斗图', sankey: '桑基图', boxplot: '箱线图', donut: '环形图',
  waterfall: '瀑布图', sunburst: '旭日图', candlestick: 'K线图',
};

const chartTypes = [
  { id: 'auto', icon: Sparkles, label: '智能推荐' },
  { id: 'bar', icon: BarChart3, label: '柱状图' },
  { id: 'line', icon: LineChart, label: '折线图' },
  { id: 'pie', icon: PieChart, label: '饼图' },
  { id: 'donut', icon: PieChart, label: '环形图' },
  { id: 'scatter', icon: ScatterChart, label: '散点图' },
  { id: 'histogram', icon: BarChart3, label: '直方图' },
  { id: 'boxplot', icon: BarChart3, label: '箱线图' },
  { id: 'area', icon: LineChart, label: '面积图' },
  { id: 'radar', icon: Layers, label: '雷达图' },
  { id: 'heatmap', icon: Layers, label: '热力图' },
  { id: 'funnel', icon: Layers, label: '漏斗图' },
  { id: 'waterfall', icon: BarChart3, label: '瀑布图' },
  { id: 'sankey', icon: GitBranch, label: '桑基图' },
  { id: 'sunburst', icon: Layers, label: '旭日图' },
  { id: 'candlestick', icon: LineChart, label: 'K线图' },
  { id: 'wordcloud', icon: Layers, label: '词云图' },
  { id: 'table', icon: Table, label: '表格' },
  { id: 'stacked', icon: Layers, label: '堆积图' },
];

const templates = [
  { label: '占比分布', icon: PieChart, text: '按【地区】统计【销售额】占比' },
  { label: '趋势变化', icon: LineChart, text: '按【月份】统计【销售额】趋势变化' },
  { label: '分组对比', icon: BarChart3, text: '按【地区】分组对比【销售额】平均值' },
  { label: '交叉分析', icon: GitBranch, text: '按【地区】和【岗位类型】做【销售额】交叉分析' },
];

const models = [
  { id: '', label: '系统默认' },
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { id: 'gpt-4o', label: 'GPT-4o' },
  { id: 'deepseek-chat', label: 'DeepSeek Chat' },
];

export default function Analysis() {
  const navigate = useNavigate();
  const { dataset } = useApp();
  const [nlInput, setNlInput] = useState('');
  const [chartType, setChartType] = useState('bar');
  const [generating, setGenerating] = useState(false);
  const [xAxis, setXAxis] = useState('');
  const [yAxis, setYAxis] = useState('');
  const [groupField, setGroupField] = useState('');
  const [aggMethod, setAggMethod] = useState('求和');
  const [agentMode, setAgentMode] = useState('single');
  const [selectedModel, setSelectedModel] = useState('');
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  // 分析直播状态（SSE 实时决策流）
  const [liveSteps, setLiveSteps] = useState([]);      // [{ record, status: 'done'|'active' }]
  const [liveError, setLiveError] = useState('');
  const [liveDone, setLiveDone] = useState(null);       // { 报表ID, 标题 }
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);

  const profile = dataset?.数据画像;
  const fields = profile?.字段列表 || [];
  const numFields = profile?.数值字段 || [];
  const catFields = profile?.分类字段 || [];
  const dateFields = profile?.日期字段 || [];
  const textFields = profile?.文本字段 || [];

  // 选中图表类型时按语义自动重选字段（自然语言/点击图表都不用手动选字段）
  const handleChartSelect = (id) => {
    setChartType(id);
    const set = (x, y, g) => { setXAxis(x || ''); setYAxis(y || ''); setGroupField(g || '无'); };
    switch (id) {
      case 'wordcloud':
        set(textFields[0] || catFields[0] || '', '', '无'); break;
      case 'scatter':
        set(numFields[0] || '', numFields[1] || numFields[0] || '', '无'); break;
      case 'boxplot':
      case 'candlestick': {
        let x = (id === 'candlestick' ? dateFields[0] : catFields[0]) || catFields[0] || dateFields[0] || '';
        const y = numFields[0] || '';
        if (x === y) x = dateFields[0] || catFields[1] || '';
        set(x, y, '无'); break;
      }
      case 'heatmap':
      case 'stacked':
      case 'sankey':
      case 'sunburst':
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', catFields[1] || '无'); break;
      case 'radar':
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', '无'); break;
      case 'histogram':
        set(numFields[0] || '', numFields[0] || '', '无'); break;
      case 'line':
      case 'area':
        set(dateFields[0] || catFields[0] || '', numFields[0] || '', '无'); break;
      default:
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', '无');
    }
  };

  // Auto-fill based on profile（useEffect 中执行，避免 render 阶段 setState）
  useEffect(() => {
    if (profile && !xAxis) {
      setXAxis((profile.分类字段?.[0] || profile.日期字段?.[0] || fields[0] || ''));
      setYAxis(numFields[0] || '');
      setGroupField('无');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  // 生成期间计时 + 决策流自动滚动到底部
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [generating]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveSteps.length]);

  // 收到 done 事件后稍作停留，跳转报表详情
  useEffect(() => {
    if (!liveDone) return;
    const t = setTimeout(() => { window.location.href = '/report/' + liveDone.报表ID; }, 1000);
    return () => clearTimeout(t);
  }, [liveDone]);

  const handleCancel = () => {
    abortRef.current?.abort();
    setGenerating(false);
    setLiveSteps([]);
    setLiveError('');
    setLiveDone(null);
  };

  async function handleGenerate() {
    if (!dataset) {
      setError('请先在数据管理页面上传数据');
      navigate('/data');
      return;
    }
    // 字段前置校验
    const validationError = validateChartFields(chartType, xAxis, yAxis, groupField, profile);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');
    setLiveError('');
    setLiveDone(null);
    setLiveSteps([]);
    setElapsed(0);
    setGenerating(true);

    const payload = {
      数据集ID: dataset.数据集ID,
      分析需求: nlInput,
      图表类型: chartMap[chartType] || '自动推荐',
      x轴: xAxis === '无' ? null : xAxis,
      y轴: yAxis ? [yAxis] : [],
      分组字段: groupField === '无' ? null : groupField,
      聚合方式: aggMethod,
      agent_mode: agentMode,
      model: selectedModel || undefined,
    };
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await generateReportStream(payload, {
        signal: controller.signal,
        onEvent: (ev) => {
          if (ev.type === 'step') {
            // 上一步置为完成，新一步置为进行中
            setLiveSteps(prev => [
              ...prev.map(s => ({ ...s, status: 'done' })),
              { record: ev.data, status: 'active' },
            ]);
          } else if (ev.type === 'done') {
            setLiveSteps(prev => prev.map(s => ({ ...s, status: 'done' })));
            setLiveDone({ 报表ID: ev.报表ID, 标题: ev.标题 });
            return 'stop';
          } else if (ev.type === 'error') {
            setLiveError(ev.message || '分析失败，请重试');
            return 'stop';
          }
          return undefined;
        },
      });
    } catch (e) {
      // 请求层错误：HTTP 状态 / 网络 / 用户取消
      if (e.name === 'AbortError') return; // 取消不报错
      if (e.status === 401) {
        setError('认证已过期或无效，请重新登录');
      } else if (e.status === 413) {
        setError('文件超过大小限制（最大 50MB）');
      } else if (e.status === 400) {
        setError(e.message || '分析失败：参数或字段不满足要求');
      } else if (e.message?.includes('Failed to fetch') || e.name === 'TypeError') {
        setError('后端服务不可用或请求中断，请检查后端是否启动');
      } else {
        setError('分析失败：' + e.message);
      }
    } finally {
      setGenerating(false);
    }
  }

  // 图表类型字段适配校验
  function validateChartFields(type, x, y, group, profile) {
    if (!profile) return null;
    const nf = new Set(profile.数值字段 || []);
    const cf = new Set(profile.分类字段 || []);
    const df = new Set(profile.日期字段 || []);
    const xIsNum = nf.has(x);
    const yIsNum = nf.has(y);
    const xIsCat = cf.has(x) || df.has(x);
    const hasGroup = group && group !== '无';

    switch (type) {
      case 'scatter':
        if (!xIsNum) return '散点图的 X 轴需要选择数值字段';
        if (!yIsNum) return '散点图的 Y 轴需要选择数值字段';
        break;
      case 'histogram':
        if (!xIsNum) return '直方图的 X 轴需要选择数值字段';
        break;
      case 'pie':
        if (!xIsCat && x) return '饼图的 X 轴建议选择分类字段，当前选择可能不适用';
        break;
      case 'heatmap':
        if (!hasGroup) return '热力图需要设置分组字段';
        break;
      case 'sankey':
        if (!hasGroup) return '桑基图需要设置分组字段（作为流向的源）';
        break;
      case 'boxplot':
        if (!yIsNum) return '箱线图的 Y 轴需要选择数值字段';
        break;
      case 'candlestick':
        if (!yIsNum) return 'K线图的 Y 轴需要选择数值字段';
        break;
      case 'waterfall':
        if (!yIsNum) return '瀑布图的 Y 轴需要选择数值字段';
        break;
      case 'funnel':
        if (!xIsCat && x) return '漏斗图的 X 轴建议选择分类字段';
        break;
      case 'donut':
        if (!xIsCat && x) return '环形图的 X 轴建议选择分类字段';
        break;
      case 'wordcloud':
        if (x && !(profile.文本字段 || []).includes(x) && xIsCat) return '词云图的 X 轴建议选择文本字段（长文本，如评论/备注）';
        break;
      case 'stacked':
      case 'stacked_bar':
        if (!hasGroup) return '堆积柱状图需要设置分组字段';
        break;
    }
    return null;
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-7">
        <h1 className="text-lg font-semibold text-gray-900">智能分析</h1>
        <p className="text-xs text-gray-400 mt-1">用自然语言描述分析需求，AI 自动生成报表</p>
        {dataset && <p className="text-xs text-accent mt-1">当前数据集：{dataset.文件名}</p>}
        {error && (
          <div className="mt-3 px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
            <span>⚠</span>
            <span>{error}</span>
            <button className="ml-auto text-red-400 hover:text-red-600 text-xs" onClick={() => setError('')}>✕</button>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 rounded-t-xl">
          <textarea
            rows={3}
            className="w-full bg-transparent border-0 text-sm text-gray-700 resize-none focus:outline-none placeholder:text-gray-400 leading-relaxed"
            placeholder="输入分析需求，例如：按【地区】统计【销售额】占比…"
            value={nlInput}
            onChange={(e) => setNlInput(e.target.value)}
          />
        </div>
        <div className="flex items-center justify-between px-5 py-3 bg-gray-50/80 border-t border-gray-100 rounded-b-xl">
          <div className="flex items-center gap-3 flex-wrap">
            <LLMConfig />
            <div className="hidden sm:flex gap-1.5 flex-wrap">
              {templates.map((t) => (
                <span
                  key={t.label}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-xs text-gray-500 cursor-pointer hover:bg-gray-100 hover:text-gray-700 transition-all border border-gray-200"
                  onClick={() => setNlInput(t.text)}
                >
                  <t.icon className="w-3.5 h-3.5 text-accent" />
                  {t.label}
                </span>
              ))}
            </div>
          </div>
          <button
            disabled={generating}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all active:scale-[.98] disabled:opacity-50"
            onClick={handleGenerate}
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            {generating ? '分析中…' : '开始分析'}
          </button>
        </div>
      </div>

      {/* 意图预览条：输入自然语言后展示系统自动选择的图表/字段，确认后再生成 */}
      {nlInput.trim().length > 0 && !generating && (
        <div className="flex items-center gap-2 flex-wrap mt-3 px-4 py-2.5 rounded-xl bg-accent-soft text-xs text-accent">
          <b className="font-semibold">已自动选择</b>
          <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium">
            {nlInput.trim() ? '图表：自动' : (chartMap[chartType] || '自动推荐')}
          </span>
          {xAxis && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium">X {xAxis}</span>}
          {yAxis && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium">Y {yAxis}</span>}
          {groupField && groupField !== '无' && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium">分组 {groupField}</span>}
          <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium">{aggMethod}</span>
          <span className="ml-auto opacity-70">确认无误再生成</span>
        </div>
      )}

      {/* 分析直播：Agent 实时决策流 + 图表生长舞台 */}
      {generating && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* 左：决策流 */}
          <div className="lg:col-span-3 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
              <span
                className="w-2 h-2 rounded-full bg-emerald-500 shrink-0"
                style={{ animation: 'live-pulse 1.6s infinite' }}
              />
              <span className="text-xs font-semibold text-gray-700">Agent 决策流</span>
              <span className="ml-auto text-[10px] px-2 py-0.5 rounded-md bg-accent-soft text-accent font-medium whitespace-nowrap">
                AI 生成 · {agentMode === 'multi' ? '多智能体' : '单 Agent'}
              </span>
              <button
                onClick={handleCancel}
                className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all"
              >
                <X className="w-3 h-3" /> 取消
              </button>
            </div>

            <div ref={scrollRef} className="px-2 py-2 space-y-0.5 max-h-[340px] overflow-y-auto">
              {liveSteps.map((s, i) => <TraceRow key={i} step={s} />)}
              {liveSteps.length === 0 && (
                <div className="flex items-center gap-3 px-3 py-4 text-xs text-gray-400">
                  <Loader2 className="w-4 h-4 animate-spin" /> 正在唤醒 Agent…
                </div>
              )}
            </div>

            {/* 底部状态条 */}
            <div className="flex items-center gap-2.5 px-4 py-2.5 bg-gray-50/80 border-t border-gray-100 text-[11px] text-gray-500">
              {liveError ? (
                <span className="text-red-600 font-medium">✕ {liveError}</span>
              ) : liveDone ? (
                <span className="text-ok font-medium">✓ 分析完成，正在打开报表…</span>
              ) : (
                <>
                  <span className="flex items-end gap-[3px] h-3.5" aria-hidden>
                    {[5, 10, 7, 12, 8].map((h, i) => (
                      <span
                        key={i}
                        className="w-[3px] rounded-[1px] bg-accent opacity-70"
                        style={{ height: h, animation: `live-eq 0.9s ease-in-out ${i * 0.15}s infinite` }}
                      />
                    ))}
                  </span>
                  <span>Agent 正在工作 · 已用 {elapsed}s</span>
                </>
              )}
              <span className="ml-auto font-variant-numeric">
                步骤 {liveSteps.length}
                {!liveDone && !liveError && ' · 实时更新'}
              </span>
            </div>
          </div>

          {/* 右：图表生长舞台 */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-col">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-semibold tracking-wide text-gray-400">生成中的报表</p>
              {liveDone && <span className="text-[10px] px-2 py-0.5 rounded-md bg-ok-soft text-ok font-medium">已完成</span>}
            </div>
            <div
              className="flex-1 min-h-[190px] mt-3 rounded-lg px-7 pb-7 flex items-end gap-4 relative overflow-hidden"
              style={{ background: 'radial-gradient(120% 100% at 50% 0%, #eef3f9 0%, #f8fafc 55%, #f1f5f9 100%)' }}
            >
              {/* 参考网格线 */}
              <div className="absolute left-7 right-7 top-5 bottom-7 flex flex-col justify-between pointer-events-none">
                {[0, 1, 2, 3].map(i => (
                  <span key={i} className="border-t border-dashed border-accent/10" />
                ))}
              </div>
              <span className="absolute left-1/2 -translate-x-1/2 top-3 text-[10px] tracking-widest text-gray-400">
                图表生成中
              </span>
              {[56, 72, 44, 32, 48].map((h, i) => (
                <span
                  key={i}
                  className="relative flex-1 rounded-t-md"
                  style={{
                    height: `${h}%`,
                    background: 'linear-gradient(180deg, #4a8ac2, #0f4c81)',
                    boxShadow: '0 6px 14px -6px rgba(15,76,129,.35)',
                    animation: `live-grow 0.9s cubic-bezier(.22,1,.36,1) ${0.12 * i + 0.1}s both`,
                  }}
                />
              ))}
            </div>
            <p className="text-[11px] text-gray-400 mt-3">
              {liveError
                ? '生成失败，请检查参数后重试'
                : liveDone
                  ? '决策完成，报表即将打开'
                  : 'AI 正在根据决策流生成图表与结论…'}
            </p>
          </div>
        </div>
      )}

      {/* 高级选项开关 */}
      <div className="flex items-center justify-between mt-4">
        <button
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <span className={`inline-block transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▶</span>
          高级选项{showAdvanced ? '（点击收起）' : ''}
        </button>
        {!showAdvanced && <span className="text-[11px] text-gray-500">图表、字段、Agent 模式等高级配置</span>}
      </div>

      {/* 模型选择 + Agent 模式 */}
      {showAdvanced && (
      <>
      <div className="flex items-center gap-4 mt-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-gray-400" />
          <select className="border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
          <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${agentMode === 'single' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('single')}>
            单 Agent
          </button>
          <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1 ${agentMode === 'multi' ? 'bg-white text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('multi')}>
            <GitBranch className="w-3 h-3" /> 多智能体
          </button>
        </div>
        {agentMode === 'multi' && <span className="text-[11px] text-accent">Supervisor + 3 个 Worker Agent</span>}
      </div>

      {/* Chart type */}
      <div className="mt-6">
        <p className="text-xs font-semibold text-gray-500 mb-3">图表类型</p>
        <div className="grid grid-cols-4 gap-2">
          {chartTypes.map((ct) => {
            const Icon = ct.icon;
            const active = chartType === ct.id;
            return (
              <div
                key={ct.id}
                className={`rounded-xl p-3 text-center cursor-pointer transition-all ${
                  active
                    ? 'border-2 border-accent bg-accent-soft'
                    : 'border border-gray-200 hover:border-accent/60 hover:bg-gray-50'
                }`}
                onClick={() => handleChartSelect(ct.id)}
              >
                <Icon className={`w-6 h-6 mx-auto mb-1 ${active ? 'text-accent' : 'text-gray-400'}`} />
                <p className={`text-xs ${active ? 'text-accent font-medium' : 'text-gray-500'}`}>{ct.label}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Config fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">X 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={xAxis} onChange={(e) => setXAxis(e.target.value)}>
            {fields.map((f) => <option key={f} value={f}>{textFields.includes(f) ? `✎ ${f}` : f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Y 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={yAxis} onChange={(e) => setYAxis(e.target.value)}>
            {numFields.map((f) => <option key={f}>{f}</option>)}
            {numFields.length === 0 && fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">分组字段</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={groupField} onChange={(e) => setGroupField(e.target.value)}>
            <option>无</option>
            {fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">聚合方式</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={aggMethod} onChange={(e) => setAggMethod(e.target.value)}>
            {['求和', '平均值', '计数', '最大值', '最小值'].map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
      </div>
      </>
      )}
    </div>
  );
}

// ---- 分析直播：单条 Agent 决策步骤卡片 ----
const STEP_ICON = { 'LLM推理': Brain, '工具调用': Wrench, '观察': Eye, '失败': AlertTriangle };

function TraceRow({ step }) {
  const r = step.record || {};
  const kind = step.status === 'active' ? 'active' : (r['状态'] === '失败' ? 'failed' : 'done');
  const Icon = STEP_ICON[r['步骤']] || Zap;
  const title = r['步骤'] === '工具调用'
    ? `工具调用 · ${r['工具名'] || '未知工具'}`
    : (r['步骤'] || '步骤');
  const desc = r['说明'] || r['理由'] || r['prompt摘要'] || r['工具输出摘要'] || (r['步骤'] === '工具调用' ? '执行数据分析工具' : '');
  const meta = r['耗时_ms'] != null
    ? `${(r['耗时_ms'] / 1000).toFixed(1)}s${r['token']?.total_tokens ? ` · ${r['token'].total_tokens} tok` : ''}`
    : '—';
  const statusLabel = kind === 'active' ? '进行中' : (kind === 'failed' ? '失败' : '完成');

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${kind === 'active' ? 'bg-accent-soft' : ''}`}>
      <span
        className={`w-7 h-7 rounded-lg flex items-center justify-center text-[13px] shrink-0 ${
          kind === 'active'
            ? 'bg-accent text-white'
            : kind === 'failed'
              ? 'bg-red-50 text-red-500'
              : 'bg-ok-soft text-ok'
        }`}
        style={kind === 'active' ? { animation: 'live-blink 1.2s infinite' } : undefined}
      >
        <Icon className="w-4 h-4" />
      </span>
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-semibold truncate ${kind === 'failed' ? 'text-red-600' : 'text-gray-700'}`}>{title}</p>
        {desc && <p className="text-[11px] text-gray-400 mt-0.5 truncate">{desc}</p>}
      </div>
      <span className="text-[10px] text-gray-400 font-variant-numeric shrink-0">{meta}</span>
      <span
        className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
          kind === 'active'
            ? 'bg-amber-soft text-amber'
            : kind === 'failed'
              ? 'bg-red-50 text-red-500'
              : 'bg-ok-soft text-ok'
        }`}
      >
        {statusLabel}
      </span>
    </div>
  );
}
