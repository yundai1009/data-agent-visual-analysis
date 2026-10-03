// Analysis 智能分析页组件测试（阶段 51）：mock useAnalysis Hook + api，
// 验证输入绑定 / 生成触发 / 错误与决策流渲染 / 追问建议 / 图表一键切换。
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
    liveSteps: [], liveError: '', liveDone: null, elapsed: 0,
    showChartSwitch: false, setShowChartSwitch: vi.fn(), scrollRef: { current: null },
    followUp: '', setFollowUp: vi.fn(), followUpSuggestions: [],
    handleChartSelect: vi.fn(), handleGenerate: vi.fn(),
    handleCancel: vi.fn(), handleFollowUp: vi.fn(),
    generatingRef: { current: false },
  },
}));

vi.mock('../hooks/useAnalysis', () => ({
  default: () => mockState.state,
  // 页面只用 chartMap 做图表切换条文案映射；此处给测试所需的子集
  chartMap: { auto: '自动推荐', bar: '柱状图', line: '折线图', pie: '饼图' },
}));

import Analysis from './Analysis';

function renderPage() {
  return render(<Analysis />);
}

describe('Analysis 智能分析页', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(mockState.state, {
      generating: false,
      error: '',
      advice: '',
      liveSteps: [],
      liveError: '',
      liveDone: null,
      showChartSwitch: false,
      followUpSuggestions: [],
      nlInput: '',
    });
  });

  it('渲染标题、输入框与开始分析按钮', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /智能分析/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入分析需求，例如：按【地区】统计【销售额】占比…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /开始分析/ })).toBeInTheDocument();
    expect(screen.getByText(/当前数据集：销售\.csv/)).toBeInTheDocument();
  });

  it('输入分析需求 → 调用 setNlInput', () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('输入分析需求，例如：按【地区】统计【销售额】占比…'), {
      target: { value: '帮我按地区看销售额' },
    });
    expect(mockState.state.setNlInput).toHaveBeenCalledWith('帮我按地区看销售额');
  });

  it('点击开始分析 → 触发 handleGenerate', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /开始分析/ }));
    expect(mockState.state.handleGenerate).toHaveBeenCalled();
  });

  it('渲染错误横幅（如配额 429 消息透传）', () => {
    mockState.state.error = '已达今日分析次数上限（200 / 200 次），请明天再试，或使用自己的 API Key（BYOK）';
    renderPage();
    expect(screen.getByText(/已达今日分析次数上限/)).toBeInTheDocument();
  });

  it('渲染决策流步骤卡片', () => {
    mockState.state.generating = true; // 分析直播区仅在生成中渲染
    mockState.state.liveSteps = [{ record: { 步骤: '工具调用', 工具名: '获取数据画像' }, status: 'active' }];
    renderPage();
    expect(screen.getByText('工具调用 · 获取数据画像')).toBeInTheDocument();
  });

  it('有结果后渲染追问条，点击推荐追问 → handleFollowUp(s)', () => {
    mockState.state.liveDone = { 报表ID: 'r1', 标题: '地区销售构成' };
    const suggestion = '那按「地区」分组看看分布呢？';
    mockState.state.followUpSuggestions = [suggestion];
    renderPage();
    expect(screen.getByText('继续追问')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: suggestion }));
    expect(mockState.state.handleFollowUp).toHaveBeenCalledWith(suggestion);
  });

  it('图表切换提示条：点饼图 → handleGenerate(false, "pie")', () => {
    mockState.state.showChartSwitch = true;
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '饼图' }));
    expect(mockState.state.handleGenerate).toHaveBeenCalledWith(false, 'pie');
  });
});