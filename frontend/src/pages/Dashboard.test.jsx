// 阶段 六十：看板页网格/关系双视图测试
// 三个数据接口（getDashboard / listReports / listDatasets）全部 mock：不打真实后端，
// 并且用 listDatasets 的调用次数锁住"网格视图不为血缘多背一个请求"这条约束。
// mock ECharts：避免在测试中加载 1MB echarts chunk
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

// 关系图与抽屉各自有测试文件，这里只验证"点回调被接线"
// 图 mock 把数据集节点名渲染出来——顺便断言 数据集ID→文件名 的 join 真的通了
vi.mock('../components/LineageGraph', () => ({
  default: ({ onSelectNode, 高亮节点ID, 图数据 }) => (
    <button data-testid="lineage-graph-mock" data-高亮={高亮节点ID} onClick={() => onSelectNode('ds:d1')}>
      {图数据.节点.filter((n) => n.类型 === '数据集').map((n) => n.名称).join(',')}
    </button>
  ),
}));

vi.mock('../components/LineageDrawer', () => ({
  default: ({ 节点, onClose }) => (
    <div data-testid="lineage-drawer-mock">
      抽屉-{节点.名称}
      <button title="关闭" onClick={onClose}>×</button>
    </div>
  ),
}));

import * as api from '../api';
import Dashboard from './Dashboard';

const 看板详情 = {
  看板ID: 'b1', 名称: '销售月报', 创建时间: '2026-10-01',
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
    { 报表ID: 'r9', 数据集ID: 'd1', 标题: '历史报表', 图表类型: 'bar' },
  ] });
  api.listDatasets.mockResolvedValue({ 数据集列表: [{ 数据集ID: 'd1', 文件名: '销售.csv', 行数: 120, 列数: 5 }], 统计: {} });
});

const 渲染 = () => render(<MemoryRouter initialEntries={['/dashboard']}><Dashboard /></MemoryRouter>);

// 网格里一张报表一个 <EChartsChart>，夹具有 2 张报表 → chart-mock 必然是 2 个，
// 所以用 getAllBy/queryAllBy 而不是 getBy/queryBy（getBy 命中多元素时会直接抛错）
const 等网格图 = () => waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));

describe('看板页 · 网格/关系双视图（阶段 六十）', () => {
  it('默认是网格视图，关系图不在 DOM 里', async () => {
    渲染();
    await 等网格图();
    expect(screen.queryByTestId('lineage-graph-mock')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /网格/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('切到关系视图：渲染关系图 + 标题条统计 + 复用榜，且此时才请求数据集', async () => {
    渲染();
    await 等网格图();
    expect(api.listDatasets).not.toHaveBeenCalled();       // 网格视图不背这个请求

    fireEvent.click(screen.getByRole('button', { name: /关系/ }));
    await waitFor(() => expect(screen.getByTestId('lineage-graph-mock')).toBeInTheDocument());
    expect(screen.queryAllByTestId('chart-mock')).toHaveLength(0);
    expect(screen.getByText(/1 个数据集 → 2 张报表 → 1 个复用字段/)).toBeInTheDocument();
    await waitFor(() => expect(api.listDatasets).toHaveBeenCalledWith(200));
    // 数据集ID 被翻成了文件名（图上的数据集节点标签不能是 UUID）
    await waitFor(() => expect(screen.getByTestId('lineage-graph-mock')).toHaveTextContent('销售.csv'));
    expect(screen.getByText('字段复用榜（被 ≥2 张报表引用 = 值得治理的核心字段）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /区域/ })).toBeInTheDocument();
  });

  it('点关系图节点 → 打开抽屉并高亮；关闭抽屉 → 清空高亮', async () => {
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByRole('button', { name: /关系/ }));
    // 等数据集元信息落地，抽屉里的节点名才是文件名而不是 'd1'
    await waitFor(() => expect(screen.getByTestId('lineage-graph-mock')).toHaveTextContent('销售.csv'));

    fireEvent.click(screen.getByTestId('lineage-graph-mock'));
    await waitFor(() => expect(screen.getByTestId('lineage-drawer-mock')).toBeInTheDocument());
    expect(screen.getByTestId('lineage-drawer-mock')).toHaveTextContent('销售.csv');   // 数据集节点名 = 数据集文件名
    expect(screen.getByTestId('lineage-graph-mock')).toHaveAttribute('data-高亮', 'ds:d1');

    fireEvent.click(screen.getByTitle('关闭'));
    await waitFor(() => expect(screen.queryByTestId('lineage-drawer-mock')).not.toBeInTheDocument());
    expect(screen.getByTestId('lineage-graph-mock')).toHaveAttribute('data-高亮', '');
  });

  it('复用榜 chip 点一下 → 选中对应字段节点', async () => {
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByRole('button', { name: /关系/ }));
    fireEvent.click(await screen.findByRole('button', { name: /区域/ }));
    await waitFor(() => expect(screen.getByTestId('lineage-drawer-mock')).toHaveTextContent('区域'));
  });

  it('listDatasets 失败：关系视图仍可用，只提示一行黄字', async () => {
    api.listDatasets.mockRejectedValue(new Error('boom'));
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByRole('button', { name: /关系/ }));
    await waitFor(() => expect(screen.getByText(/数据集信息加载失败/)).toBeInTheDocument());
    expect(screen.getByTestId('lineage-graph-mock')).toBeInTheDocument();
  });

  it('切回网格视图：关系图与抽屉都卸载', async () => {
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByRole('button', { name: /关系/ }));
    fireEvent.click(await screen.findByTestId('lineage-graph-mock'));
    await waitFor(() => expect(screen.getByTestId('lineage-drawer-mock')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /网格/ }));
    expect(screen.queryByTestId('lineage-graph-mock')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lineage-drawer-mock')).not.toBeInTheDocument();
  });

  it('空看板（0 报表）不进关系视图，也不报错', async () => {
    api.listDashboards.mockResolvedValue({ 看板列表: [] });
    api.listReports.mockResolvedValue({ 报表列表: [] });
    渲染();
    await waitFor(() => expect(screen.getByText('还没有看板')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /关系/ })).not.toBeInTheDocument();
  });
});
