/* =============================================================================
 * 文件：frontend/src/pages/Analysis.jsx —— 智能分析页（路由 /analysis，平台核心页面）
 * 职责：纯 JSX 渲染层（所有状态与业务逻辑已拆分到 hooks/useAnalysis.js）
 * 依赖：hooks/useAnalysis（业务逻辑）、components/LLMConfig（模型配置）、
 *        components/TraceRow（决策流步骤卡片——定义在本文件末尾）
 * ============================================================================= */
import { Zap, Sparkles, BarChart3, LineChart, PieChart, ScatterChart, Table, Layers, Loader2, Cpu, GitBranch, X, Brain, Wrench, Eye, AlertTriangle, MessageSquare, ArrowRight, Bookmark } from 'lucide-react';
import LLMConfig from '../components/LLMConfig';
import useAnalysis, { chartMap } from '../hooks/useAnalysis';

// 图表类型选择面板：id（英文键）+ 图标 + 展示名，网格渲染
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

// 快捷模板
const templates = [
  { label: '占比分布', icon: PieChart, text: '按【地区】统计【销售额】占比' },
  { label: '趋势变化', icon: LineChart, text: '按【月份】统计【销售额】趋势变化' },
  { label: '分组对比', icon: BarChart3, text: '按【地区】分组对比【销售额】平均值' },
  { label: '交叉分析', icon: GitBranch, text: '按【地区】和【岗位类型】做【销售额】交叉分析' },
];

// 可选模型下拉
const models = [
  { id: '', label: '系统默认' },
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { id: 'gpt-4o', label: 'GPT-4o' },
  { id: 'deepseek-chat', label: 'DeepSeek Chat' },
];

// 筛选操作（从 hook 导入的常量）
const 筛选操作列表 = ['等于', '不等于', '包含', '大于', '大于等于', '小于', '小于等于', '为空', '不为空'];

// ---- 主组件 ----

export default function Analysis() {
  const {
    dataset, profile, fields, numFields, catFields, dateFields, textFields,
    nlInput, setNlInput, chartType, setChartType, generating,
    xAxis, setXAxis, yAxis, setYAxis, groupField, setGroupField,
    aggMethod, setAggMethod, filters, setFilters, topN, setTopN, compare, setCompare,
    更新筛选, 添加筛选, 删除筛选,
    agentMode, setAgentMode, selectedModel, setSelectedModel,
    error, setError, advice, setAdvice, showAdvanced, setShowAdvanced,
    savedTemplates, showTemplates, setShowTemplates,
    templateName, setTemplateName, savingTemplate, runningTemplateId, templateMsg,
    loadTemplates, handleSaveTemplate, handleRunTemplate, handleLoadTemplate, handleDeleteTemplate,
    schedules, scheduleCron, setScheduleCron, scheduleTplId, setScheduleTplId, scheduleMsg,
    loadSchedules, handleCreateSchedule, handleDeleteSchedule,
    liveSteps, liveError, liveDone, elapsed, showChartSwitch, setShowChartSwitch,
    scrollRef, followUp, setFollowUp,
    handleChartSelect, handleGenerate, handleCancel, handleFollowUp, generatingRef,
  } = useAnalysis();

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-7">
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">智能分析</h1>
        <p className="text-xs text-gray-400 mt-1">用自然语言描述分析需求，AI 自动生成报表</p>
        {dataset && <p className="text-xs text-accent mt-1">当前数据集：{dataset.文件名}</p>}
        {error && (
          <div className="mt-3 px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
            <span>⚠</span><span>{error}</span>
            <button className="ml-auto text-red-400 hover:text-red-600 text-xs" onClick={() => setError('')}>✕</button>
          </div>
        )}
        {advice && (
          <div className="mt-3 px-4 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-700 flex items-center gap-2">
            <span>💡</span><span>{advice}</span>
            <button className="ml-auto text-amber-400 hover:text-amber-600 text-xs" onClick={() => setAdvice('')}>✕</button>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 rounded-t-xl">
          <textarea rows={3} className="w-full bg-transparent border-0 text-sm text-gray-700 resize-none focus:outline-none placeholder:text-gray-400 leading-relaxed"
            placeholder="输入分析需求，例如：按【地区】统计【销售额】占比…" value={nlInput} onChange={(e) => setNlInput(e.target.value)} />
        </div>
        <div className="flex items-center justify-between px-5 py-3 bg-gray-50/80 border-t border-gray-100 rounded-b-xl">
          <div className="flex items-center gap-3 flex-wrap">
            <LLMConfig />
            <div className="hidden sm:flex gap-1.5 flex-wrap">
              {templates.map((t) => (
                <span key={t.label} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-xs text-gray-500 cursor-pointer hover:bg-gray-100 hover:text-gray-700 transition-all border border-gray-200"
                  onClick={() => setNlInput(t.text)}>
                  <t.icon className="w-3.5 h-3.5 text-accent" />{t.label}
                </span>
              ))}
            </div>
          </div>
          <button disabled={generating}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all active:scale-[.98] disabled:opacity-50"
            onClick={handleGenerate}>
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            {generating ? '分析中…' : '开始分析'}
          </button>
        </div>
      </div>

      {/* 意图预览条 */}
      {nlInput.trim().length > 0 && !generating && (
        <div className="flex items-center gap-2 flex-wrap mt-3 px-4 py-2.5 rounded-xl bg-accent-soft text-xs text-accent">
          <b className="font-semibold">已自动选择</b>
          <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors"
            onClick={() => setShowAdvanced(true)} title="点击修改图表类型">
            {(chartMap[chartType] || '自动推荐')} ✎
          </span>
          {xAxis && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改 X 轴">X {xAxis} ✎</span>}
          {yAxis && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改 Y 轴">Y {yAxis} ✎</span>}
          {groupField && groupField !== '无' && <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改分组字段">分组 {groupField} ✎</span>}
          <span className="bg-white border border-accent/20 rounded-md px-2 py-1 font-medium cursor-pointer hover:border-accent/60 transition-colors" onClick={() => setShowAdvanced(true)} title="点击修改聚合方式">{aggMethod} ✎</span>
          <span className="ml-auto opacity-70">点击任意项可修改</span>
        </div>
      )}

      {/* 分析直播区 */}
      {generating && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
          <div className="lg:col-span-3 bg-white rounded-xl shadow-[var(--shadow-card)] overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
              <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" style={{ animation: 'live-pulse 1.6s infinite' }} />
              <span className="text-xs font-semibold text-gray-700">Agent 决策流</span>
              <span className="ml-auto text-[10px] px-2 py-0.5 rounded-md bg-accent-soft text-accent font-medium whitespace-nowrap">
                AI 生成 · {agentMode === 'multi' ? '多智能体' : '单 Agent'}
              </span>
              <button onClick={handleCancel} className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all">
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
            <div className="flex items-center gap-2.5 px-4 py-2.5 bg-gray-50/80 border-t border-gray-100 text-[11px] text-gray-500">
              {liveError ? (
                <span className="text-red-600 font-medium">✕ {liveError}</span>
              ) : liveDone ? (
                <span className="text-ok font-medium">✓ 分析完成，正在打开报表…</span>
              ) : (
                <>
                  <span className="flex items-end gap-[3px] h-3.5" aria-hidden>
                    {[5, 10, 7, 12, 8].map((h, i) => (
                      <span key={i} className="w-[3px] rounded-[1px] bg-accent opacity-70"
                        style={{ height: h, animation: `live-eq 0.9s ease-in-out ${i * 0.15}s infinite` }} />
                    ))}
                  </span>
                  <span>Agent 正在工作 · 已用 {elapsed}s</span>
                </>
              )}
              <span className="ml-auto font-variant-numeric">步骤 {liveSteps.length}{!liveDone && !liveError && ' · 实时更新'}</span>
            </div>
          </div>
          <div className="lg:col-span-2 bg-white rounded-xl shadow-[var(--shadow-card)] p-4 flex flex-col">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-semibold tracking-wide text-gray-400">生成中的报表</p>
              {liveDone && <span className="text-[10px] px-2 py-0.5 rounded-md bg-ok-soft text-ok font-medium">已完成</span>}
            </div>
            <div className="flex-1 min-h-[190px] mt-3 rounded-lg px-7 pb-7 flex items-end gap-4 relative overflow-hidden"
              style={{ background: 'radial-gradient(120% 100% at 50% 0%, #eef3f9 0%, #f8fafc 55%, #f1f5f9 100%)' }}>
              <div className="absolute left-7 right-7 top-5 bottom-7 flex flex-col justify-between pointer-events-none">
                {[0, 1, 2, 3].map(i => (<span key={i} className="border-t border-dashed border-accent/10" />))}
              </div>
              <span className="absolute left-1/2 -translate-x-1/2 top-3 text-[10px] tracking-widest text-gray-400">图表生成中</span>
              {[56, 72, 44, 32, 48].map((h, i) => (
                <span key={i} className="relative flex-1 rounded-t-md"
                  style={{ height: `${h}%`, background: 'linear-gradient(180deg, #4a8ac2, #0f4c81)', boxShadow: '0 6px 14px -6px rgba(15,76,129,.35)', animation: `live-grow 0.9s cubic-bezier(.22,1,.36,1) ${0.12 * i + 0.1}s both` }} />
              ))}
            </div>
            <p className="text-[11px] text-gray-400 mt-3">{liveError ? '生成失败，请检查参数后重试' : liveDone ? '决策完成，报表即将打开' : 'AI 正在根据决策流生成图表与结论…'}</p>
          </div>
        </div>
      )}

      {/* 多轮追问条 */}
      {liveDone && !generating && (
        <div className="mt-3 bg-white rounded-xl shadow-[var(--shadow-card)] px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="w-4 h-4 text-accent" />
            <span className="text-xs font-semibold text-gray-700">继续追问</span>
            <span className="text-[11px] text-gray-400">基于刚才的分析结果接着问，例如「那华南区呢？」「按月份对比呢？」</span>
          </div>
          <div className="flex items-center gap-2">
            <input value={followUp} onChange={(e) => setFollowUp(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFollowUp(); }}
              placeholder="输入追问，如：那华南区呢？按月份对比呢？"
              className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent transition-colors" />
            <button disabled={!followUp.trim()} onClick={handleFollowUp}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all disabled:opacity-40">
              <Zap className="w-3.5 h-3.5" /> 追问分析
            </button>
          </div>
        </div>
      )}

      {/* 图表切换提示条 */}
      {showChartSwitch && !generating && (
        <div className="mt-2 px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200/60 flex items-center gap-2 text-xs text-amber-700">
          <span>已使用当前图表生成，如需查看各分类占比可一键切换：</span>
          <button onClick={() => { if (!generatingRef.current) handleGenerate(false, 'pie'); }} className="px-2 py-1 rounded-md bg-white border border-amber-200 text-amber-600 hover:bg-amber-100 font-medium transition-all">饼图</button>
          <button onClick={() => { if (!generatingRef.current) handleGenerate(false, 'bar'); }} className="px-2 py-1 rounded-md bg-white border border-amber-200 text-amber-600 hover:bg-amber-100 font-medium transition-all">柱状图</button>
          <button onClick={() => setShowChartSwitch(false)} className="ml-1 text-amber-400 hover:text-amber-600 transition-colors">×</button>
        </div>
      )}

      {/* 高级选项开关 */}
      <div className="flex items-center justify-between mt-4">
        <button className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors" onClick={() => setShowAdvanced(!showAdvanced)}>
          <span className={`inline-block transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▶</span>
          高级选项{showAdvanced ? '（点击收起）' : ''}
        </button>
        {!showAdvanced && <span className="text-[11px] text-gray-500">图表、字段、Agent 模式等高级配置</span>}
      </div>

      {/* 高级面板 */}
      {showAdvanced && (<>
        {/* 模板 */}
        <div className="mt-4 border border-gray-200 rounded-xl p-3 bg-gray-50/60">
          <div className="flex items-center justify-between">
            <button className="flex items-center gap-1 text-xs font-semibold text-gray-600 hover:text-accent transition-colors"
              onClick={() => { setShowTemplates(!showTemplates); if (!showTemplates) { if (savedTemplates.length === 0) loadTemplates(); if (schedules.length === 0) loadSchedules(); } }}>
              <Bookmark className="w-3.5 h-3.5" /> 模板{showTemplates ? '（收起）' : ''}
            </button>
            <span className="text-[11px] text-gray-400">收藏分析配置，下次一键复用 / 定时执行</span>
          </div>
          {templateMsg && <p className="text-[11px] mt-2 text-amber-600">{templateMsg}</p>}
          {showTemplates && (
            <div className="mt-3 space-y-2">
              <div className="flex items-center gap-2">
                <input className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:border-accent"
                  placeholder="模板名称，如：每周销售周报" value={templateName} onChange={(e) => setTemplateName(e.target.value)} maxLength={50} />
                <button onClick={handleSaveTemplate} disabled={savingTemplate}
                  className="px-3 py-1.5 rounded-lg text-xs bg-accent text-white hover:opacity-90 transition-all disabled:opacity-50">
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
                      <button className="text-[11px] text-accent hover:underline" onClick={() => handleLoadTemplate(tpl)}>加载</button>
                      <button className="text-[11px] text-emerald-600 hover:underline disabled:opacity-50"
                        disabled={runningTemplateId === tpl.模板ID} onClick={() => handleRunTemplate(tpl)}>
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

        {/* 定时任务 */}
        <div className="mt-3 border-t border-gray-100 pt-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-500">定时执行 <span className="text-[10px] text-gray-400 font-normal">（模板 + cron，到点自动生成到报表历史）</span></p>
            {schedules.length > 0 && <button className="text-[11px] text-accent hover:underline" onClick={() => {}}>收起</button>}
          </div>
          {scheduleMsg && <p className="text-[11px] mb-2 text-amber-600">{scheduleMsg}</p>}
          <div className="flex items-center gap-2">
            <select className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:border-accent" value={scheduleTplId} onChange={(e) => setScheduleTplId(e.target.value)}>
              <option value="">选择模板</option>
              {savedTemplates.map((tpl) => <option key={tpl.模板ID} value={tpl.模板ID}>{tpl.名称}</option>)}
            </select>
            <input className="w-40 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:border-accent"
              placeholder="cron 如：0 9 * * 1" value={scheduleCron} onChange={(e) => setScheduleCron(e.target.value)}
              title="5 字段 cron：分 时 日 月 周（0=周日）。示例：0 9 * * 1 = 每周一 09:00" />
            <div className="flex gap-1">
              {[['每天 09:00', '0 9 * * *'], ['每 30 分钟', '*/30 * * * *'], ['每周一 09:00', '0 9 * * 1'], ['每月 1 日 09:00', '0 9 1 * *']].map(([label, expr]) => (
                <button key={expr} className={`px-2 py-1 rounded text-[10px] transition-all ${scheduleCron === expr ? 'bg-accent text-white' : 'bg-gray-100 text-gray-500 hover:bg-accent-soft hover:text-accent'}`}
                  onClick={() => setScheduleCron(expr)} title={`填入 ${expr}`}>{label}</button>
              ))}
            </div>
            <button onClick={handleCreateSchedule} className="px-3 py-1.5 rounded-lg text-xs bg-accent text-white hover:opacity-90 transition-all shrink-0">创建</button>
          </div>
          {schedules.length > 0 && (
            <div className="space-y-1.5 mt-2 max-h-40 overflow-y-auto">
              {schedules.map((job) => (
                <div key={job.任务ID} className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5">
                  <span className="flex-1 text-xs text-gray-700 truncate" title={job.cron}>
                    cron <code className="text-accent">{job.cron}</code>
                    {job.下次执行 && <span className="text-gray-400 ml-2">下次：{new Date(job.下次执行).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>}
                    {job.上次状态 && <span className={`ml-2 ${job.上次状态 === '成功' ? 'text-emerald-500' : 'text-red-400'}`}>{job.上次状态 === '成功' ? '上次执行成功' : `上次失败：${String(job.上次状态).slice(0, 40)}${String(job.上次状态).length > 40 ? '…' : ''}`}</span>}
                  </span>
                  <button className="text-[11px] text-red-400 hover:text-red-600 hover:underline" onClick={() => handleDeleteSchedule(job)}>删除</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 模型 + Agent 模式 */}
        <div className="flex items-center gap-4 mt-3">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-gray-400" />
            <select className="border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
            <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${agentMode === 'single' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('single')}>单 Agent</button>
            <button className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1 ${agentMode === 'multi' ? 'bg-white text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} onClick={() => setAgentMode('multi')}>
              <GitBranch className="w-3 h-3" /> 多智能体
            </button>
          </div>
          {agentMode === 'multi' && <span className="text-[11px] text-accent">Supervisor + 3 个 Worker Agent</span>}
        </div>

        {/* 图表类型 */}
        <div className="mt-6">
          <p className="text-xs font-semibold text-gray-500 mb-3">图表类型</p>
          <div className="grid grid-cols-4 gap-2">
            {chartTypes.map((ct) => {
              const Icon = ct.icon; const active = chartType === ct.id;
              return (
                <div key={ct.id}
                  className={`rounded-xl p-3 text-center cursor-pointer transition-all ${active ? 'border-2 border-accent bg-accent-soft' : 'border border-gray-200 hover:border-accent/60 hover:bg-gray-50'}`}
                  onClick={() => handleChartSelect(ct.id)}>
                  <Icon className={`w-6 h-6 mx-auto mb-1 ${active ? 'text-accent' : 'text-gray-400'}`} />
                  <p className={`text-xs ${active ? 'text-accent font-medium' : 'text-gray-500'}`}>{ct.label}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* 字段配置 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
          <div>
            <label className="text-xs text-gray-400 mb-1.5 block">X 轴</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={xAxis} onChange={(e) => setXAxis(e.target.value)}>
              <option value="">🤖 自动推荐</option>
              {fields.map((f) => <option key={f} value={f}>{textFields.includes(f) ? `✎ ${f}` : f}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1.5 block">Y 轴</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={yAxis} onChange={(e) => setYAxis(e.target.value)}>
              <option value="">🤖 自动推荐</option>
              {numFields.map((f) => <option key={f}>{f}</option>)}
              {numFields.length === 0 && fields.map((f) => <option key={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1.5 block">分组字段</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={groupField} onChange={(e) => setGroupField(e.target.value)}>
              <option value="">🤖 自动推荐</option>
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
          <div>
            <label className="text-xs text-gray-400 mb-1.5 block">对比 <span className="text-[10px]">（需日期 X 轴）</span></label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm bg-gray-50 focus:outline-none focus:border-accent" value={compare} onChange={(e) => setCompare(e.target.value)}>
              <option value="">无</option>
              <option value="环比">环比（与上期比）</option>
              <option value="同比">同比（与去年同期比）</option>
            </select>
          </div>
        </div>

        {/* 筛选条件 + TopN */}
        <div className="mt-5 border-t border-gray-100 pt-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-500">筛选条件 <span className="text-[10px] text-gray-400 font-normal">（多条同时满足，也可在需求里说"只看华东区"）</span></p>
            {filters.length > 0 && <button className="text-[11px] text-accent hover:underline" onClick={() => setFilters([])}>清空</button>}
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
                <input className="flex-1 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent" value={f.值 || ''}
                  onChange={(e) => 更新筛选(i, '值', e.target.value)} placeholder={['为空', '不为空'].includes(f.操作) ? '无需填值' : '筛选值'}
                  disabled={['为空', '不为空'].includes(f.操作)} />
                <button className="text-gray-400 hover:text-red-500 transition-colors" onClick={() => 删除筛选(i)}>✕</button>
              </div>
            ))}
            {filters.length < 10 && <button className="text-[11px] text-accent hover:underline" onClick={添加筛选}>+ 添加条件</button>}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <label className="text-xs text-gray-400 shrink-0">Top N</label>
            <input type="number" min="1" max="200" className="w-24 border border-gray-200 rounded-lg px-2.5 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent" value={topN} onChange={(e) => setTopN(e.target.value)} placeholder="如 10" title="只保留数值最大的前 N 行" />
            <span className="text-[11px] text-gray-400">只保留数值最大的前 N 行（如"销量 Top 10"）</span>
          </div>
        </div>
      </>)}
    </div>
  );
}

// ---- 决策流步骤卡片 ----
const STEP_ICON = { 'LLM推理': Brain, '工具调用': Wrench, '观察': Eye, '失败': AlertTriangle };

function TraceRow({ step }) {
  const r = step.record || {};
  const kind = step.status === 'active' ? 'active' : (r['状态'] === '失败' ? 'failed' : 'done');
  const Icon = STEP_ICON[r['步骤']] || Zap;
  const title = r['步骤'] === '工具调用' ? `工具调用 · ${r['工具名'] || '未知工具'}` : (r['步骤'] || '步骤');
  const desc = r['说明'] || r['理由'] || r['prompt摘要'] || r['工具输出摘要'] || (r['步骤'] === '工具调用' ? '执行数据分析工具' : '');
  const meta = r['耗时_ms'] != null ? `${(r['耗时_ms'] / 1000).toFixed(1)}s${r['token']?.total_tokens ? ` · ${r['token'].total_tokens} tok` : ''}` : '—';
  const statusLabel = kind === 'active' ? '进行中' : (kind === 'failed' ? '失败' : '完成');

  return (
    <div className={`relative flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${kind === 'active' ? 'bg-accent-soft' : ''}`}>
      {kind === 'active' && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-[3px]" style={{ background: 'linear-gradient(180deg, #4a8ac2, #0f4c81)' }} />}
      <span className={`w-7 h-7 rounded-lg flex items-center justify-center text-[13px] shrink-0 ${kind === 'active' ? 'bg-accent text-white' : kind === 'failed' ? 'bg-red-50 text-red-500' : 'bg-ok-soft text-ok'}`} style={kind === 'active' ? { animation: 'live-blink 1.2s infinite' } : undefined}>
        <Icon className="w-4 h-4" />
      </span>
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-semibold truncate ${kind === 'failed' ? 'text-red-600' : 'text-gray-700'}`}>{title}</p>
        {desc && <p className="text-[11px] text-gray-400 mt-0.5 truncate">{desc}</p>}
      </div>
      <span className="text-[10px] text-gray-400 font-variant-numeric shrink-0">{meta}</span>
      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${kind === 'active' ? 'bg-amber-soft text-amber' : kind === 'failed' ? 'bg-red-50 text-red-500' : 'bg-ok-soft text-ok'}`}>{statusLabel}</span>
    </div>
  );
}
