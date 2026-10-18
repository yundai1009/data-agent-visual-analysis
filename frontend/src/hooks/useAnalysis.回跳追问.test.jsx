// 阶段六十九 回归：报表页「继续分析」带回来的上一份报表，必须把追问条重新点亮。
//
// 为什么单开文件：阶段六十八「生成成功自动跳报表页」把分析页卸载了，liveDone /
// lastReportIdRef 全丢，追问条（查看报表 / 存为模板 / 推荐追问，阶段 52/53 入口）
// 在主导流程里再也没机会出现。真机 E2E P5 抓到这个回归：分析成功后在报表页等
// 180 秒也等不到「继续追问」。这里钉住修复后的行为：
//   1) 带 state 回到 /analysis → liveDone 就位、追问用的上一报表 ID 透传进 payload；
//   2) 不带 state 回到 /analysis → 追问条不该凭空出现（不能误开）。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import useAnalysis from './useAnalysis';

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
    navigate: vi.fn(),
    listTemplates: vi.fn().mockResolvedValue({ 模板列表: [] }),
    listSchedules: vi.fn().mockResolvedValue({ 任务列表: [] }),
  };
});

vi.mock('../api', () => ({
  generateReportStream: (payload, opts) => mockCtx.gen(payload, opts),
  listTemplates: (...a) => mockCtx.listTemplates(...a),
  saveTemplate: vi.fn().mockResolvedValue({}),
  deleteTemplate: vi.fn().mockResolvedValue({}),
  runTemplate: vi.fn().mockResolvedValue({}),
  listSchedules: (...a) => mockCtx.listSchedules(...a),
  createSchedule: vi.fn().mockResolvedValue({}),
  deleteSchedule: vi.fn().mockResolvedValue({}),
}));

vi.mock('../AppContext', () => ({
  useApp: () => ({ dataset: mockCtx.dataset }),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => mockCtx.navigate };
});

// 报表页「继续分析」跳过来时带的 location.state
const 带回来 = { pathname: '/analysis', state: { 上一报表ID: 'r-77', 上一报表标题: '地区销售构成' } };
const 直接进来 = { pathname: '/analysis' };

function wrapper(entry) {
  return ({ children }) => <MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter>;
}

describe('阶段六十九 报表页回跳后的追问条恢复', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCtx.dataset = { ...mockCtx.baseDataset };
    mockCtx.gen.mockImplementation(async () => {});
  });

  it('带上一报表 ID 回到分析页：liveDone 就位，业务仍在非生成态', () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper: wrapper(带回来) });

    // Analysis.jsx 的追问条门控是 liveDone && !generating —— 这两个都要成立
    expect(result.current.liveDone).toEqual({ 报表ID: 'r-77', 标题: '地区销售构成' });
    expect(result.current.generating).toBe(false);
  });

  it('带上一报表 ID 回到分析页：追问走真链路，payload 带上一报表ID', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper: wrapper(带回来) });

    await act(async () => {
      await result.current.handleFollowUp('那华南区呢？');
    });

    expect(mockCtx.gen).toHaveBeenCalledTimes(1);
    const payload = mockCtx.gen.mock.calls[0][0];
    expect(payload.分析需求).toBe('那华南区呢？');
    expect(payload.上一报表ID).toBe('r-77');
  });

  it('没带 state 直接进分析页：不凭空亮起追问条', async () => {
    const { result } = renderHook(() => useAnalysis(), { wrapper: wrapper(直接进来) });

    expect(result.current.liveDone).toBeNull();

    // 追问动作必须拦住（此时没有可追问的对象），且不能发出请求
    await act(async () => {
      await result.current.handleFollowUp('那华南区呢？');
    });
    expect(mockCtx.gen).not.toHaveBeenCalled();
    expect(result.current.error).toContain('还没有可追问');
  });
});
