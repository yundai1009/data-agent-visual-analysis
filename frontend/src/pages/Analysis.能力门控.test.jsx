// 阶段八十四 · C：基础版 / 专业版 能力门控（第 10 项「用户反应基础和专业没什么区别」）。
// 锁住：能力表 模板 / 定时任务 在 basic=false、pro=true，页面必须跟表走——
// 基础版不显示「存为模板」快捷入口、高级面板里的「模板区」与「定时执行」区块；
// 切到专业版（?mode=pro）后全部回来。
// 既有 Analysis.test.jsx 的模板用例跑在 pro（beforeEach 已设 /?mode=pro），不与此冲突；
// 这里只新增「基础版确实收起」「专业版确实出现」两条，规则只改 utils/capabilities.js 一处。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../api', () => ({
  fetchLLMProviders: vi.fn().mockResolvedValue({ providers: [] }),
  getAccountLLMKey: vi.fn().mockResolvedValue(''),
  saveAccountLLMKey: vi.fn().mockResolvedValue({}),
  clearAccountLLMKey: vi.fn().mockResolvedValue({}),
  saveCustomProvider: vi.fn().mockResolvedValue({}),
  deleteCustomProvider: vi.fn().mockResolvedValue({}),
  testCustomProvider: vi.fn().mockResolvedValue({ ok: true }),
}));

const mockState = vi.hoisted(() => ({
  state: {
    dataset: { 数据集ID: 'd1', 文件名: '销售.csv' },
    profile: {}, fields: [], numFields: [], catFields: [], dateFields: [], textFields: [],
    nlInput: '', setNlInput: vi.fn(), chartType: 'auto', setChartType: vi.fn(),
    generating: false, xAxis: '', setXAxis: vi.fn(), yAxis: '', setYAxis: vi.fn(),
    groupField: '', setGroupField: vi.fn(), aggMethod: '求和', setAggMethod: vi.fn(),
    filters: [], setFilters: vi.fn(), topN: '', setTopN: vi.fn(), compare: '', setCompare: vi.fn(),
    更新筛选: vi.fn(), 添加筛选: vi.fn(), 删除筛选: vi.fn(),
    agentMode: 'single', setAgentMode: vi.fn(), selectedModel: '', setSelectedModel: vi.fn(),
    error: '', setError: vi.fn(), advice: '', setAdvice: vi.fn(),
    showAdvanced: false, setShowAdvanced: vi.fn(),
    savedTemplates: [], showTemplates: false, setShowTemplates: vi.fn(),
    templateName: '', setTemplateName: vi.fn(), savingTemplate: false,
    runningTemplateId: '', templateMsg: '',
    loadTemplates: vi.fn(), handleSaveTemplate: vi.fn(), handleRunTemplate: vi.fn(),
    handleLoadTemplate: vi.fn(), handleDeleteTemplate: vi.fn(),
    schedules: [], scheduleCron: '', setScheduleCron: vi.fn(),
    scheduleTplId: '', setScheduleTplId: vi.fn(), scheduleMsg: '',
    loadSchedules: vi.fn(), handleCreateSchedule: vi.fn(), handleDeleteSchedule: vi.fn(),
    liveSteps: [], liveError: '', liveDone: { 报表ID: 'r1', 标题: '地区销售构成' }, elapsed: 0,
    showChartSwitch: false, setShowChartSwitch: vi.fn(), scrollRef: { current: null },
    followUp: '', setFollowUp: vi.fn(), followUpSuggestions: [],
    handleChartSelect: vi.fn(), handleGenerate: vi.fn(),
    handleCancel: vi.fn(), handleFollowUp: vi.fn(),
    generatingRef: { current: false },
  },
}));

vi.mock('../hooks/useAnalysis', () => ({
  default: () => mockState.state,
  chartMap: { auto: '自动推荐', bar: '柱状图', line: '折线图', pie: '饼图' },
}));

const navMock = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => navMock.navigate }));

import Analysis from './Analysis';

function renderPage() {
  return render(<Analysis />);
}

describe('阶段八十四 · C 能力门控（基础版收起专业控件）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 不给 ?mode=pro、清 localStorage → 取模式() 落到 默认模式 = 基础版
    window.history.replaceState({}, '', '/');
    localStorage.clear();
    Object.assign(mockState.state, {
      generating: false, error: '', advice: '', liveSteps: [], liveError: '',
      liveDone: { 报表ID: 'r1', 标题: '地区销售构成' }, dataset: { 数据集ID: 'd1', 文件名: '销售.csv' },
      fields: [], catFields: [], numFields: [], dateFields: [], textFields: [],
      showAdvanced: true, // 打开高级面板，让模板区/定时区能渲染（若未被门控收起）
      savedTemplates: [{ 模板ID: 't1', 名称: '每周周报' }], schedules: [],
    });
  });

  it('基础版：完成栏不出现「存为模板」快捷入口（模板 basic:false）', () => {
    renderPage();
    expect(screen.queryByRole('button', { name: /存为模板/ })).not.toBeInTheDocument();
  });

  it('基础版：高级面板打开后也不出现「模板」区块与「定时执行」区块', () => {
    renderPage();
    expect(screen.queryByText('定时执行')).not.toBeInTheDocument();
    // 模板区标题文案不出现（区块被门控整段收起）
    expect(screen.queryByText('收藏分析配置，下次一键复用 / 定时执行')).not.toBeInTheDocument();
  });

  it('基础版主链路不受影响：开始分析 / 可用字段引导仍在', () => {
    renderPage();
    expect(screen.getByRole('button', { name: /开始分析/ })).toBeInTheDocument();
  });

  it('专业版（?mode=pro）：「存为模板」快捷入口出现', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderPage();
    expect(screen.getByRole('button', { name: /存为模板/ })).toBeInTheDocument();
  });

  it('专业版（?mode=pro）：高级面板出现「定时执行」区块', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderPage();
    expect(screen.getByText('定时执行')).toBeInTheDocument();
    expect(screen.getByText('收藏分析配置，下次一键复用 / 定时执行')).toBeInTheDocument();
  });

  it('专业版：点击「存为模板」→ 展开模板区（与既有模板用例行为一致）', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /存为模板/ }));
    expect(mockState.state.setShowAdvanced).toHaveBeenCalledWith(true);
    expect(mockState.state.setShowTemplates).toHaveBeenCalledWith(true);
  });
});
