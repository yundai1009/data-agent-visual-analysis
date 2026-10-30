// 阶段八十五：看板全局筛选器 + 看板导出测试
// 锁住四条约束：
//   ① 维度下拉的选项来自各报表「图表配置.X轴 / 颜色 / 分组字段」，取值来自「报表.报表数据」的去重值；
//   ② 选了维度+取值后，数据里没有该取值的卡片灰显（opacity-30 grayscale），命中的卡片不灰；
//   ③ 清空按钮 → 灰显恢复；
//   ④ 「导出看板」调 exportDashboard(看板ID, 'xlsx') 并触发一次浏览器下载（文件名来自 Content-Disposition）。
// 另加一条回归：筛选选项是 reports 的纯派生值，**不能**再走 useMemo→useEffect→setState 同步。
//   当初那样写在 detail=null 的那一帧会在每次渲染重建数组，导致无限重渲染（vitest worker 烧死）。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
  exportDashboard: vi.fn(),
}));

vi.mock('../components/EChartsChart', () => ({
  default: () => <div data-testid="chart-mock">图表</div>,
}));
vi.mock('../components/LineageGraph', () => ({ default: () => null }));
vi.mock('../components/LineageDrawer', () => ({ default: () => null }));

import * as api from '../api';
import Dashboard from './Dashboard';

// r1 的 X 轴是「区域」，r2 的 X 轴是「品类」→ 两个维度、两组取值
const 看板详情 = {
  看板ID: 'b1', 名称: '销售月报', 创建时间: '2026-10-01', 布局: {},
  报表列表: [
    {
      报表ID: 'r1', 标题: '各区域销售额', 图表类型: 'bar', 创建时间: '2026-10-01',
      报表: {
        结论: '华东最高',
        图表配置: { 类型: 'bar', X轴: '区域', Y轴: ['销售额'], 数据: [{ 区域: '华东', 销售额: 100 }, { 区域: '华南', 销售额: 60 }] },
        报表数据: [{ 区域: '华东', 销售额: 100 }, { 区域: '华南', 销售额: 60 }],
      },
    },
    {
      报表ID: 'r2', 标题: '各品类销量', 图表类型: 'line', 创建时间: '2026-10-02',
      报表: {
        结论: 'A 类最高',
        图表配置: { 类型: 'line', X轴: '品类', Y轴: ['销量'], 数据: [{ 品类: 'A', 销量: 10 }, { 品类: 'B', 销量: 5 }] },
        报表数据: [{ 品类: 'A', 销量: 10 }, { 品类: 'B', 销量: 5 }],
      },
    },
  ],
};

let 下载 = null;
let clickSpy = null;

beforeEach(() => {
  vi.clearAllMocks();
  下载 = null;
  api.listDashboards.mockResolvedValue({ 看板列表: [{ 看板ID: 'b1', 名称: '销售月报', 报表数: 2 }] });
  api.getDashboard.mockResolvedValue(看板详情);
  api.listReports.mockResolvedValue({ 报表列表: [
    { 报表ID: 'r1', 数据集ID: 'd1', 标题: '各区域销售额', 图表类型: 'bar' },
    { 报表ID: 'r2', 数据集ID: 'd1', 标题: '各品类销量', 图表类型: 'line' },
  ] });
  api.listDatasets.mockResolvedValue({ 数据集列表: [], 统计: {} });
  api.updateDashboard.mockResolvedValue({ 看板ID: 'b1', 名称: '销售月报' });
  api.exportDashboard.mockResolvedValue({ blob: new Blob(['zip']), filename: '销售月报.zip' });

  // jsdom 没有 createObjectURL/revokeObjectURL，导出链路要自己兜住
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock');
  globalThis.URL.revokeObjectURL = vi.fn();
  clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function 记录下载() {
    下载 = { download: this.download, href: this.href };
  });
});

afterEach(() => {
  clickSpy?.mockRestore();
});

const 渲染 = () => render(<MemoryRouter initialEntries={['/dashboard']}><Dashboard /></MemoryRouter>);
const 等网格图 = () => waitFor(() => expect(screen.getAllByTestId('chart-mock')).toHaveLength(2));
// 卡片根节点是 rounded-2xl 的那个 div（工具条是 rounded-xl，不会误命中）
const 卡片 = (标题) => screen.getByText(标题).closest('div.rounded-2xl');

describe('看板页 · 全局筛选器（阶段八十五）', () => {
  it('维度下拉出现，选项 = 各报表的 X 轴字段（区域 / 品类）', async () => {
    渲染();
    await 等网格图();
    const dim = await screen.findByTestId('board-filter-dim');
    const options = [...dim.querySelectorAll('option')].map((o) => o.value);
    expect(options).toEqual(['', '区域', '品类']);   // 首项「全部维度」，其余按字典序
    // 还没选维度 → 取值下拉不出现
    expect(screen.queryByTestId('board-filter-value')).not.toBeInTheDocument();
  });

  it('选维度后取值下拉出现，取值 = 该维度在报表数据里的去重值', async () => {
    渲染();
    await 等网格图();
    fireEvent.change(await screen.findByTestId('board-filter-dim'), { target: { value: '区域' } });
    const val = await screen.findByTestId('board-filter-value');
    const options = [...val.querySelectorAll('option')].map((o) => o.value);
    expect(options).toEqual(['', '华东', '华南']);
  });

  it('选维度+取值 → 数据里没有该取值的卡片灰显，命中的不灰', async () => {
    渲染();
    await 等网格图();
    fireEvent.change(await screen.findByTestId('board-filter-dim'), { target: { value: '区域' } });
    fireEvent.change(await screen.findByTestId('board-filter-value'), { target: { value: '华东' } });

    await waitFor(() => expect(卡片('各品类销量').className).toContain('opacity-30'));
    expect(卡片('各品类销量').className).toContain('grayscale');
    // r1 的报表数据里有「华东」→ 命中，保持原样
    expect(卡片('各区域销售额').className).not.toContain('opacity-30');
    // 有筛选时禁用拖拽排序，避免拖完发现是灰卡
    expect(卡片('各区域销售额')).toHaveAttribute('draggable', 'false');
  });

  it('清空筛选 → 灰显恢复、拖拽恢复', async () => {
    渲染();
    await 等网格图();
    fireEvent.change(await screen.findByTestId('board-filter-dim'), { target: { value: '区域' } });
    fireEvent.change(await screen.findByTestId('board-filter-value'), { target: { value: '华东' } });
    await waitFor(() => expect(卡片('各品类销量').className).toContain('opacity-30'));

    fireEvent.click(screen.getByTitle('清空筛选'));
    await waitFor(() => expect(卡片('各品类销量').className).not.toContain('opacity-30'));
    expect(screen.queryByTestId('board-filter-value')).not.toBeInTheDocument();
    expect(卡片('各品类销量')).toHaveAttribute('draggable', 'true');
  });
});

describe('看板页 · 导出看板（阶段八十五）', () => {
  it('点「导出看板」→ 调 exportDashboard(看板ID, xlsx) 并触发下载，文件名取响应头解析结果', async () => {
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByTestId('board-export'));

    await waitFor(() => expect(api.exportDashboard).toHaveBeenCalledWith('b1', 'xlsx'));
    await waitFor(() => expect(下载).not.toBeNull());
    expect(下载.download).toBe('销售月报.zip');
    expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalled();
  });

  it('导出失败 → 页面提示错误且不触发下载', async () => {
    api.exportDashboard.mockRejectedValue(new Error('看板为空'));
    渲染();
    await 等网格图();
    fireEvent.click(screen.getByTestId('board-export'));

    await waitFor(() => expect(screen.getByText(/看板导出失败：看板为空/)).toBeInTheDocument());
    expect(下载).toBeNull();
  });
});
