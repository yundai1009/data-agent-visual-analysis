// 阶段 55：图表局部精细化编辑面板（ChartRefinePanel）测试
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../api', () => ({
  refineReport: vi.fn(),
}));

import { refineReport } from '../api';
import ChartRefinePanel from './ChartRefinePanel';

const 画像 = {
  字段列表: ['城市', '销售额'],
  分类字段: ['城市'],
  数值字段: ['销售额'],
};

describe('ChartRefinePanel', () => {
  const onClose = vi.fn();
  const onRefined = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
    onRefined.mockClear();
  });

  it('show=false 时不渲染', () => {
    render(<ChartRefinePanel show={false} onClose={onClose} />);
    expect(screen.queryByText('精细化编辑图表')).not.toBeInTheDocument();
  });

  it('show=true 渲染标题与描述', () => {
    render(<ChartRefinePanel show onClose={onClose} reportId="r1" 画像={画像} />);
    expect(screen.getByText('精细化编辑图表')).toBeInTheDocument();
    expect(screen.getByText(/标识符\/编码字段/)).toBeInTheDocument();
  });

  it('NL 指令未输入时提示', () => {
    render(<ChartRefinePanel show onClose={onClose} reportId="r1" 画像={画像} />);
    expect(screen.getAllByText(/执行编辑/).length).toBeGreaterThan(0);
  });

  it('提交 NL 指令调用 refineReport 并展示变更清单', async () => {
    refineReport.mockResolvedValueOnce({
      需确认: false, 拒绝原因: null, 新报表ID: 'new1',
      新spec: { X轴: '销售额' },
      变更清单: [{ 字段: 'Y轴', 旧: '金额', 新: '销售额' }],
    });
    render(<ChartRefinePanel show onClose={onClose} reportId="r1" 画像={画像} onRefined={onRefined} />);
    fireEvent.change(screen.getByPlaceholderText(/例：把X轴换成城市/), { target: { value: '把X轴换成销售额' } });
    fireEvent.click(screen.getByText(/执行编辑/));
    await waitFor(() => {
      expect(refineReport).toHaveBeenCalledWith('r1', { 指令: '把X轴换成销售额' });
    });
    await waitFor(() => expect(screen.getByText('Y轴')).toBeInTheDocument());
    expect(onRefined).toHaveBeenCalledWith({ X轴: '销售额' }, 'new1');
  });

  it('后端返回拒绝原因时展示，不触发 onRefined', async () => {
    refineReport.mockResolvedValue({ 拒绝原因: '字段「订单ID」是标识符，禁止作为数值度量 Y 轴' });
    render(<ChartRefinePanel show onClose={onClose} reportId="r1" 画像={画像} onRefined={onRefined} />);
    fireEvent.change(screen.getByPlaceholderText(/把X轴换成城市/), { target: { value: '把X轴换成订单ID' } });
    fireEvent.click(screen.getByText('执行编辑'));
    await waitFor(() => expect(screen.getByText('编辑被拒绝')).toBeInTheDocument());
    expect(onRefined).not.toHaveBeenCalled();
  });

  it('后端返回需确认时展示提示', async () => {
    refineReport.mockResolvedValue({ 需确认: true, 拒绝原因: '未识别字段，请确认' });
    render(<ChartRefinePanel show onClose={onClose} reportId="r1" 画像={画像} onRefined={onRefined} />);
    fireEvent.change(screen.getByPlaceholderText(/把X轴换成城市/), { target: { value: '不知道かな怎么改' } });
    fireEvent.click(screen.getByText('执行编辑'));
    await waitFor(() => expect(screen.getByText('需要确认')).toBeInTheDocument());
    expect(onRefined).not.toHaveBeenCalled();
  });
});