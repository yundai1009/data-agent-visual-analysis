/* =============================================================================
 * 文件：frontend/src/pages/Analysis.jsx —— 智能分析页（路由 /analysis，平台核心页面）
 * 功能：
 *   1. 自然语言描述需求 + 模板快捷输入 + 图表/字段/聚合方式高级配置
 *   2. handleGenerate 构造 payload 调 generateReportStream（SSE 直播 Agent 决策流）
 *   3. 分析直播区：左侧决策流逐步渲染 + 右侧图表生长动画 + 计时
 *   4. 多轮追问：基于最近一次报表继续问（携带 上一报表ID）
 *   5. 智能推荐模式：图表/字段不显式选择时交给后端 LLM 决策（字段传空）
 * 依赖：
 *   - api.js generateReportStream —— SSE 流式分析接口
 *   - AppContext useApp().dataset —— 当前数据集（含 数据画像/字段列表）
 *   - validators/chartFields.js —— 图表字段适配校验（handleGenerate 内调用）
 *   - components/LLMConfig —— LLM 模型配置入口
 * ============================================================================= */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, Sparkles, BarChart3, LineChart, PieChart, ScatterChart, Table, Layers, Loader2, Cpu, GitBranch, X, Brain, Wrench, Eye, AlertTriangle, MessageSquare, ArrowRight, Bookmark } from 'lucide-react';
import LLMConfig from '../components/LLMConfig';
import { generateReportStream, listTemplates, saveTemplate, deleteTemplate, runTemplate } from '../api';
import { useApp } from '../AppContext';
import validateChartFields from '../validators/chartFields';

// 图表类型英文键 → 中文名映射：payload 里传给后端的“图表类型”必须是中文（chartMap[chartType]）
const chartMap = {
  auto: '自动推荐', bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图',
  heatmap: '热力图', table: '表格', stacked: '堆积柱状图',
  histogram: '直方图', area: '面积图', radar: '雷达图', wordcloud: '词云图',
  funnel: '漏斗图', sankey: '桑基图', boxplot: '箱线图', donut: '环形图',
  waterfall: '瀑布图', sunburst: '旭日图', candlestick: 'K线图',
};

// 图表类型选择面板的数据源：id（英文键）+ 图标 + 展示名，网格渲染
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

// 快捷模板：点击后把固定句式填入输入框，降低新手描述需求的门槛
const templates = [
  { label: '占比分布', icon: PieChart, text: '按【地区】统计【销售额】占比' },
  { label: '趋势变化', icon: LineChart, text: '按【月份】统计【销售额】趋势变化' },
  { label: '分组对比', icon: BarChart3, text: '按【地区】分组对比【销售额】平均值' },
  { label: '交叉分析', icon: GitBranch, text: '按【地区】和【岗位类型】做【销售额】交叉分析' },
];

// 可选模型下拉：空 id = 系统默认（后端按账号配置决定）
const models = [
  { id: '', label: '系统默认' },
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { id: 'gpt-4o', label: 'GPT-4o' },
  { id: 'deepseek-chat', label: 'DeepSeek Chat' },
];

// Analysis 智能分析页主组件
// 无 props：全部数据来自 useApp() 的 dataset（当前选中数据集）；路由跳转用 useNavigate
// 业务定位：平台三大主页面之一，是“自然语言 → 报表”的主入口
export default function Analysis() {
  const navigate = useNavigate();
  const { dataset } = useApp();
  // 表单状态：自然语言输入 / 图表类型 / 生成中标记
  const [nlInput, setNlInput] = useState('');
  const [chartType, setChartType] = useState('auto');
  const [generating, setGenerating] = useState(false);
  // 高级配置：X/Y 轴、分组字段、聚合方式（空值 = 交给后端自动决定）
  const [xAxis, setXAxis] = useState('');
  const [yAxis, setYAxis] = useState('');
  const [groupField, setGroupField] = useState('');
  const [aggMethod, setAggMethod] = useState('求和');
// 阶段 29：筛选条件 + TopN（业务高频分析——"只看华东区" / "销量 Top 10"）
const 筛选操作列表 = ['等于', '不等于', '包含', '大于', '大于等于', '小于', '小于等于', '为空', '不为空'];
const [filters, setFilters] = useState([]); // [{ 字段, 操作, 值 }]，AND 语义
const [topN, setTopN] = useState('');       // 数字字符串，空 = 不限制
const 更新筛选 = (i, key, val) => setFilters(prev => prev.map((f, idx) => idx === i ? { ...f, [key]: val } : f));
const 添加筛选 = () => setFilters(prev => [...prev, { 字段: '', 操作: '等于', 值: '' }]);
const 删除筛选 = (i) => setFilters(prev => prev.filter((_, idx) => idx !== i));
  // Agent 模式：single 单 Agent / multi 多智能体（Supervisor + 3 Worker）
  const [agentMode, setAgentMode] = useState('single');
  const [selectedModel, setSelectedModel] = useState('');
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  // 阶段 30：报表模板（分析配置收藏 + 一键复用/执行）
  const [savedTemplates, setSavedTemplates] = useState([]);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [runningTemplateId, setRunningTemplateId] = useState('');
  const [templateMsg, setTemplateMsg] = useState('');
  const lastPayloadRef = useRef(null); // 最近一次实际发出的生成请求（保存模板用）
  // 分析直播状态（SSE 实时决策流）
  const [liveSteps, setLiveSteps] = useState([]);      // [{ record, status: 'done'|'active' }]
  const [liveError, setLiveError] = useState('');
  const [liveDone, setLiveDone] = useState(null);       // { 报表ID, 标题 }
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  // 多轮追问：最近一次分析完成的报表ID（追问链），追问输入框内容
  const lastReportIdRef = useRef(null);
  // B6 修复：请求序号守卫——取消后立即重开时，旧 finally 不能误关新请求的 generating
  const generateSeqRef = useRef(0);
  const [followUp, setFollowUp] = useState('');

  // 从数据集画像里拆出字段分类：数值/分类/日期/文本，供选图和下拉框使用
  const profile = dataset?.数据画像;
  const fields = profile?.字段列表 || [];
  const numFields = profile?.数值字段 || [];
  const catFields = profile?.分类字段 || [];
  const dateFields = profile?.日期字段 || [];
  const textFields = profile?.文本字段 || [];

  // 选中图表类型时按语义自动重选字段（自然语言/点击图表都不用手动选字段）
  // 入参 id：图表类型英文键（'auto'/'bar'/'line'/...）
  // 业务定位：把“选图”和“选字段”两个动作合并，用户只需点一次图表类型
  const handleChartSelect = (id) => {
    setChartType(id);
    // 智能推荐：字段交给后端 Agent/LLM 决策，清空显式选择
    // 【关键行】选“智能推荐”时把 X/Y/分组全部清空，让后端 LLM 自由决定字段。
    // 为什么：auto 模式的本意就是“我不指定，AI 看着办”；若残留上一张图的字段，
    //   后端会被陈旧字段误导，生成的图与用户意图对不上。
    // 删除后果：切换回智能推荐后仍带着上一张图的字段，AI 被“半指定”状态束缚，
    //   推荐结果总与自然语言描述相悖。
    // 替代方案：把旧字段也传给后端让它参考（可能保留用户偏好），但语义不清——
    //   后端分不清是“用户指定”还是“历史残留”；清空让契约更明确。
    if (id === 'auto') {
      setXAxis(''); setYAxis(''); setGroupField('无');
      return;
    }
    // set 局部函数：统一把三字段写入 state，空值兜底（x 空 → ''，分组空 → '无'）
    const set = (x, y, g) => { setXAxis(x || ''); setYAxis(y || ''); setGroupField(g || '无'); };
    switch (id) {
      // 词云：拿文本字段（词频统计）或分类字段兜底，无 Y 轴
      case 'wordcloud':
        set(textFields[0] || catFields[0] || '', '', '无'); break;
      // 散点：需要两个数值字段（X 与 Y 都是数值），缺第二个时用第一个顶替
      case 'scatter':
        set(numFields[0] || '', numFields[1] || numFields[0] || '', '无'); break;
      // 箱线图/蜡烛图：X 用分类或日期，Y 用数值；X 与 Y 撞了换第二个分类字段
      case 'boxplot':
      case 'candlestick': {
        let x = (id === 'candlestick' ? dateFields[0] : catFields[0]) || catFields[0] || dateFields[0] || '';
        const y = numFields[0] || '';
        if (x === y) x = dateFields[0] || catFields[1] || '';
        set(x, y, '无'); break;
      }
      // 热力图/堆积/桑基/旭日：X 分类 + Y 数值 + 第二个分类做分组（交叉维度）
      case 'heatmap':
      case 'stacked':
      case 'sankey':
      case 'sunburst':
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', catFields[1] || '无'); break;
      // 雷达：X 分类（维度）+ Y 数值（各维度取值）
      case 'radar':
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', '无'); break;
      // 直方图：X 和 Y 都用同一个数值字段（分布统计）
      case 'histogram':
        set(numFields[0] || '', numFields[0] || '', '无'); break;
      // 折线/面积：X 优先日期（时间趋势），退而求其次分类
      case 'line':
      case 'area':
        set(dateFields[0] || catFields[0] || '', numFields[0] || '', '无'); break;
      // 默认（柱状等）：X 分类 + Y 数值
      default:
        set(catFields[0] || dateFields[0] || '', numFields[0] || '', '无');
    }
  };

  // 智能推荐模式（auto）不预填：字段交给后端 Agent/LLM 决策
  // 首次加载数据集时自动预填一次 X/Y/分组（仅在 xAxis 为空时），避免用户空着字段
  useEffect(() => {
    if (profile && chartType !== 'auto' && !xAxis) {
      setXAxis((profile.分类字段?.[0] || profile.日期字段?.[0] || fields[0] || ''));
      setYAxis(numFields[0] || '');
      setGroupField('无');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, chartType]);

  // 生成期间计时（每秒 +1）+ 决策流自动滚动到底部（liveSteps.length 变化时触发）
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [generating]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveSteps.length]);

  // 收到 done 事件后不再自动跳转：停留本页让用户选择「继续追问」或「查看报表」（批次3 多轮追问）
  // （自动跳转会在 1 秒内打断追问流程，已移除）

  // 取消按钮：abort 当前 SSE 请求 + 重置直播状态
  const handleCancel = () => {
    abortRef.current?.abort();
    setGenerating(false);
    setLiveSteps([]);
    setLiveError('');
    setLiveDone(null);
  };

  // 生成报表主函数
  // 入参：isFollowUp = true 时进入「追问模式」——清空上一轮字段，携带 lastReportId 传给后端
  // 业务定位：整个分析流程的入口，串联 payload 构造 → SSE 发起 → 事件驱动 UI
  async function handleGenerate(isFollowUp = false) {
    if (!dataset) {
      setError('请先在数据管理页面上传数据');
      navigate('/data');
      return;
    }
    // 智能推荐模式（字段未显式选择）跳过前端校验：字段由后端 Agent/LLM 决策
    // 追问模式（isFollowUp）也跳过旧字段校验：系统会按追问语义重新选字段
    if (!isFollowUp) {
      // 智能推荐模式（xAxis/yAxis 为空）跳过前端校验——字段由后端 LLM 决策
      const validationError = xAxis && yAxis
        ? validateChartFields(chartType, xAxis, yAxis, groupField, profile)
        : null;
      if (validationError) {
        setError(validationError);
        return;
      }
    }
    setError('');
    setLiveError('');
    setLiveDone(null);
    setLiveSteps([]);
    setElapsed(0);
    setGenerating(true);

    // 构造分析请求 payload（字段全中文键名，与后端契约一致）
    // 【关键行】智能推荐模式下 x轴/y轴/分组字段传 null/[]，把字段决策权交给后端 LLM。
    // 为什么：用户没显式选字段时（xAxis/yAxis 为空），前端不具备理解自然语言的能力，
    //   硬传“第一个分类字段”只会帮倒忙；后端 Agent 会结合 分析需求 文本自主选字段。
    // 删除后果：若把空字符串/undefined 直接传过去，后端契约里可能解析成“用户指定了空字段”，
    //   导致生成空图或报参数错误；null 是明确的“未指定”语义。
    // 替代方案：前端用规则引擎猜字段（速度更快但准确率低，词义理解不到位）；
    //   把决策交给 LLM 是智能推荐模式的核心理念，准确率远高于规则。
    const payload = {
      数据集ID: dataset.数据集ID,
      // 追问时优先用追问输入（followUp），为空退回主输入框内容
      分析需求: isFollowUp ? (followUp.trim() || nlInput) : nlInput,
      // 追问固定走“自动推荐”：新问题不一定适配上一张图的类型，让后端重新决策
      图表类型: isFollowUp ? '自动推荐' : (chartMap[chartType] || '自动推荐'),
      // '无' 是 UI 里“不分组”的占位值，转成 null 才是后端契约的“不分组”
      x轴: isFollowUp ? null : (xAxis === '无' ? null : xAxis),
      // y轴 是数组：支持多指标；空数组 = 未指定（交给后端），[yAxis] = 指定一个
      y轴: isFollowUp ? [] : (yAxis ? [yAxis] : []),
      分组字段: isFollowUp ? null : (groupField === '无' ? null : groupField),
      聚合方式: isFollowUp ? '求和' : aggMethod,
      // 阶段 29：筛选（追问时清空——新问题不一定延续原筛选，交给后端重新决策）
      筛选条件: isFollowUp ? [] : filters
        .filter(f => f.字段 && f.操作 && (['为空', '不为空'].includes(f.操作) || f.值 !== ''))
        .map(f => ({ 字段: f.字段, 操作: f.操作, 值: f.值 })),
      topN: isFollowUp ? undefined : (topN ? parseInt(topN, 10) : undefined),
      agent_mode: agentMode,
      model: selectedModel || undefined, // undefined 不出现在 JSON 里，后端走默认模型
      上一报表ID: isFollowUp ? (lastReportIdRef.current || undefined) : undefined, // 追问链：后端基于上一报表上下文续答
    };
    lastPayloadRef.current = payload; // 阶段 30：记录本次实际配置，供"保存为模板"使用
    const controller = new AbortController();
    abortRef.current = controller; // 供「取消」按钮随时中断请求
    const seq = ++generateSeqRef.current; // B6：本次请求序号（防旧请求的 finally 误关新请求）

    try {
      // 发起 SSE 流式分析：每收到一个事件就回调 onEvent，驱动直播 UI 实时更新
      await generateReportStream(payload, {
        signal: controller.signal,
        onEvent: (ev) => {
          // 【关键行】step 事件：把新一步追加进 liveSteps，旧步骤全部置为 done。
          // 为什么：决策流是“从上到下逐步生长”的，当前正在执行的一步要高亮
          //   （active 状态 + 呼吸灯动画），已完成步骤保持灰色对勾。
          // 删除后果：决策流不再实时增长，用户看不到 Agent 工作过程，体验回到黑盒。
          // 替代方案：直接覆盖整个数组（setLiveSteps([newStep])）——历史步骤全丢；
          //   用函数式更新 prev => [...] 追加是最稳的不可变更新写法。
          if (ev.type === 'step') {
            // 上一步置为完成，新一步置为进行中
            setLiveSteps(prev => [
              ...prev.map(s => ({ ...s, status: 'done' })),
              { record: ev.data, status: 'active' },
            ]);
          } else if (ev.type === 'done') {
            // 【关键行】done 事件：全部步骤标记完成 + 记录报表 ID，并返回 'stop' 终止流。
            // 为什么：done 是最后一条事件，后面没有数据了，主动 stop 让 fetch 提前收尾，
            //   顺便把 lastReportId 存进 ref —— 追问模式要拿它当 上一报表ID。
            // 删除后果：不 stop 也能正常结束（流自然关闭），但会多等一个网络周期；
            //   不存 lastReportId 则追问功能彻底失效（报“还没有可追问的分析结果”）。
            // 替代方案：把报表 ID 放进全局状态（Context）——多一层状态源；ref 是
            //   纯内部记忆，不触发渲染，最适合存这类“只给下次请求用”的值。
            setLiveSteps(prev => prev.map(s => ({ ...s, status: 'done' })));
            setLiveDone({ 报表ID: ev.报表ID, 标题: ev.标题 });
            lastReportIdRef.current = ev.报表ID;  // 更新追问链
            return 'stop';
          } else if (ev.type === 'error') {
            // 服务端主动推送的分析失败：展示错误并停止消费流
            setLiveError(ev.message || '分析失败，请重试');
            return 'stop';
          }
          return undefined;
        },
      });
    } catch (e) {
      // 请求层错误：HTTP 状态 / 网络 / 用户取消
      if (e.name === 'AbortError') return; // 取消不报错
      // 按错误类型给出针对性提示（401 会先触发全局登出，这里只是补充文案）
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
      // B6：仅最新请求可收尾（旧请求的取消/完成不干扰新请求状态）
      if (generateSeqRef.current === seq) {
        setGenerating(false);
      }
    }
  }

  // ── 阶段 30：报表模板 ──
  // 模板 = 分析配置收藏："保存当前配置" 供下次一键复用/定时执行
  const loadTemplates = async () => {
    try {
      const res = await listTemplates();
      setSavedTemplates(res?.模板列表 || []);
    } catch (e) {
      setTemplateMsg('模板列表加载失败：' + (e.message || e));
    }
  };
  // 保存模板：用最近一次实际发出的生成配置（lastPayloadRef），避免用户改了表单但没点生成
  const handleSaveTemplate = async () => {
    const name = templateName.trim();
    if (!name) { setTemplateMsg('请先填写模板名称'); return; }
    if (!lastPayloadRef.current) { setTemplateMsg('请先完成一次分析（或直接点生成），再保存为模板'); return; }
    setSavingTemplate(true);
    setTemplateMsg('');
    try {
      const payload = { ...lastPayloadRef.current };
      delete payload.上一报表ID; // 模板不携带追问链
      await saveTemplate(name, payload);
      setTemplateMsg(`模板「${name}」已保存`);
      setTemplateName('');
      await loadTemplates();
    } catch (e) {
      setTemplateMsg('保存失败：' + (e.message || e));
    } finally {
      setSavingTemplate(false);
    }
  };
  // 立即执行模板：后端用模板配置 + 最新数据生成报表，跳转查看
  const handleRunTemplate = async (tpl) => {
    setRunningTemplateId(tpl.模板ID);
    setTemplateMsg('');
    try {
      const res = await runTemplate(tpl.模板ID);
      navigate(`/report/${res.报表ID}`);
    } catch (e) {
      setTemplateMsg(`模板「${tpl.名称}」执行失败：` + (e.message || e));
    } finally {
      setRunningTemplateId('');
    }
  };
  // 把模板配置反填进表单：编辑后用（图表中文名 → chartMap 反查英文 id）
  const handleLoadTemplate = (tpl) => {
    setShowTemplates(false);
    setError('');
    const p = tpl.payload || {};
    if (p.数据集ID && dataset && p.数据集ID !== dataset.数据集ID) {
      setError(`模板绑定的是另一份数据集（${p.数据集ID.slice(0, 8)}…），请先在数据管理选择对应数据集`);
    }
    setNlInput(p.分析需求 || '');
    if (p.图表类型) {
      const id = Object.keys(chartMap).find(k => chartMap[k] === p.图表类型);
      if (id) setChartType(id);
    }
    setXAxis(p.x轴 || '');
    setYAxis(Array.isArray(p.y轴) && p.y轴.length ? p.y轴[0] : '');
    setGroupField(p.分组字段 || '');
    setAggMethod(p.聚合方式 || '求和');
    setFilters((p.筛选条件 || []).map(f => ({ 字段: f.字段, 操作: f.操作, 值: f.值 ?? '' })));
    setTopN(p.topN ? String(p.topN) : '');
    setAgentMode(p.agent_mode || 'single');
  };
  const handleDeleteTemplate = async (tpl) => {
    try {
      await deleteTemplate(tpl.模板ID);
      setSavedTemplates(prev => prev.filter(t => t.模板ID !== tpl.模板ID));
    } catch (e) {
      setTemplateMsg('删除失败：' + (e.message || e));
    }
  };

  // 继续追问：基于最近一次分析结果发起新一轮分析（录入追问 → 走 handleGenerate(true)）
  // 追问的语义：后端拿到 上一报表ID + 新问题，会结合上一份报表的上下文续答
  const handleFollowUp = async () => {
    const q = followUp.trim();
    if (!q) return; // 空追问直接忽略
    if (!lastReportIdRef.current) {
      setError('还没有可追问的分析结果，请先完成一次分析');
      return;
    }
    setNlInput(q);          // 主输入框同步展示（便于观察本轮需求）
    await handleGenerate(true);
    setFollowUp('');
  };

  // 图表类型字段适配校验（逻辑抽到 validators/chartFields.js 便于单测，handleGenerate 内调用）

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-7">
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">智能分析</h1>
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

      {/* Input（输入容器保留边框，区别于展示卡） */}
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

      {/* 意图预览条：输入自然语言后展示系统自动选择的图表/字段，确认后再生成
          （B21 修复：预览与实际提交一致，不再恒显“自动”） */}
      {nlInput.trim().length > 0 && !generating && (
        <div className="flex items-center gap-2 flex-wrap mt-3 px-4 py-2.5 rounded-xl bg-accent-soft text-xs text-accent">
          <b className="font-semibold">已自动选择</b>
          <span
            className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors"
            onClick={() => setShowAdvanced(true)}
            title="点击修改图表类型"
          >
            {(chartMap[chartType] || '自动推荐')} ✎  {/* B21：预览与实际提交一致，不再恒显“自动” */}
          </span>
          {xAxis && (
            <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改 X 轴">
              X {xAxis} ✎
            </span>
          )}
          {yAxis && (
            <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改 Y 轴">
              Y {yAxis} ✎
            </span>
          )}
          {groupField && groupField !== '无' && (
            <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改分组字段">
              分组 {groupField} ✎
            </span>
          )}
          <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改聚合方式">
            {aggMethod} ✎
          </span>
          <span className="ml-auto opacity-70">点击任意项可修改</span>
        </div>
      )}

      {/* 分析直播：Agent 实时决策流 + 图表生长舞台 */}
      {generating && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* 左：决策流 —— 每行是一条 Agent 步骤（LLM推理/工具调用/观察） */}
          <div className="lg:col-span-3 bg-white rounded-xl shadow-[var(--shadow-card)] overflow-hidden">
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

            {/* 决策流滚动容器：liveSteps 每条渲染一个 TraceRow，新步骤追加到尾部 */}
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

          {/* 右：图表生长舞台 —— 生成期间先展示占位柱状动画，让用户看到图表“长出来” */}
          <div className="lg:col-span-2 bg-white rounded-xl shadow-[var(--shadow-card)] p-4 flex flex-col">
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

      {/* 多轮追问条：分析完成后停留本页，可继续追问或查看报表（批次3 多轮追问） */}
      {liveDone && !generating && (
        <div className="mt-3 bg-white rounded-xl shadow-[var(--shadow-card)] px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="w-4 h-4 text-accent" />
            <span className="text-xs font-semibold text-gray-700">继续追问</span>
            <span className="text-[11px] text-gray-400">基于刚才的分析结果接着问，例如「那华南区呢？」「按月份对比呢？」</span>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFollowUp(); }}
              placeholder="输入追问，如：那华南区呢？按月份对比呢？"
              className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent transition-colors"
            />
            <button
              disabled={!followUp.trim()}
              onClick={handleFollowUp}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all disabled:opacity-40"
            >
              <Zap className="w-3.5 h-3.5" /> 追问分析
            </button>
            <button
              onClick={() => navigate(`/report/${liveDone.报表ID}`)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all"
            >
              查看报表 <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* 高级选项开关：展开后显示 模型选择 / Agent 模式 / 图表类型 / 字段配置 */}
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

      {/* 模型选择 + Agent 模式：LLM 模型下拉 + 单 Agent/多智能体 切换 */}
      {showAdvanced && (
      <>
      {/* 阶段 30：模板——分析配置收藏，一键复用/执行 */}
      <div className="mt-4 border border-gray-200 rounded-xl p-3 bg-gray-50/60">
        <div className="flex items-center justify-between">
          <button
            className="flex items-center gap-1 text-xs font-semibold text-gray-600 hover:text-accent transition-colors"
            onClick={() => { setShowTemplates(!showTemplates); if (!showTemplates && savedTemplates.length === 0) loadTemplates(); }}
          >
            <Bookmark className="w-3.5 h-3.5" /> 模板{showTemplates ? '（收起）' : ''}
          </button>
          <span className="text-[11px] text-gray-400">收藏分析配置，下次一键复用 / 定时执行</span>
        </div>
        {templateMsg && <p className="text-[11px] mt-2 text-amber-600">{templateMsg}</p>}
        {showTemplates && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <input
                className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:border-accent"
                placeholder="模板名称，如：每周销售周报"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                maxLength={50}
              />
              <button
                onClick={handleSaveTemplate}
                disabled={savingTemplate}
                className="px-3 py-1.5 rounded-lg text-xs bg-accent text-white hover:opacity-90 transition-all disabled:opacity-50"
              >
                {savingTemplate ? '保存中…' : '保存当前配置'}
              </button>
            </div>
            {savedTemplates.length === 0 ? (
              <p className="text-[11px] text-gray-400 py-1">还没有模板——先完成一次分析，再点"保存当前配置"</p>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {savedTemplates.map((tpl) => (
                  <div key={tpl.模板ID} className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5">
                    <span className="flex-1 text-xs text-gray-700 truncate" title={tpl.名称}>{tpl.名称}</span>
                    <button className="text-[11px] text-accent hover:underline" onClick={() => handleLoadTemplate(tpl)} title="把配置加载到表单">加载</button>
                    <button
                      className="text-[11px] text-emerald-600 hover:underline disabled:opacity-50"
                      disabled={runningTemplateId === tpl.模板ID}
                      onClick={() => handleRunTemplate(tpl)}
                      title="立即用模板生成报表（读取最新数据）"
                    >
                      {runningTemplateId === tpl.模板ID ? '执行中…' : '执行'}
                    </button>
                    <button className="text-[11px] text-red-400 hover:text-red-600 hover:underline" onClick={() => handleDeleteTemplate(tpl)}>删除</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
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

      {/* 图表类型：网格渲染 18 种图表，点击 handleChartSelect 自动换字段 */}
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

      {/* 字段配置：X 轴 / Y 轴 / 分组 / 聚合 四个下拉；空选项「🤖 自动推荐」= 交给后端 LLM */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">X 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={xAxis} onChange={(e) => setXAxis(e.target.value)}>
            <option value="">🤖 自动推荐</option>
            {fields.map((f) => <option key={f} value={f}>{textFields.includes(f) ? `✎ ${f}` : f}</option>)}
            {/* ✎ 前缀标识文本字段（词云等场景专用） */}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Y 轴</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={yAxis} onChange={(e) => setYAxis(e.target.value)}>
            <option value="">🤖 自动推荐</option>
            {numFields.map((f) => <option key={f}>{f}</option>)}
            {/* 没有数值字段时退而求其次显示全部字段（空数据集也能选） */}
            {numFields.length === 0 && fields.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">分组字段</label>
          <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={groupField} onChange={(e) => setGroupField(e.target.value)}>
            <option value="">🤖 自动推荐</option>
            <option>无</option> {/* 「无」= 明确不分组，转成 null 传给后端 */}
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

      {/* 阶段 29：筛选条件 + TopN——"只看华东区" / "销量 Top 10" 的高级配置入口 */}
      <div className="mt-5 border-t border-gray-100 pt-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-gray-500">筛选条件 <span className="text-[10px] text-gray-400 font-normal">（多条同时满足，也可在需求里说"只看华东区"）</span></p>
          {filters.length > 0 && (
            <button className="text-[11px] text-accent hover:underline" onClick={() => setFilters([])}>清空</button>
          )}
        </div>
        <div className="space-y-2">
          {filters.map((f, i) => (
            <div key={i} className="flex items-center gap-2">
              <select className="flex-1 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent" value={f.字段} onChange={(e) => 更新筛选(i, '字段', e.target.value)}>
                <option value="">选择字段</option>
                {fields.map((fd) => <option key={fd} value={fd}>{fd}</option>)}
              </select>
              <select className="w-28 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent" value={f.操作} onChange={(e) => 更新筛选(i, '操作', e.target.value)}>
                {筛选操作列表.map((op) => <option key={op} value={op}>{op}</option>)}
              </select>
              <input
                className="flex-1 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                value={f.值 || ''}
                onChange={(e) => 更新筛选(i, '值', e.target.value)}
                placeholder={['为空', '不为空'].includes(f.操作) ? '无需填值' : '筛选值（数字/文本）'}
                disabled={['为空', '不为空'].includes(f.操作)}
              />
              <button className="text-gray-400 hover:text-red-500 transition-colors" onClick={() => 删除筛选(i)} title="删除该条件">✕</button>
            </div>
          ))}
          {filters.length < 10 && (
            <button className="text-[11px] text-accent hover:underline" onClick={添加筛选}>+ 添加条件</button>
          )}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <label className="text-xs text-gray-400 shrink-0">Top N</label>
          <input
            type="number" min="1" max="200"
            className="w-24 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
            value={topN}
            onChange={(e) => setTopN(e.target.value)}
            placeholder="如 10"
            title="只保留聚合结果中数值最大的前 N 行（如：销量 Top 10）"
          />
          <span className="text-[11px] text-gray-400">只保留数值最大的前 N 行（如"销量 Top 10"）</span>
        </div>
      </div>
      </>
      )}
    </div>
  );
}

// ---- 分析直播：单条 Agent 决策步骤卡片 ----
// 步骤图标映射：不同步骤类型对应不同图标（LLM推理=大脑 / 工具调用=扳手 / 观察=眼睛 / 失败=警告）
const STEP_ICON = { 'LLM推理': Brain, '工具调用': Wrench, '观察': Eye, '失败': AlertTriangle };

// TraceRow 步骤卡片组件：渲染决策流中的一行
// 入参：step = { record: 后端步骤对象（含 步骤/说明/状态/耗时/token）, status: 'active'|'done' }
// 返回：一行带图标 + 标题 + 描述 + 耗时 + 状态标签的卡片；active 时高亮背景 + 左边蓝条
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
    <div className={`relative flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${kind === 'active' ? 'bg-accent-soft' : ''}`}>
      {kind === 'active' && (
        <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-[3px]"
              style={{ background: 'linear-gradient(180deg, #4a8ac2, #0f4c81)' }} />
      )}
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
