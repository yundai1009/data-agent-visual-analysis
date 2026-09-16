/**
 * hooks/useAnalysis.js — 智能分析页的业务逻辑 Hook（从 Analysis.jsx 拆分）
 *
 * 职责：智能分析页的全部状态与逻辑——
 *  - 表单状态（需求/图表/字段/聚合/筛选/TopN/对比/Agent模式/模型）
 *  - SSE 直播状态（liveSteps/liveError/liveDone/elapsed）
 *  - handleGenerate 主流程（payload 构造 + generateReportStream 事件驱动）
 *  - handleChartSelect 图表切换自动选字段
 *  - 模板 CRUD / 定时任务 CRUD / 多轮追问
 *  - 相关 useEffect（数据集字段预填、计时、滚动）
 *
 * Analysis.jsx 只负责 JSX 渲染，从本 Hook 取状态与动作。
 */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { generateReportStream, listTemplates, saveTemplate, deleteTemplate, runTemplate, listSchedules, createSchedule, deleteSchedule } from '../api';
import { useApp } from '../AppContext';
import validateChartFields from '../validators/chartFields';

// 图表类型英文键 → 中文名映射：payload 里传给后端的"图表类型"必须是中文（chartMap[chartType]）
export const chartMap = {
  auto: '自动推荐', bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图',
  heatmap: '热力图', table: '表格', stacked: '堆积柱状图',
  histogram: '直方图', area: '面积图', radar: '雷达图', wordcloud: '词云图',
  funnel: '漏斗图', sankey: '桑基图', boxplot: '箱线图', donut: '环形图',
  waterfall: '瀑布图', sunburst: '旭日图', candlestick: 'K线图',
};

// 筛选操作列表（阶段 29）
export const 筛选操作列表 = ['等于', '不等于', '包含', '大于', '大于等于', '小于', '小于等于', '为空', '不为空'];

export default function useAnalysis() {
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
  // 阶段 29：筛选条件 + TopN
  const [filters, setFilters] = useState([]); // [{ 字段, 操作, 值 }]，AND 语义
  const [topN, setTopN] = useState('');       // 数字字符串，空 = 不限制
  // 阶段 30：同比环比
  const [compare, setCompare] = useState(''); // '' | '环比' | '同比'
  const 更新筛选 = (i, key, val) => setFilters(prev => prev.map((f, idx) => idx === i ? { ...f, [key]: val } : f));
  const 添加筛选 = () => setFilters(prev => [...prev, { 字段: '', 操作: '等于', 值: '' }]);
  const 删除筛选 = (i) => setFilters(prev => prev.filter((_, idx) => idx !== i));
  // Agent 模式：single / multi
  const [agentMode, setAgentMode] = useState('single');
  const [selectedModel, setSelectedModel] = useState('');
  const [error, setError] = useState('');
  const [advice, setAdvice] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  // 阶段 30：报表模板
  const [savedTemplates, setSavedTemplates] = useState([]);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [runningTemplateId, setRunningTemplateId] = useState('');
  const [templateMsg, setTemplateMsg] = useState('');
  // 阶段 30：定时任务
  const [schedules, setSchedules] = useState([]);
  const [scheduleCron, setScheduleCron] = useState('');
  const [scheduleTplId, setScheduleTplId] = useState('');
  const [scheduleMsg, setScheduleMsg] = useState('');
  const lastPayloadRef = useRef(null); // 最近一次实际发出的生成请求（保存模板用）
  // 分析直播状态（SSE 实时决策流）
  const [liveSteps, setLiveSteps] = useState([]);      // [{ record, status: 'done'|'active' }]
  const [liveError, setLiveError] = useState('');
  const [liveDone, setLiveDone] = useState(null);       // { 报表ID, 标题 }
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef(null);
  // F-M1：记录当前数据集 ID，用于切换数据集时重置字段
  const datasetRef = useRef(null);
  const scrollRef = useRef(null);
  const [showChartSwitch, setShowChartSwitch] = useState(false);
  // 多轮追问
  const lastReportIdRef = useRef(null);
  // B6：请求序号守卫
  const generateSeqRef = useRef(0);
  // F-S4：并发守卫
  const generatingRef = useRef(false);
  const [followUp, setFollowUp] = useState('');

  // 从数据集画像里拆出字段分类
  const profile = dataset?.数据画像;
  const fields = profile?.字段列表 || [];
  const numFields = profile?.数值字段 || [];
  const catFields = profile?.分类字段 || [];
  const dateFields = profile?.日期字段 || [];
  const textFields = profile?.文本字段 || [];

  // 选中图表类型时按语义自动重选字段
  const handleChartSelect = (id) => {
    setChartType(id);
    if (id === 'auto') {
      setXAxis(''); setYAxis(''); setGroupField('无');
      return;
    }
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

  // 首次加载数据集时自动预填一次 X/Y/分组（仅 xAxis 为空时）
  useEffect(() => {
    if (profile && chartType !== 'auto') {
      const switched = datasetRef.current !== dataset?.数据集ID;
      datasetRef.current = dataset?.数据集ID;
      if (switched || !xAxis) {
        setXAxis((profile.分类字段?.[0] || profile.日期字段?.[0] || fields[0] || ''));
        setYAxis(numFields[0] || '');
        setGroupField('无');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset?.数据集ID, profile, chartType]);

  // 生成期间计时（每秒 +1）
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [generating]);

  // 决策流自动滚动到底部
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveSteps.length]);

  // 取消按钮：abort 当前 SSE 请求 + 重置直播状态
  const handleCancel = () => {
    abortRef.current?.abort();
    generatingRef.current = false; // P0 修复（Bug3）：取消必须同步释放并发守卫
    setGenerating(false);
    setLiveSteps([]);
    setLiveError('');
    setLiveDone(null);
    setShowChartSwitch(false);
  };

  // 生成报表主函数
  async function handleGenerate(isFollowUp = false, chartTypeOverride = null) {
    if (generatingRef.current) return false;
    generatingRef.current = true;
    if (!dataset) {
      generatingRef.current = false;
      setError('请先在数据管理页面上传数据');
      navigate('/data');
      return false;
    }
    setShowChartSwitch(false);
    if (!isFollowUp) {
      const activeChartType = chartTypeOverride || chartType;
      const needsY = ['scatter', 'boxplot', 'candlestick', 'waterfall'].includes(activeChartType);
      const validationError = (needsY || xAxis || yAxis)
        ? validateChartFields(activeChartType, xAxis || '', yAxis || '', groupField, profile)
        : null;
      if (validationError) {
        if (validationError.includes('建议')) {
          setAdvice(validationError);
        } else {
          generatingRef.current = false;
          setError(validationError);
          return false;
        }
      } else {
        setAdvice('');
      }
    }
    setError('');
    setLiveError('');
    setLiveDone(null);
    setLiveSteps([]);
    setElapsed(0);
    if (chartTypeOverride) setChartType(chartTypeOverride);
    setGenerating(true);

    const payload = {
      数据集ID: dataset.数据集ID,
      分析需求: isFollowUp ? (followUp.trim() || nlInput) : nlInput,
      // 【Bug修复】追问时若用户显式选择过图表类型（非 auto）则沿用上一图表
      // （如追问"那华南区呢？"应继续用柱状图，而不是重置为自动推荐）；
      // 用户未显式选择（auto）或显式传 chartTypeOverride 时优先用 override。
      图表类型: (() => {
        const effective = chartTypeOverride
          || (isFollowUp && chartType !== 'auto' ? chartType : null)
          || (isFollowUp ? null : chartType)
          || 'auto';
        return chartMap[effective] || '自动推荐';
      })(),
      x轴: isFollowUp ? null : ((!xAxis || xAxis === '无') ? null : xAxis),
      y轴: isFollowUp ? [] : (yAxis ? [yAxis] : []),
      分组字段: isFollowUp ? null : ((!groupField || groupField === '无') ? null : groupField),
      聚合方式: isFollowUp ? '求和' : aggMethod,
      筛选条件: isFollowUp ? [] : filters
        .filter(f => f.字段 && f.操作 && (['为空', '不为空'].includes(f.操作) || f.值 !== ''))
        .map(f => ({ 字段: f.字段, 操作: f.操作, 值: f.值 })),
      topN: isFollowUp ? undefined : (() => {
        const n = parseInt(topN, 10);
        return Number.isFinite(n) && n > 0 ? n : undefined;
      })(),
      对比: isFollowUp ? undefined : (compare || undefined),
      agent_mode: agentMode,
      model: selectedModel || undefined,
      上一报表ID: isFollowUp ? (lastReportIdRef.current || undefined) : undefined,
    };
    lastPayloadRef.current = payload;
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++generateSeqRef.current;

    try {
      await generateReportStream(payload, {
        signal: controller.signal,
        onEvent: (ev) => {
          if (ev.type === 'step') {
            setLiveSteps(prev => [
              ...prev.map(s => ({ ...s, status: 'done' })),
              { record: ev.data, status: 'active' },
            ]);
          } else if (ev.type === 'done') {
            setLiveSteps(prev => prev.map(s => ({ ...s, status: 'done' })));
            setLiveDone({ 报表ID: ev.报表ID, 标题: ev.标题 });
            setShowChartSwitch(true);
            lastReportIdRef.current = ev.报表ID;
            return 'stop';
          } else if (ev.type === 'error') {
            setLiveError(ev.message || '分析失败，请重试');
            return 'stop';
          }
          return undefined;
        },
      });
    } catch (e) {
      if (e.name === 'AbortError') return false;
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
      if (generateSeqRef.current === seq) {
        setGenerating(false);
        generatingRef.current = false;
      }
    }
    return true;
  }

  // ── 阶段 30：报表模板 ──
  const loadTemplates = async () => {
    try {
      const res = await listTemplates();
      setSavedTemplates(res?.模板列表 || []);
    } catch (e) {
      setTemplateMsg('模板列表加载失败：' + (e.message || e));
    }
  };
  const handleSaveTemplate = async () => {
    const name = templateName.trim();
    if (!name) { setTemplateMsg('请先填写模板名称'); return; }
    if (!lastPayloadRef.current) { setTemplateMsg('请先完成一次分析（或直接点生成），再保存为模板'); return; }
    setSavingTemplate(true);
    setTemplateMsg('');
    try {
      const payload = { ...lastPayloadRef.current };
      delete payload.上一报表ID;
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

  // ── 阶段 30：定时任务 ──
  const loadSchedules = async () => {
    try {
      const res = await listSchedules();
      setSchedules(res?.任务列表 || []);
    } catch (e) {
      setScheduleMsg('定时任务加载失败：' + (e.message || e));
    }
  };
  const handleCreateSchedule = async () => {
    const cron = scheduleCron.trim();
    if (!cron) { setScheduleMsg('请填写 cron 表达式（分 时 日 月 周）'); return; }
    if (!scheduleTplId) { setScheduleMsg('请选择要定时执行的模板'); return; }
    setScheduleMsg('');
    try {
      await createSchedule(scheduleTplId, cron);
      setScheduleMsg('定时任务已创建（到点自动生成报表，可在报表历史查看）');
      setScheduleCron('');
      await loadSchedules();
    } catch (e) {
      setScheduleMsg('创建失败：' + (e.message || e));
    }
  };
  const handleDeleteSchedule = async (job) => {
    try {
      await deleteSchedule(job.任务ID);
      setSchedules(prev => prev.filter(j => j.任务ID !== job.任务ID));
    } catch (e) {
      setScheduleMsg('删除失败：' + (e.message || e));
    }
  };

  // 继续追问
  const handleFollowUp = async (overrideText) => {
    const q = (overrideText ?? followUp).trim();
    if (!q) return;
    if (!lastReportIdRef.current) {
      setError('还没有可追问的分析结果，请先完成一次分析');
      return;
    }
    setNlInput(q);
    const started = await handleGenerate(true);
    if (started) setFollowUp('');
  };

  // 阶段 45：推荐追问建议——基于当前数据字段生成 2-3 条可点击的自然语言追问，
  // 用户不知该问什么时点一下即可继续（解决"不知道怎么追问"的体验断点）。
  const followUpSuggestions = (() => {
    const list = [];
    const cat = catFields?.[0];
    const date = dateFields?.[0];
    const num = numFields?.[0];
    if (cat) list.push(`那按「${cat}」分组看看分布呢？`);
    if (date) list.push(`按「${date}」看趋势变化呢？`);
    if (num) list.push(`只看「${num}」最高的前 10 呢？`);
    // 最多展示 3 条，避免刷屏
    return list.slice(0, 3).filter(Boolean);
  })();

  return {
    // 数据/画像
    dataset, profile, fields, numFields, catFields, dateFields, textFields,
    // 表单
    nlInput, setNlInput, chartType, setChartType, generating,
    xAxis, setXAxis, yAxis, setYAxis, groupField, setGroupField,
    aggMethod, setAggMethod, filters, setFilters, topN, setTopN, compare, setCompare,
    更新筛选, 添加筛选, 删除筛选,
    agentMode, setAgentMode, selectedModel, setSelectedModel,
    error, setError, advice, setAdvice, showAdvanced, setShowAdvanced,
    // 模板/定时
    savedTemplates, setSavedTemplates, showTemplates, setShowTemplates,
    templateName, setTemplateName, savingTemplate, runningTemplateId, templateMsg,
    loadTemplates, handleSaveTemplate, handleRunTemplate, handleLoadTemplate, handleDeleteTemplate,
    schedules, scheduleCron, setScheduleCron, scheduleTplId, setScheduleTplId, scheduleMsg,
    loadSchedules, handleCreateSchedule, handleDeleteSchedule,
    // 直播
    liveSteps, liveError, liveDone, elapsed, showChartSwitch, setShowChartSwitch,
    scrollRef,
    // 追问
    followUp, setFollowUp, followUpSuggestions,
    // 动作
    handleChartSelect, handleGenerate, handleCancel, handleFollowUp,
    // 并发守卫引用（JSX 图表切换提示条直接读它判断是否可发起）
    generatingRef,
  };
}