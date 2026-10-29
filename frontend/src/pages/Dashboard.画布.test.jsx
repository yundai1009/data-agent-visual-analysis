// 阶段八十四：自由画布视图测试
// 锁住三条约束：① 点「画布」按钮切到 canvas 视图、data-testid="canvas-view" 出现；
// ② 进入画布视图时所有卡片都被种子布局给了显式坐标（不会重叠 / 不会缺坐标）；
// ③ 拖动一张卡片后松手 → updateDashboard 被调用且布局里该报表坐标已更新；
// ④ 缩放手柄拖动 → 卡片宽高变大且落库。
// 与既有 Dashboard.test.jsx 互不干扰（这里只测 canvas，不碰 lineage 的 listDatasets 约束）。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({
  listDashboards: vi.fn(),
  getDashboard: vi.fn(),
  createDashboard: vi.fn(),
  updateDashboard: vi.fn(),
  deleteDashboard: vi.fn(),
  listReports: vi.fn(),
  listDatasets: vi.fn(),
}));

vi.mock('../components/EChartsChart', () => ({
  default: () => <div data-testid="chart-mock">图表</div>,
}));
vi.mock('../components/LineageGraph', () => ({ default: () => null }));
vi.mock('../components/LineageDrawer', () => ({ default: () => null }));

import * as api from '../api';
import Dashboard from './Dashboard';

const 看板详情 = {
  看板ID: 'b1', 名称: '销售月报', 创建时间: '2026-10-01', 布局: {},
  报表列表: [
    { 报表ID: 'r1', 标题: '各区域销售额', 图表类型: 'bar', 创建时间: '2026-10-01',
      报表: { 结论: '华东最高', 图表配置: { 类型: 'bar', X轴: '区域', Y轴: ['销售额'], 数据: [{ 区域: '华东', 销售额: 100 }] } } },
    { 报表ID: 'r2', 标题: '各区域销量', 图表类型: 'line', 创建时间: '2026-10-02',
      报表: { 结论: '同向', 图表配置: { 类型: 'line', X轴: '区域', Y轴: ['销量'], 数据: [{ 区域: '华东', 销量: 8 }] } } },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listDashboards.mockResolvedValue({ 看板列表: [{ 看板ID: 'b1', 名称: '销售月报', 报表数: 2 }] });
  api.getDashboard.mockResolvedValue(看板详情);
  api.listReports.mockResolvedValue({ 报表列表: [
    { 报表ID: 'r1', 数据集ID: 'd1', 标题: '各区域销售额', 图表类型: 'bar' },
    { 报表ID: 'r2', 数据集ID: 'd1', 标题: '各区域销量', 图表类型: 'line' },
  ] });
  api.updateDashboard.mockResolvedValue({ 看板ID: 'b1', 名称: '销售月报' });
});

const 渲染 = () => render(<MemoryRouter initialEntries={['/dashboard']}><Dashboard /></MemoryRouter>);

describe('看板页 · 自由画布视图（阶段 八十四）', () => {
  it('默认网格视图，画布视图不在 DOM', async () => {
    渲染();
    await waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
    expect(screen.queryByTestId('canvas-view')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /画布/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('点「画布」→ 进入 canvas 视图，两张卡都拿到显式坐标（不重叠）', async () => {
    渲染();
    await waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: /画布/ }));
    const canvas = await screen.findByTestId('canvas-view');
    const cards = canvas.querySelectorAll('[data-report-id]');
    expect(cards.length).toBe(2);
    const r1 = canvas.querySelector('[data-report-id="r1"]');
    const r2 = canvas.querySelector('[data-report-id="r2"]');
    // 种子布局：第 0 张 x=0，第 1 张 x=0+宽+24 → 不重叠
    expect(r1.style.left).toBe('0px');
    expect(Number(r2.style.left.replace('px', ''))).toBeGreaterThan(0);
    expect(r1.style.top).toBe('0px');
  });

  it('拖动卡片松手 → updateDashboard 带新布局，该卡坐标更新', async () => {
    渲染();
    await waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: /画布/ }));
    const canvas = await screen.findByTestId('canvas-view');
    const r1 = canvas.querySelector('[data-report-id="r1"]');
    const header = r1.querySelector('[data-report-id] > div');   // 卡头顶栏绑定 move
    fireEvent.mouseDown(header, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(window, { clientX: 110, clientY: 60 });
    fireEvent.mouseUp(window, { clientX: 110, clientY: 60 });
    await waitFor(() => expect(api.updateDashboard).toHaveBeenCalled());
    const lastCall = api.updateDashboard.mock.calls[api.updateDashboard.mock.calls.length - 1];
    const layout = lastCall[3];
    expect(layout.r1.x).toBe(100);
    expect(layout.r1.y).toBe(50);
  });

  it('缩放手柄拖动 → 卡片宽高变大且落库', async () => {
    渲染();
    await waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: /画布/ }));
    const canvas = await screen.findByTestId('canvas-view');
    const r1 = canvas.querySelector('[data-report-id="r1"]');
    const handle = r1.querySelector('[title="拖拽右下角缩放"]');
    fireEvent.mouseDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.mouseMove(window, { clientX: 200, clientY: 120 });
    fireEvent.mouseUp(window, { clientX: 200, clientY: 120 });
    await waitFor(() => expect(api.updateDashboard).toHaveBeenCalled());
    const lastCall = api.updateDashboard.mock.calls[api.updateDashboard.mock.calls.length - 1];
    const layout = lastCall[3];
    expect(layout.r1.w).toBeGreaterThan(440);
    expect(layout.r1.h).toBeGreaterThan(320);
  });

  it('已存布局直接回显（不回落自动网格）', async () => {
    api.getDashboard.mockResolvedValue({
      ...看板详情,
      布局: { r1: { x: 500, y: 300, w: 600, h: 360 }, r2: { x: 50, y: 720, w: 440, h: 320 } },
    });
    渲染();
    await waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: /画布/ }));
    const canvas = await screen.findByTestId('canvas-view');
    const r1 = canvas.querySelector('[data-report-id="r1"]');
    expect(r1.style.left).toBe('500px');
    expect(r1.style.top).toBe('300px');
  });
});

