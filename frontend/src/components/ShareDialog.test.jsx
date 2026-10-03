// 阶段 52：分享弹窗 ESC 关闭（P3 a11y）
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../api', () => ({
  createShare: vi.fn().mockResolvedValue({ 需密码: false, 协作者: [] }),
  listShares: vi.fn().mockResolvedValue({ 分享列表: [] }),
  revokeShare: vi.fn().mockResolvedValue({}),
}));

import ShareDialog from './ShareDialog';

describe('ShareDialog', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
  });

  it('showShare=false 时不渲染', () => {
    render(<ShareDialog showShare={false} onClose={onClose} currentReportId="r1" />);
    expect(screen.queryByText('分享报表')).not.toBeInTheDocument();
  });

  it('按 ESC 触发 onClose（回归：此前只能点 X/遮罩）', () => {
    render(<ShareDialog showShare onClose={onClose} currentReportId="r1" />);
    expect(screen.getByText('分享报表')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});