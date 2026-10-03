// useAnalysis 业务逻辑 Hook 测试（阶段 51）：mock API 层与 AppContext，
// 覆盖生成主流程 / 校验拦截 / 追问 / 模板 / 错误文案 / 追问建议。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import useAnalysis from './useAnalysis';

// vi.hoisted：mock 工厂与测试体共享的可变上下文（dataset 可切换 null 测无数据分支）
const mockCtx = vi.hoisted(() => {
  const baseDataset = {
    数据集ID: 'd1',
    数据画像: {
      字段列表: ['月份', '地区', '销售额', '订单数'],
      数值字段: ['销售额', '订单数'],
      分类字段: ['地区'],
      日期字段: ['月份'],
      文本字段: [],
    },
  };
  return {
    baseDataset,
    dataset: baseDataset,
    gen: vi.fn(),
    listTemplates: vi.fn().mockResolvedValue({ 模板列表: [] }),
    saveTemplate: vi.fn().mockResolvedValue({}),
    deleteTemplate: vi.fn().mockResolvedValue({}),
    runTemplate: vi.fn().mockResolvedValue({ 报表ID: 'r9' }),
    listSchedules: vi.fn().mockResolvedValue({ 任务列表: [] }),
    createSchedule: vi.fn().mockResolvedValue({}),
    deleteSchedule: vi.fn().mockResolvedValue({}),
  };
});

vi.mock('../api', () => ({
  generateReportStream: (payload, opts) => mockCtx.gen(payload, opts),
  listTemplates: (...a) => mockCtx.listTemplates(...a),
  saveTemplate: (...a) => mockCtx.saveTemplate(...a),
  deleteTemplate: (...a) => mockCtx.deleteTemplate(...a),
  runTemplate: (...a) => mockCtx.runTemplate(...a),
  listSchedules: (...a) => mockCtx.listSchedules(...a),
  createSchedule: (...a) => mockCtx.createSchedule(...a),
  deleteSchedule: (...a) => mockCtx.deleteSchedule(...a),
}));

vi.mock('../AppContext', () => ({
  useApp: () => ({ dataset: mockCtx.dataset }),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => mockNavigate };
});

function wrapper({ children }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

describe('useAnalysis 智能分析 Hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCtx.dataset = { ...mockCtx.baseDataset };
  });

  it('初始状态：空表单、自动推荐、非生成中', () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    expect(result.current.nlInput).toBe('');
    expect(result.current.chartType).toBe('auto');
    expect(result.current.generating).toBe(false);
    expect(result.current.filters).toEqual([]);
  });

  it('handleGenerate 成功：SSE 事件驱动 → liveDone 落地、generating 复位', async () => {
    mockCtx.gen.mockImplementation(async (_payload, opts) => {
      opts.onEvent({ type: 'step', data: { 步骤: '获取数据画像' } });
      opts.onEvent({ type: 'done', 报表ID: 'r1', 标题: '地区销售构成' });
    });
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => result.current.setNlInput('帮我按地区看销售额'));
    await act(async () => {
      await result.current.handleGenerate();
    });
    expect(mockCtx.gen).toHaveBeenCalledTimes(1);
    expect(mockCtx.gen).toHaveBeenCalledWith(
      expect.objectContaining({ 分析需求: '帮我按地区看销售额' }),
      expect.anything()
    );
    expect(result.current.liveSteps).toHaveLength(1); // 1 条 step 事件，done 只改状态不追加
    expect(result.current.liveDone).toEqual({ 报表ID: 'r1', 标题: '地区销售构成' });
    expect(result.current.generating).toBe(false);
  });

  it('handleGenerate 无数据集：报错并跳转数据管理页', async () => {
    mockCtx.dataset = null;
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    await act(async () => {
      await result.current.handleGenerate();
    });
    expect(result.current.error).toBe('请先在数据管理页面上传数据');
    expect(mockNavigate).toHaveBeenCalledWith('/data');
    expect(mockCtx.gen).not.toHaveBeenCalled();
  });

  it('handleGenerate 字段校验失败：不发请求', async () => {
    // 空画像 → 自动预填也拿不到字段 → boxplot（needsY）校验失败
    mockCtx.dataset = { 数据集ID: 'd1', 数据画像: { 字段列表: [], 数值字段: [], 分类字段: [], 日期字段: [], 文本字段: [] } };
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => result.current.setChartType('boxplot')); // needsY 类型，未填 X/Y 应校验失败
    await act(async () => {
      await result.current.handleGenerate();
    });
    expect(result.current.error).toBeTruthy();
    expect(mockCtx.gen).not.toHaveBeenCalled();
  });

  it('handleFollowUp 无前序结果：提示先完成分析', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => result.current.setFollowUp('那华南区呢？'));
    await act(async () => {
      await result.current.handleFollowUp();
    });
    expect(result.current.error).toBe('还没有可追问的分析结果，请先完成一次分析');
    expect(mockCtx.gen).not.toHaveBeenCalled();
  });

  it('handleSaveTemplate 未完成分析：提示先完成一次分析', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => result.current.setTemplateName('周报模板'));
    await act(async () => {
      await result.current.handleSaveTemplate();
    });
    expect(result.current.templateMsg).toBe('请先完成一次分析（或直接点生成），再保存为模板');
    expect(mockCtx.saveTemplate).not.toHaveBeenCalled();
  });

  it('生成失败（断网）：展示后端不可用文案', async () => {
    mockCtx.gen.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    await act(async () => {
      await result.current.handleGenerate();
    });
    expect(result.current.error).toBe('后端服务不可用或请求中断，请检查后端是否启动');
  });

  it('生成失败（429 配额）：透传后端限流消息', async () => {
    const quotaMsg = '已达今日分析次数上限（200 / 200 次），请明天再试，或使用自己的 API Key（BYOK）';
    mockCtx.gen.mockRejectedValueOnce({ status: 429, message: quotaMsg });
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    await act(async () => {
      await result.current.handleGenerate();
    });
    expect(result.current.error).toContain('已达今日分析次数上限');
    expect(result.current.error).toContain('API Key');
  });

  it('followUpSuggestions：由画像分类/日期/数值字段生成追问建议', () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    const s = result.current.followUpSuggestions;
    expect(s.length).toBeGreaterThanOrEqual(2);
    expect(s[0]).toContain('地区');
    expect(s[1]).toContain('月份');
  });

  // ---- 阶段 53 · B7：定时任务创建反馈（成功/失败可区分、失败可读）----
  it('B7 创建定时任务成功：反馈含"已创建"且标记成功样式', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => {
      result.current.setScheduleTplId('t1');
      result.current.setScheduleCron('0 9 * * *');
    });
    await act(async () => {
      await result.current.handleCreateSchedule();
    });
    expect(mockCtx.createSchedule).toHaveBeenCalledWith('t1', '0 9 * * *');
    expect(result.current.scheduleMsg).toContain('已创建');
    expect(result.current.scheduleMsgType).toBe('success');
    // 成功后清空 cron 输入，避免重复提交同一任务
    expect(result.current.scheduleCron).toBe('');
    expect(mockCtx.listSchedules).toHaveBeenCalled(); // 列表刷新
  });

  it('B7 创建定时任务失败：反馈含错误原因且标记失败样式', async () => {
    mockCtx.createSchedule.mockRejectedValueOnce({ message: 'cron 表达式不合法' });
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    act(() => {
      result.current.setScheduleTplId('t1');
      result.current.setScheduleCron('bad cron');
    });
    await act(async () => {
      await result.current.handleCreateSchedule();
    });
    expect(result.current.scheduleMsg).toContain('cron 表达式不合法');
    expect(result.current.scheduleMsgType).toBe('error');
  });

  it('B7 未选模板/未填 cron：就地提示（error 样式），不发请求', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper });
    await act(async () => {
      await result.current.handleCreateSchedule();
    });
    expect(result.current.scheduleMsg).toContain('cron');
    expect(result.current.scheduleMsgType).toBe('error');
    expect(mockCtx.createSchedule).not.toHaveBeenCalled();
  });
});