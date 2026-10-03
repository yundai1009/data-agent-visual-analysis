/**
 * 阶段 53 · A2：导出失败不再用原生 alert，改为弹窗内错误横幅。
 *
 * 缺陷（用户走查观察）：导出失败时弹原生 window.alert("导出失败：…")，
 * 与全站"页面内横幅"的错误呈现方式不一致，像两个系统。
 * 期望：onExport 抛错 → ExportDialog 内显示红色错误条 + 弹窗保持打开，
 *       用户看清原因再关闭。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ExportDialog from './ExportDialog';

function renderDialog(overrides = {}) {
  const props = {
    showDl: true,
    onClose: vi.fn(),
    onExport: vi.fn().mockResolvedValue(undefined),
    dlFmt: 'xlsx',
    setDlFmt: vi.fn(),
    chartTypeKey: 'bar',
    trace: [{ 步骤: '选字段' }],
    exportData: { HTML: '<html></html>', JSON: '{}' },
    ...overrides,
  };
  render(<ExportDialog {...props} />);
  return props;
}

describe('ExportDialog 错误呈现（阶段 53 · A2）', () => {
  beforeEach(() => vi.clearAllMocks());

  it('导出失败：显示弹窗内错误横幅，且弹窗不自动关闭', async () => {
    const onExport = vi.fn().mockRejectedValue(new Error('网络异常，请重试'));
    const { onClose } = renderDialog({ onExport });

    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));

    expect(await screen.findByText(/导出失败|网络异常/)).toBeInTheDocument();
    expect(screen.getByText('导出报表')).toBeInTheDocument(); // 弹窗仍在
    expect(onClose).not.toHaveBeenCalled();
  });

  it('错误横幅在重试前一直可见，不依赖 window.alert', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const onExport = vi.fn().mockRejectedValue(new Error('磁盘权限不足'));
    renderDialog({ onExport });

    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));

    expect(await screen.findByText(/磁盘权限不足/)).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('导出成功：关闭弹窗（回归：成功路径不受错误处理影响）', async () => {
    const onExport = vi.fn().mockResolvedValue(undefined);
    const { onClose } = renderDialog({ onExport });

    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/网络异常|权限不足/)).not.toBeInTheDocument();
  });

  it('失败后重试成功：错误横幅消失且关闭弹窗', async () => {
    const onExport = vi.fn()
      .mockRejectedValueOnce(new Error('首次失败'))
      .mockResolvedValueOnce(undefined);
    const { onClose } = renderDialog({ onExport });

    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));
    expect(await screen.findByText(/首次失败/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /确认下载/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/首次失败/)).not.toBeInTheDocument();
  });
});