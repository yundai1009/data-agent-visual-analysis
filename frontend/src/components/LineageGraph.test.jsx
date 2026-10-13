// 阶段 六十：血缘关系图渲染层测试（mock echarts，不加载 1MB chunk）
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { 构建血缘图 } from '../utils/看板血缘';

// mock ECharts：避免在测试中加载 1MB echarts chunk
vi.mock('echarts', () => {
  const inst = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn() };
  return { init: vi.fn(() => inst), __inst: inst };
});

import * as echarts from 'echarts';
import LineageGraph from './LineageGraph';

const 图数据 = 构建血缘图({
  报表列表: [
    { 报表ID: 'r1', 标题: '各区域销售额', 报表: { 图表配置: { X轴: '区域', 数据: [{ 区域: '华东' }] } } },
    { 报表ID: 'r2', 标题: '各区域销量', 报表: { 图表配置: { X轴: '区域', 数据: [{ 区域: '华东' }] } } },
  ],
  报表索引: new Map([
    ['r1', { 报表ID: 'r1', 数据集ID: 'd1', 标题: '各区域销售额' }],
    ['r2', { 报表ID: 'r2', 数据集ID: 'd1', 标题: '各区域销量' }],
  ]),
  数据集索引: new Map([['d1', { 数据集ID: 'd1', 文件名: '销售.csv', 行数: 10, 列数: 2 }]]),
});

const 末次Option = () => echarts.__inst.setOption.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LineageGraph', () => {
  it('懒加载完成后用 canvas 渲染出关系图', async () => {
    render(<LineageGraph 图数据={图数据} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    expect(echarts.init.mock.calls[0][2]).toEqual({ renderer: 'canvas' });
    expect(末次Option().series[0].type).toBe('graph');
    expect(screen.getByTestId('血缘图画布')).toBeInTheDocument();
  });

  it('点节点回传节点ID，点连线不回传', async () => {
    const onSelectNode = vi.fn();
    render(<LineageGraph 图数据={图数据} onSelectNode={onSelectNode} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    const 点击 = echarts.__inst.on.mock.calls.find(([事件]) => 事件 === 'click')[1];

    点击({ dataType: 'node', data: { 节点ID: 'rp:r1' } });
    expect(onSelectNode).toHaveBeenCalledWith('rp:r1');

    onSelectNode.mockClear();
    点击({ dataType: 'edge', data: { source: 'ds:d1' } });
    expect(onSelectNode).not.toHaveBeenCalled();
  });

  it('高亮节点变化会重新 setOption', async () => {
    const { rerender } = render(<LineageGraph 图数据={图数据} 高亮节点ID="" />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    const 初次 = echarts.__inst.setOption.mock.calls.length;
    rerender(<LineageGraph 图数据={图数据} 高亮节点ID="rp:r1" />);
    await waitFor(() => expect(echarts.__inst.setOption.mock.calls.length).toBeGreaterThan(初次));
    const 透明度 = (id) => 末次Option().series[0].data.find((d) => d.节点ID === id).itemStyle.opacity;
    expect(透明度('rp:r1')).toBe(1);
    expect(透明度('ds:d1')).toBe(1);
  });

  it('卸载时 dispose 实例', async () => {
    const { unmount } = render(<LineageGraph 图数据={图数据} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    unmount();
    expect(echarts.__inst.dispose).toHaveBeenCalled();
  });

  it('图数据为空也安全渲染（不崩）', async () => {
    render(<LineageGraph 图数据={构建血缘图()} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    expect(末次Option().series[0].data).toEqual([]);
  });

  // ---- 以下 3 条对应 Task 2 硬约束里"必须处理并测到的真实工程细节" ----

  it('高亮变化只走 setOption，不重建实例（init 只调用一次、不 dispose）', async () => {
    const { rerender } = render(<LineageGraph 图数据={图数据} 高亮节点ID="" />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalledTimes(1));
    const 初次 = echarts.__inst.setOption.mock.calls.length;
    rerender(<LineageGraph 图数据={图数据} 高亮节点ID="rp:r1" />);
    await waitFor(() => expect(echarts.__inst.setOption.mock.calls.length).toBe(初次 + 1));
    expect(echarts.init).toHaveBeenCalledTimes(1);
    expect(echarts.__inst.dispose).not.toHaveBeenCalled();
  });

  it('窗口 resize 时转发给实例 resize()', async () => {
    render(<LineageGraph 图数据={图数据} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    echarts.__inst.resize.mockClear();
    window.dispatchEvent(new Event('resize'));
    expect(echarts.__inst.resize).toHaveBeenCalledTimes(1);
  });

  it('无数据时显示空态文案，而不是留一块空白画布', async () => {
    render(<LineageGraph 图数据={构建血缘图()} />);
    await waitFor(() => expect(echarts.init).toHaveBeenCalled());
    expect(screen.getByTestId('血缘图空态').textContent).toBe('当前看板暂无可展示的血缘关系');
  });
});
