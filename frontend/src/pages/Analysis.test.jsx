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

const navMock = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => navMock.navigate }));

import Analysis from './Analysis';
import { fetchLLMProviders } from '../api';

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
      // 重置数据集/字段（防用例间状态残留）
      dataset: { 数据集ID: 'd1', 文件名: '销售.csv' },
      fields: [], catFields: [], numFields: [], dateFields: [], textFields: [],
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

  it('点击开始分析 → handleGenerate 必须是 isFollowUp=false（回归：MouseEvent 当参数会丢弃高级设置并串成追问）', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /开始分析/ }));
    expect(mockState.state.handleGenerate).toHaveBeenCalled();
    // 回归锁定：不能把点击事件对象当 isFollowUp 传下去（真值 → 追问分支）
    expect(mockState.state.handleGenerate).toHaveBeenCalledWith(false);
  });

  it('渲染错误横幅（如配额 429 消息透传）', () => {
    mockState.state.error = '已达今日分析次数上限（200 / 200 次），请明天再试，或使用自己的 API Key（BYOK）';
    renderPage();
    expect(screen.getByText(/已达今日分析次数上限/)).toBeInTheDocument();
  });

  // ---- Fix 1（阶段54-7）：SSE error 持久可见（live 面板消失后错误横幅仍在）----
  it('Fix1 live 面板卸载后（generating=false），持久错误横幅仍显示', () => {
    mockState.state.generating = false; // finally 已把 generating 复位 → 直播面板卸载
    mockState.state.error = 'cannot insert SepalLength, already exists';
    renderPage();
    // 回归锁定：错误不能只存在于 live 面板内（面板没了错误也消失 → 静默失败）
    expect(screen.getByText(/cannot insert SepalLength/)).toBeInTheDocument();
    expect(screen.queryByText('Agent 决策流')).not.toBeInTheDocument();
  });

  it('Fix1 生成中 SSE 失败：live 面板与持久横幅同时显示错误', () => {
    mockState.state.generating = true;
    mockState.state.error = 'cannot insert SepalLength, already exists';
    mockState.state.liveError = 'cannot insert SepalLength, already exists';
    renderPage();
    expect(screen.getByText('Agent 决策流')).toBeInTheDocument();
    // 同一文案同时出现在：顶部持久错误横幅 + live 面板底部
    expect(screen.getAllByText(/cannot insert SepalLength/).length).toBeGreaterThanOrEqual(2);
  });

  // ---- Fix 2（阶段54-7）：追问按钮 onClick 传事件对象崩溃 ----
  it('Fix2 点击「追问分析」→ handleFollowUp 无参调用（不把 MouseEvent 当 overrideText）', () => {
    mockState.state.liveDone = { 报表ID: 'r1', 标题: '地区销售构成' };
    mockState.state.followUp = '那华南区呢？';
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /追问分析/ }));
    expect(mockState.state.handleFollowUp).toHaveBeenCalledTimes(1);
    // 回归锁定：直接传事件对象 → (overrideText ?? followUp).trim is not a function
    expect(mockState.state.handleFollowUp).toHaveBeenCalledWith();
  });

  it('Fix2 追问输入为空时按钮禁用（不触发请求）', () => {
    mockState.state.liveDone = { 报表ID: 'r1', 标题: 'x' };
    mockState.state.followUp = '';
    renderPage();
    const btn = screen.getByRole('button', { name: /追问分析/ });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(mockState.state.handleFollowUp).not.toHaveBeenCalled();
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

  it('生成完成后显示"查看报表"入口并跳转（回归：原文案谎称"报表即将打开"且无入口）', () => {
    navMock.navigate.mockClear();
    mockState.state.liveDone = { 报表ID: 'r-abc', 标题: '某报表' };
    renderPage();
    const btn = screen.getByRole('button', { name: '查看报表' });
    expect(btn).toBeInTheDocument();
    // 不再出现误导文案
    expect(screen.queryByText('报表即将打开')).not.toBeInTheDocument();
    fireEvent.click(btn);
    expect(navMock.navigate).toHaveBeenCalledWith('/report/r-abc');
  });

  it('完成栏"存为模板"快捷入口：一键展开模板区（用户找不到模板保存入口的修复）', () => {
    mockState.state.liveDone = { 报表ID: 'r-1', 标题: '地区销售构成' };
    mockState.state.savedTemplates = [];
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /存为模板/ }));
    expect(mockState.state.setShowAdvanced).toHaveBeenCalledWith(true);
    expect(mockState.state.setShowTemplates).toHaveBeenCalledWith(true);
    // 模板列表为空时按需加载
    expect(mockState.state.loadTemplates).toHaveBeenCalled();
  });

  it('完成栏"存为模板"在模板列表非空时不重复加载', () => {
    mockState.state.liveDone = { 报表ID: 'r-1', 标题: 'x' };
    mockState.state.savedTemplates = [{ 模板ID: 't1', 名称: '每周周报' }];
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /存为模板/ }));
    expect(mockState.state.loadTemplates).not.toHaveBeenCalled();
    expect(mockState.state.setShowTemplates).toHaveBeenCalledWith(true);
  });

  it('未完成分析时不显示"存为模板"快捷入口', () => {
    mockState.state.liveDone = null;
    renderPage();
    expect(screen.queryByRole('button', { name: /存为模板/ })).not.toBeInTheDocument();
  });

  it('多智能体模式说明用用户语言，不暴露 Supervisor/Worker Agent 术语（B6）', () => {
    mockState.state.showAdvanced = true; // 该区在"高级选项"折叠面板内
    mockState.state.agentMode = 'multi';
    renderPage();
    expect(screen.getByText(/多智能体协同：/)).toBeInTheDocument();
    expect(screen.queryByText(/Supervisor/)).not.toBeInTheDocument();
    // 说明要讲清"什么时候用、代价是什么"
    expect(screen.getByText(/耗时略长/)).toBeInTheDocument();
  });

  it('单 Agent 模式也有悬浮说明（默认模式用户同样需要知道差异）', () => {
    mockState.state.showAdvanced = true;
    mockState.state.agentMode = 'single';
    renderPage();
    const btn = screen.getByTitle(/单 Agent：一个 AI/);
    expect(btn.getAttribute('title')).toMatch(/快/);
  });

  // ---- 阶段 53 · B8：字段加入分析引导 ----
  it('B8 输入框下方展示本数据集的可用字段（用户不知道自己能用什么字段）', () => {
    Object.assign(mockState.state, {
      fields: ['地区', '销售额', '月份', '评论'],
      catFields: ['地区'], numFields: ['销售额'], dateFields: ['月份'], textFields: ['评论'],
    });
    renderPage();
    expect(screen.getByText('可用字段')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '销售额' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '月份' })).toBeInTheDocument();
  });

  it('B8 点击字段 chip → 需求框插入【字段名】（mock 下按当前输入追加）', () => {
    Object.assign(mockState.state, {
      fields: ['地区', '销售额'], catFields: ['地区'], numFields: ['销售额'], dateFields: [], textFields: [],
      nlInput: '按',
    });
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '地区' }));
    expect(mockState.state.setNlInput).toHaveBeenLastCalledWith('按【地区】');
    fireEvent.click(screen.getByRole('button', { name: '销售额' }));
    // setNlInput 是 mock，state.nlInput 不更新，因此第二次基于同一 mock 值追加
    expect(mockState.state.setNlInput).toHaveBeenLastCalledWith('按【销售额】');
  });

  it('B8 空输入时点字段 → 需求框直接填【字段名】', () => {
    Object.assign(mockState.state, {
      fields: ['地区'], catFields: ['地区'], numFields: [], dateFields: [], textFields: [], nlInput: '',
    });
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '地区' }));
    expect(mockState.state.setNlInput).toHaveBeenCalledWith('【地区】');
  });

  it('B8 无数据集时不展示字段引导', () => {
    Object.assign(mockState.state, {
      dataset: null, fields: [], catFields: [], numFields: [], dateFields: [], textFields: [],
    });
    renderPage();
    expect(screen.queryByText('可用字段')).not.toBeInTheDocument();
  });

  it('B8 字段过多时折叠并提供展开入口', () => {
    Object.assign(mockState.state, {
      fields: Array.from({ length: 20 }, (_, i) => `字段${i}`),
      catFields: [], numFields: [], dateFields: [], textFields: [],
    });
    renderPage();
    expect(screen.getByRole('button', { name: '展开全部 20 个字段' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '字段15' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '展开全部 20 个字段' }));
    expect(screen.getByRole('button', { name: '字段15' })).toBeInTheDocument();
  });
});

// ---- 阶段七十四 · A3：模型下拉读后端活的 provider 配置 ----
// 用户反馈「LLM 模型配置列表缺少最新模型」：页面里原来写死 4 个 id，
// 而后端 config/providers.toml 有 17 家 provider、上百个模型，
// 且 GET /auth/llm-providers 早就能下发。这三条锁住「用活的、失败能降级」。
describe('Analysis 模型下拉（阶段七十四 A3）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 注意：必须用 mockResolvedValue 而不是 mockResolvedValueOnce。
    // StrictMode 下 effect 会 mount→unmount→mount 跑两次，组件里用 alive 标志
    // 丢弃第一次的结果，于是会发第二次请求——once 队列在第一次就被吃光，
    // 第二次拿到默认值，下拉看起来永远是空的（这个坑真踩过）。
    vi.mocked(fetchLLMProviders).mockResolvedValue({ providers: [] });
    Object.assign(mockState.state, {
      dataset: { 数据集ID: 'd1', 文件名: '销售.csv' },
      selectedModel: '', setSelectedModel: vi.fn(),
    });
  });

  it('按 provider 分组渲染后端下发的模型，默认模型标注「（默认）」', async () => {
    vi.mocked(fetchLLMProviders).mockResolvedValue({
      providers: [
        { id: 'zhipu', label: '智谱', models: ['glm-4-flash', 'glm-4-plus'], default: 'glm-4-flash' },
        { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat'], default: 'deepseek-chat' },
      ],
    });
    renderPage();
    // 异步拉接口 → 用 findBy 等条件成立，不等固定毫秒
    expect(await screen.findByRole('option', { name: 'glm-4-flash（默认）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'glm-4-plus' })).toBeInTheDocument();
    expect(screen.getAllByRole('group', { name: '智谱' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('group', { name: 'DeepSeek' }).length).toBeGreaterThan(0);
  });

  it('接口挂了 → 回落到内置静态清单，不出现空下拉', async () => {
    vi.mocked(fetchLLMProviders).mockRejectedValue(new Error('network down'));
    renderPage();
    // 静态清单里一定有这两项；接口失败不应把下拉变成空的
    expect(await screen.findByRole('option', { name: 'GPT-4o' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'DeepSeek Chat' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '系统默认' })).toBeInTheDocument();
  });

  it('选中的模型写回 selectedModel（模型名直接透传给后端）', async () => {
    vi.mocked(fetchLLMProviders).mockResolvedValue({
      providers: [{ id: 'zhipu', label: '智谱', models: ['glm-4-plus'], default: 'glm-4-plus' }],
    });
    renderPage();
    const 选项 = await screen.findByRole('option', { name: 'glm-4-plus（默认）' });
    const 下拉 = 选项.closest('select');
    fireEvent.change(下拉, { target: { value: 'glm-4-plus' } });
    expect(mockState.state.setSelectedModel).toHaveBeenCalledWith('glm-4-plus');
  });
});