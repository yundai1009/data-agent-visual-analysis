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

vi.mock('../components/EChartsChart', () => {
  const { forwardRef, useImperativeHandle } = require('react');
  return {
    default: forwardRef((props, ref) => {
      useImperativeHandle(ref, () => ({ 导出PNG: () => 'data:image/png;base64,mock' }));
      return (
        <div data-testid="chart-mock" data-cfg={JSON.stringify(props.chartConfig)}>
          图表
          <button data-testid={`chart-click-${props.chartConfig?.X轴 || 'x'}`} onClick={() => props.on点选?.({ name: '华东' })}>点图</button>
        </div>
      );
    }),
  };
});

// 关系图与抽屉各自有测试文件，这里只验证"点回调被接线"
// 图 mock 把数据集节点名渲染出来——顺便断言 数据集ID→文件名 的 join 真的通了
vi.mock('../components/LineageGraph', () => {
  const { forwardRef, useImperativeHandle } = require('react');
  return {
    default: forwardRef(({ onSelectNode, 高亮节点ID, 图数据 }, ref) => {
      useImperativeHandle(ref, () => ({ 导出PNG: () => 'data:image/png;base64,mock' }));
      return (
        <button data-testid="lineage-graph-mock" data-高亮={高亮节点ID} onClick={() => onSelectNode('ds:d1')}>
          {图数据.节点.filter((n) => n.类型 === '数据集').map((n) => n.名称).join(',')}
        </button>
      );
    }),
  };
});

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

  // 阶段八十九：血缘图导出 PNG —— 关系视图里一键把图存成图片（此前只能截图）
  it('关系视图有「导出 PNG」按钮，点击触发下载且不报错', async () => {
    const clicks = [];
    const 原始 = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function 点击() { clicks.push({ href: this.href, download: this.download }); };
    try {
      渲染();
      await 等网格图();
      fireEvent.click(screen.getByRole('button', { name: /关系/ }));
      await waitFor(() => expect(screen.getByTestId('lineage-graph-mock')).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: /导出 PNG/ }));
      await waitFor(() => expect(clicks.length).toBe(1));
      expect(clicks[0].href).toBe('data:image/png;base64,mock');
      expect(clicks[0].download).toContain('销售月报-血缘关系图.png');
      // 正常路径不能弹错误
      expect(screen.queryByText(/血缘图尚未渲染完成/)).not.toBeInTheDocument();
    } finally {
      HTMLAnchorElement.prototype.click = 原始;
    }
  });

  it('空看板（0 报表）不进关系视图，也不报错', async () => {
    api.listDashboards.mockResolvedValue({ 看板列表: [] });
    api.listReports.mockResolvedValue({ 报表列表: [] });
    渲染();
    await waitFor(() => expect(screen.getByText('还没有看板')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /关系/ })).not.toBeInTheDocument();
  });

  // ---- 阶段八十九 · B5：看板导出 PDF/图片 ----
  it('网格视图有「导出图片」与「导出 PDF」按钮', async () => {
    渲染();
    await 等网格图();
    expect(screen.getByTestId('board-export-image')).toBeInTheDocument();
    expect(screen.getByTestId('board-export-pdf')).toBeInTheDocument();
  });

  it('导出图片：拼接全部图 dataURL → 下载一张 PNG（文件名带看板名）', async () => {
    const clicks = [];
    const 原始点击 = HTMLAnchorElement.prototype.click;
    const 原始创建 = global.document.createElement;
    HTMLAnchorElement.prototype.click = function 点击() { clicks.push({ href: this.href, download: this.download }); };
    // canvas.getContext / toDataURL：jsdom 没有 canvas，给最小桩
    const ctx = { fillRect: vi.fn(), drawImage: vi.fn() };
    global.document.createElement = function (tag) {
      if (tag === 'canvas') return { width: 0, height: 0, getContext: () => ctx, toDataURL: () => 'data:image/png;base64,stitched' };
      return 原始创建.call(this, tag);
    };
    // Image：立即触发 onload（同源 dataURL 同步解码）
    const 原始Image = global.Image;
    global.Image = class { set src(v) { this._src = v; if (this.onload) this.onload(); } get src() { return this._src; } };
    try {
      渲染();
      await 等网格图();
      fireEvent.click(screen.getByTestId('board-export-image'));
      await waitFor(() => expect(clicks.length).toBe(1));
      expect(clicks[0].href).toBe('data:image/png;base64,stitched');
      expect(clicks[0].download).toContain('销售月报-看板.png');
      expect(ctx.drawImage).toHaveBeenCalledTimes(2);
    } finally {
      HTMLAnchorElement.prototype.click = 原始点击;
      global.document.createElement = 原始创建;
      global.Image = 原始Image;
    }
  });

  it('导出 PDF：打开打印窗口并写入每张图，不触发下载', async () => {
    const written = { html: '' };
    const 原始Open = global.window.open;
    global.window.open = () => ({
      document: { open: vi.fn(), close: vi.fn(), write: (h) => { written.html = h; } },
      focus: vi.fn(), print: vi.fn(),
    });
    try {
      渲染();
      await 等网格图();
      fireEvent.click(screen.getByTestId('board-export-pdf'));
      await waitFor(() => expect(written.html).toContain('销售月报'));
      expect(written.html).toContain('data:image/png;base64,mock');
      expect(written.html).toContain('各区域销售额');
      expect(written.html).toContain('华东最高');
    } finally {
      global.window.open = 原始Open;
    }
  });

  it('全表格式看板：导出图片/PDF 提示无可导出图表，不崩', async () => {
    api.getDashboard.mockResolvedValue({
      看板ID: 'b2', 名称: '纯表格', 创建时间: '2026-10-01',
      报表列表: [{ 报表ID: 'r1', 标题: '明细', 图表类型: 'table', 报表: { 结论: '', 图表配置: { 类型: 'table', 数据: [] } } }],
    });
    渲染();
    // 全表格 → 没有任何 chart-mock（表格类不渲染 ECharts）
    await waitFor(() => expect(screen.getByText('明细')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('board-export-image'));
    await waitFor(() => expect(screen.getByText(/没有可导出的图表/)).toBeInTheDocument());
  });

  // ---- 阶段八十九 · B6：看板联动/下钻 ----
  it('点图 → 联动筛选（全局筛选器跟着变）+ 下钻 chips 出现，返回后清空', async () => {
    渲染();
    await 等网格图();
    // 点第一张图（r1，X轴=区域，点中 华东）
    fireEvent.click(screen.getAllByTestId(/chart-click-/)[0]);
    // 联动：全局筛选器的 值 下拉被设为 华东
    await waitFor(() => expect(screen.getByText('区域=华东')).toBeInTheDocument());
    expect(screen.getByDisplayValue('华东')).toBeInTheDocument();
    // 下钻 chips 与「返回」按钮出现
    await waitFor(() => expect(screen.getByRole('button', { name: /返回/ })).toBeInTheDocument());
    // 返回 → 下钻清空，chips 消失
    fireEvent.click(screen.getByRole('button', { name: /返回/ }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /返回/ })).not.toBeInTheDocument());
    // 联动筛选仍保留（返回只退下钻，不清全局筛选）
    expect(screen.getByDisplayValue('华东')).toBeInTheDocument();
  });

  it('下钻把图配置切到下一维度（图表拿到应用下钻后的 cfg）', async () => {
    // r1 数据只有 区域/销售额 两列 → 下钻后无下一维度，X轴不变；
    // 换一个带 月份 列的数据来断言 X 轴真的切换
    api.getDashboard.mockResolvedValue({
      看板ID: 'b3', 名称: '多维', 创建时间: '2026-10-01',
      报表列表: [{
        报表ID: 'r1', 标题: '按区域', 图表类型: 'bar',
        报表: {
          结论: '', 图表配置: {
            类型: 'bar', X轴: '区域', Y轴: ['销售额'],
            数据: [
              { 区域: '华东', 销售额: 100, 月份: '1月' },
              { 区域: '华东', 销售额: 120, 月份: '2月' },
              { 区域: '华南', 销售额: 80, 月份: '1月' },
            ],
          },
        },
      }],
    });
    渲染();
    await waitFor(() => expect(screen.getByTestId('chart-mock')).toBeInTheDocument());
    fireEvent.click(screen.getAllByTestId(/chart-click-/)[0]);
    // 下钻后 X 轴切到 月份
    await waitFor(() => {
      const cfg = JSON.parse(screen.getByTestId('chart-mock').dataset.cfg);
      expect(cfg.X轴).toBe('月份');
      expect(cfg.数据).toHaveLength(2);
    });
  });

  // ---- 阶段八十九 · B7：看板刷新与订阅 ----
  it('点「刷新」重新拉取当前看板详情', async () => {
    渲染();
    await 等网格图();
    const 次数 = api.getDashboard.mock.calls.length;
    fireEvent.click(screen.getByTestId('board-refresh'));
    await waitFor(() => expect(api.getDashboard.mock.calls.length).toBe(次数 + 1));
    expect(api.getDashboard).toHaveBeenLastCalledWith('b1');
  });

  it('点「订阅」开启自动刷新，30 秒后再拉一次；再点关闭后不再拉', async () => {
    渲染();
    await 等网格图();
    // 先真实定时器完成首屏，再切假定时器（RTL 的 waitFor 依赖真实定时器，混用会超时）
    vi.useFakeTimers();
    try {
      const 基线 = api.getDashboard.mock.calls.length;
      fireEvent.click(screen.getByTestId('board-subscribe'));
      expect(screen.getByTestId('board-subscribe')).toHaveAttribute('aria-pressed', 'true');
      await vi.advanceTimersByTimeAsync(31000);
      expect(api.getDashboard.mock.calls.length).toBe(基线 + 1);
      fireEvent.click(screen.getByTestId('board-subscribe'));
      expect(screen.getByTestId('board-subscribe')).toHaveAttribute('aria-pressed', 'false');
      const 关闭后 = api.getDashboard.mock.calls.length;
      await vi.advanceTimersByTimeAsync(31000);
      expect(api.getDashboard.mock.calls.length).toBe(关闭后);
    } finally {
      vi.useRealTimers();
    }
  });
});
