// 报表历史页：统一下载对话框测试（选格式 → 确认下载 → 调后端端点）
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

vi.mock('../api', () => ({
  listReports: vi.fn(),
  getReport: vi.fn(),
  deleteReport: vi.fn(),
  exportReport: vi.fn(),
  createShare: vi.fn(),
  listShares: vi.fn(),
  revokeShare: vi.fn(),
  replayReport: vi.fn(),
}));

// mock ECharts：避免在测试中加载 1MB echarts chunk
vi.mock('../components/EChartsChart', () => ({
  default: () => <div data-testid="chart-mock">图表</div>,
}));

import * as api from '../api';
import Report from './Report';

const chartReport = {
  报表ID: 'r1',
  标题: '销售分析',
  图表类型: '柱状图',
  图表配置: { 类型: 'bar' },
  结论: '销售额环比增长',
  推荐说明: { 理由: ['月度趋势'] },
  风险提示: ['数据样本偏少'],
  'Agent Trace': [{ 步骤: '数据分析', 状态: '成功', 说明: '完成汇总' }],
  报表数据: [{ 月份: '1月', 销售额: 100 }],
  导出数据: { HTML: '<html><body>报告</body></html>', JSON: '{"ok":1}' },
};

function setupMocks(report = chartReport) {
  api.listReports.mockResolvedValue({
    报表列表: [{ 报表ID: report.报表ID, 标题: report.标题, 图表类型: report.图表类型 }],
  });
  api.getReport.mockResolvedValue({ 报表: report, 报表ID: report.报表ID, 上一报表标题: '' });
  api.exportReport.mockResolvedValue({ blob: new Blob(['x']), filename: 'report.csv' });
}

function renderReport() {
  return render(
    <MemoryRouter initialEntries={['/report/r1']}>
      <Routes>
        <Route path="/report/:reportId" element={<Report />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeAll(() => {
  // jsdom 缺少 File System Access API 与 blob URL —— saveWithPicker 应回退 a.download
  Object.defineProperty(window, 'showSaveFilePicker', { writable: true, value: undefined });
  Object.defineProperty(URL, 'createObjectURL', { writable: true, value: vi.fn(() => 'blob:mock') });
  Object.defineProperty(URL, 'revokeObjectURL', { writable: true, value: vi.fn() });
  // 阻止 jsdom 中对 a.click() 导航报警
  Object.defineProperty(HTMLAnchorElement.prototype, 'click', { writable: true, value: vi.fn() });
});

beforeEach(() => {
  vi.clearAllMocks();
  setupMocks();
});

describe('Report 统一下载对话框', () => {
  it('点「导出」打开对话框，展示全部可用格式', async () => {
    renderReport();
    await screen.findByText('报表查看');

    fireEvent.click(screen.getByText('导出'));

    expect(screen.getByText('导出报表')).toBeInTheDocument();
    expect(screen.getByText('Excel 表格')).toBeInTheDocument();
    expect(screen.getByText('CSV 数据')).toBeInTheDocument();
    expect(screen.getByText('PDF 报告')).toBeInTheDocument();
    expect(screen.getByText('图表图片')).toBeInTheDocument();
    expect(screen.getByText('Agent 决策记录')).toBeInTheDocument();
    expect(screen.getByText('HTML 报告')).toBeInTheDocument();
    expect(screen.getByText('JSON 数据')).toBeInTheDocument();
  });

  it('选择 CSV → 确认下载 → 调用 exportReport 并关闭弹窗', async () => {
    renderReport();
    await screen.findByText('报表查看');

    fireEvent.click(screen.getByText('导出'));
    fireEvent.click(screen.getByText('CSV 数据'));
    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));

    await waitFor(() => expect(api.exportReport).toHaveBeenCalledWith('r1', 'csv'));
    await waitFor(() => expect(screen.queryByText('导出报表')).not.toBeInTheDocument());
    // jsdom 无 showSaveFilePicker → 回退 a.download（a.click 触发下载）
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it('表格型报表不出现「图表图片」选项', async () => {
    setupMocks({ ...chartReport, 图表类型: 'table', 图表配置: { 类型: 'table' } });
    renderReport();
    await screen.findByText('报表查看');

    fireEvent.click(screen.getByText('导出'));

    expect(screen.queryByText('图表图片')).not.toBeInTheDocument();
    expect(screen.getByText('Excel 表格')).toBeInTheDocument();
  });
});