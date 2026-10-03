// DataManagement 数据管理页组件测试（阶段 51）：mock api + AppContext，
// 覆盖列表加载 / 空态 / 删除确认流程 / 搜索 / 上传成功与部分失败提示。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockApi = vi.hoisted(() => ({
  listDatasets: vi.fn().mockResolvedValue({ 数据集列表: [], 统计: { 总数: 0, 总行数: 0 } }),
  healthCheck: vi.fn().mockResolvedValue({ status: 'ok' }),
  deleteDataset: vi.fn().mockResolvedValue({ message: '已删除' }),
  uploadFileWithProgress: vi.fn(),
  renameDataset: vi.fn().mockResolvedValue({}),
  mergeDatasets: vi.fn().mockResolvedValue({}),
  getDataset: vi.fn().mockResolvedValue({ 文件名: 'x.csv', 数据画像: {} }),
  getDatasetRows: vi.fn().mockResolvedValue({}),
  exportUserData: vi.fn().mockResolvedValue({}),
  loadExample: vi.fn().mockResolvedValue({}),
  cleanDataset: vi.fn().mockResolvedValue({}),
}));

vi.mock('../api', () => ({
  listDatasets: (...a) => mockApi.listDatasets(...a),
  healthCheck: (...a) => mockApi.healthCheck(...a),
  deleteDataset: (...a) => mockApi.deleteDataset(...a),
  uploadFileWithProgress: (...a) => mockApi.uploadFileWithProgress(...a),
  renameDataset: (...a) => mockApi.renameDataset(...a),
  mergeDatasets: (...a) => mockApi.mergeDatasets(...a),
  getDataset: (...a) => mockApi.getDataset(...a),
  getDatasetRows: (...a) => mockApi.getDatasetRows(...a),
  exportUserData: (...a) => mockApi.exportUserData(...a),
  loadExample: (...a) => mockApi.loadExample(...a),
  cleanDataset: (...a) => mockApi.cleanDataset(...a),
}));

const setAppDataset = vi.fn();
vi.mock('../AppContext', () => ({
  useApp: () => ({ dataset: null, setDataset: setAppDataset }),
}));

import DataManagement from './DataManagement';

function renderPage() {
  return render(
    <MemoryRouter>
      <DataManagement />
    </MemoryRouter>
  );
}

const 样本列表 = {
  数据集列表: [
    { 数据集ID: 'd1', 文件名: '销售.csv', 行数: 100, 列数: 4, 数据画像: {} },
    { 数据集ID: 'd2', 文件名: '订单.xlsx', 行数: 50, 列数: 3, 数据画像: {} },
  ],
  统计: { 总数: 2, 总行数: 150 },
};

describe('DataManagement 数据管理页', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listDatasets.mockResolvedValue({ 数据集列表: [], 统计: { 总数: 0, 总行数: 0 } });
    mockApi.healthCheck.mockResolvedValue({ status: 'ok' });
  });

  it('挂载后拉取健康检查与数据集列表', async () => {
    renderPage();
    await waitFor(() => expect(mockApi.healthCheck).toHaveBeenCalled());
    await waitFor(() => expect(mockApi.listDatasets).toHaveBeenCalledWith(200, '', 'created_at_desc'));
  });

  it('空列表：打开"我的数据集"面板显示空态文案', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /我的数据集/ }));
    expect(await screen.findByText('暂无数据集，上传一个吧')).toBeInTheDocument();
  });

  it('列表渲染：文件名 + 概览统计', async () => {
    mockApi.listDatasets.mockResolvedValue(样本列表);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /我的数据集/ }));
    expect(await screen.findByText('销售.csv')).toBeInTheDocument();
    expect(screen.getByText('订单.xlsx')).toBeInTheDocument();
    expect(screen.getByText(/共 2 个数据集 · 总行数 150 行/)).toBeInTheDocument();
  });

  it('删除流程：确认后调用 deleteDataset 并从列表移除', async () => {
    mockApi.listDatasets.mockResolvedValue(样本列表);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /我的数据集/ }));
    const 删除按钮 = (await screen.findAllByTitle('删除'))[0];
    fireEvent.click(删除按钮);

    await waitFor(() => expect(mockApi.deleteDataset).toHaveBeenCalledWith('d1'));
    await waitFor(() => expect(screen.queryByText('销售.csv')).not.toBeInTheDocument());
    expect(screen.getByText('订单.xlsx')).toBeInTheDocument();
  });

  it('删除流程：取消确认则弹出确认框但不调用 deleteDataset', async () => {
    mockApi.listDatasets.mockResolvedValue(样本列表);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /我的数据集/ }));
    const 删除按钮 = (await screen.findAllByTitle('删除'))[0];
    fireEvent.click(删除按钮);

    await waitFor(() =>
      expect(confirmSpy).toHaveBeenCalledWith('删除数据集「销售.csv」？此操作不可恢复。')
    );
    await new Promise((r) => setTimeout(r, 50)); // 等同步路径走完
    expect(mockApi.deleteDataset).not.toHaveBeenCalled();
    expect(screen.getByText('销售.csv')).toBeInTheDocument();
  });

  it('搜索文件名：触发带关键字的数据集列表重拉', async () => {
    mockApi.listDatasets.mockResolvedValue(样本列表);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /我的数据集/ }));
    const 搜索框 = await screen.findByPlaceholderText('搜索文件名…');
    fireEvent.change(搜索框, { target: { value: '销售' } });

    await waitFor(() => expect(mockApi.listDatasets).toHaveBeenCalledWith(200, '销售', 'created_at_desc'));
  });

  it('上传成功：调用上传接口并把新数据集写入全局 context', async () => {
    const 上传成功项 = {
      数据集ID: 'd9', 文件名: '新销售.csv', 行数: 3, 列数: 2,
      数据画像: { 行数: 3, 列数: 2, 日期字段: [], 分类字段: [], 数值字段: [] },
    };
    mockApi.uploadFileWithProgress.mockReturnValue({
      promise: Promise.resolve({ 上传成功: [上传成功项], 上传失败: [] }),
      abort: vi.fn(),
    });
    renderPage();
    const file = new File(['地区,销售额\n华东,1\n'], '新销售.csv', { type: 'text/csv' });
    const input = document.getElementById('file-input');
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockApi.uploadFileWithProgress).toHaveBeenCalled());
    await waitFor(() =>
      expect(setAppDataset).toHaveBeenCalledWith({
        数据集ID: 'd9', 文件名: '新销售.csv', 行数: 3, 数据画像: { 行数: 3, 列数: 2, 日期字段: [], 分类字段: [], 数值字段: [] },
      })
    );
  });

  it('上传部分失败：显示黄色部分成功提示', async () => {
    mockApi.uploadFileWithProgress.mockReturnValue({
      promise: Promise.resolve({
        上传成功: [{
          数据集ID: 'd9', 文件名: '好文件.csv',
          数据画像: { 行数: 1, 列数: 1, 日期字段: [], 分类字段: [], 数值字段: [] },
        }],
        上传失败: [{ 文件名: '坏文件.csv', 错误: '解析失败' }],
      }),
      abort: vi.fn(),
    });
    renderPage();
    const file = new File(['x'], '好文件.csv', { type: 'text/csv' });
    const input = document.getElementById('file-input');
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText(/成功上传 1 个文件，失败 1 个/)).toBeInTheDocument();
  });
});