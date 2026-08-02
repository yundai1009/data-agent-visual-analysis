import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, Sparkles, BarChart3, LineChart, PieChart, ScatterChart, Table, Layers, Loader2, Cpu, GitBranch } from 'lucide-react';
import LLMConfig from '../components/LLMConfig';
import { generateReport } from '../api';
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
  { label: '📊 占比分布', text: '按【地区】统计【销售额】占比' },
  { label: '📈 趋势变化', text: '按【月份】统计【销售额】趋势变化' },
  { label: '📊 分组对比', text: '按【地区】分组对比【销售额】平均值' },
  { label: '🔀 交叉分析', text: '按【地区】和【岗位类型】做【销售额】交叉分析' },
];

const models = [
  { id: '', label: '系统默认' },
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { id: 'gpt-4o', label: 'GPT-4o' },
  { id: 'deepseek-chat', label: 'DeepSeek Chat' },
  { id: 'deepseek-v4', label: 'DeepSeek V4' },
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

  const profile = dataset?.数据画像;
  const fields = profile?.字段列表 || [];
  const numFields = profile?.数值字段 || [];
  const catFields = profile?.分类字段 || [];
  const dateFields = profile?.日期字段 || [];

  // Auto-fill based on profile（useEffect 中执行，避免 render 阶段 setState）
  useEffect(() => {
    if (profile && !xAxis) {
      setXAxis((profile.分类字段?.[0] || profile.日期字段?.[0] || fields[0] || ''));
      setYAxis(numFields[0] || '');
      setGroupField('无');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

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
    setGenerating(true);
    try {
      const res = await generateReport({
        数据集ID: dataset.数据集ID,
        分析需求: nlInput,
        图表类型: chartMap[chartType] || '自动推荐',
        x轴: xAxis === '无' ? null : xAxis,
        y轴: yAxis ? [yAxis] : [],
        分组字段: groupField === '无' ? null : groupField,
        聚合方式: aggMethod,
        agent_mode: agentMode,
        model: selectedModel || undefined,
      });
      // 报表已由后端持久化（阶段 6），直接跳转到报表详情页，不再写 sessionStorage 缓存
      window.location.href = '/report/' + res.报表ID;
    } catch (e) {
      // 区分错误类型
      if (e.message?.includes('401') || e.message?.includes('UNAUTHORIZED')) {
        setError('认证配置不正确，请检查 AUTH_ENABLED 设置');
      } else if (e.message?.includes('413') || e.message?.includes('large')) {
        setError('文件超过大小限制（最大 50MB）');
      } else if (e.message?.includes('Failed to fetch') || e.message?.includes('NetworkError')) {
        setError('后端服务不可用，请检查后端是否启动');
      } else {
        setError('分析失败：' + e.message);
      }
    }
    setGenerating(false);
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
        {dataset && <p className="text-xs text-indigo-500 mt-1">当前数据集：{dataset.文件名}</p>}
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
            className="w-full bg-transparent border-0 text-sm text-gray-700 resize-none focus:outline-none placeholder:text-gray-300 leading-relaxed"
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
                  className="px-3 py-1.5 rounded-lg bg-white text-xs text-gray-500 cursor-pointer hover:bg-gray-100 hover:text-gray-700 transition-all border border-gray-200"
                  onClick={() => setNlInput(t.text)}
                >
                  {t.label}
                </span>
              ))}
            </div>
          </div>
          <button
            disabled={generating}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 transition-all active:scale-[.98] disabled:opacity-50"
            onClick={handleGenerate}
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            {generating ? '分析中…' : '开始分析'}
          </button>
        </div>
      </div>

      {/* 高级选项开关 */}
      <div className="flex items-center justify-between mt-4">
        <button
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <span className={`inline-block transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▶</span>
          高级选项{showAdvanced ? '（点击收起）' : ''}
        </button>
        {!showAdvanced && <span className="text-[11px] text-gray-300">图表、字段、Agent 模式等高级配置</span>}
      </div>

      {/* 模型选择 + Agent 模式 */}
      {showAdvanced && (
      <>
      <div className="flex items-center gap-4 mt-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-gray-400" />
          <select className="border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-indigo-400" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
          <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${agentMode === 'single' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('single')}>
            单 Agent
          </button>
          <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1 ${agentMode === 'multi' ? 'bg-white text-indigo-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('multi')}>
            <GitBranch className="w-3 h-3" /> 多智能体
          </button>
        </div>
        {agentMode === 'multi' && <span className="text-[11px] text-indigo-500">Supervisor + 3 个 Worker Agent</span>}
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
                    ? 'border-2 border-indigo-500 bg-indigo-50'
                    : 'border border-gray-200 hover:border-indigo-300 hover:bg-gray-50'
                }`}
                onClick={() => setChartType(ct.id)}
              >
                <Icon className={`w-6 h-6 mx-auto mb-1 ${active ? 'text-indigo-500' : 'text-gray-300'}`} />
                <p className={`text-xs ${active ? 'text-indigo-600 font-medium' : 'text-gray-500'}`}>{ct.label}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Config fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">X 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-indigo-400" value={xAxis} onChange={(e) => setXAxis(e.target.value)}>
            {fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Y 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-indigo-400" value={yAxis} onChange={(e) => setYAxis(e.target.value)}>
            {numFields.map((f) => <option key={f}>{f}</option>)}
            {numFields.length === 0 && fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">分组字段</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-indigo-400" value={groupField} onChange={(e) => setGroupField(e.target.value)}>
            <option>无</option>
            {fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">聚合方式</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-indigo-400" value={aggMethod} onChange={(e) => setAggMethod(e.target.value)}>
            {['求和', '平均值', '计数', '最大值', '最小值'].map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
      </div>
      </>
      )}
    </div>
  );
}
