/**
 * 阶段 53 · A3：分享页需密码交互修复。
 *
 * 缺陷（用户走查观察）：打开一个"有密码"的分享链接，密码输入框上方
 * 直接显示"密码不正确，请重试"——用户还没输过密码就被指责。后端
 * 对"未带密码"与"密码错误"都返回 401，前端不区分、硬编码该文案。
 * 期望：
 *   1. 首次无密码 → 只显示密码框，不显示错误
 *   2. 输错密码 → 才提示"密码不正确，请重试"
 *   3. StrictMode 下同一分享只发一次请求（dev 双挂载导致重复请求）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';

const getSharedReport = vi.hoisted(() => vi.fn());
vi.mock('../api', () => ({ getSharedReport: (...a) => getSharedReport(...a) }));
vi.mock('../components/EChartsChart', () => ({ default: () => <div data-testid="chart" /> }));
vi.mock('react-router-dom', () => ({ useParams: () => ({ shareId: 's53' }) }));

import ShareView from './ShareView';

function err401(message) {
  const e = new Error(message);
  e.status = 401;
  return e;
}

describe('ShareView 需密码交互（阶段 53 · A3）', () => {
  beforeEach(() => vi.clearAllMocks());

  it('首次打开需密码分享：显示密码框，但不显示"密码不正确"（用户还没输过）', async () => {
    getSharedReport.mockRejectedValue(err401('需要访问密码'));
    render(<ShareView />);

    expect(await screen.findByText('此分享已设置访问密码')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('访问密码')).toBeInTheDocument();
    expect(screen.queryByText(/密码不正确/)).not.toBeInTheDocument();
  });

  it('输入错误密码：才提示密码不对（后端"访问密码不正确"）', async () => {
    getSharedReport.mockRejectedValueOnce(err401('需要访问密码'));
    render(<ShareView />);

    fireEvent.change(await screen.findByPlaceholderText('访问密码'), { target: { value: 'wrong' } });
    getSharedReport.mockRejectedValueOnce(err401('访问密码不正确'));
    fireEvent.click(screen.getByRole('button', { name: '查看报表' }));

    expect(await screen.findByText(/密码不正确|访问密码不正确/)).toBeInTheDocument();
  });

  it('首次无密码时不带 X-Share-Password 请求头（不把空密码发出去）', async () => {
    getSharedReport.mockRejectedValue(err401('需要访问密码'));
    render(<ShareView />);

    await screen.findByText('此分享已设置访问密码');
    expect(getSharedReport).toHaveBeenCalledWith('s53', '');
  });

  it('StrictMode 双挂载：同一分享只请求一次（dev 重复请求消失）', async () => {
    getSharedReport.mockRejectedValue(err401('需要访问密码'));
    render(
      <StrictMode>
        <ShareView />
      </StrictMode>,
    );

    await screen.findByText('此分享已设置访问密码');
    await waitFor(() => expect(getSharedReport.mock.calls.length).toBe(1));
  });

  it('密码正确：渲染报表标题与只读标识', async () => {
    getSharedReport
      .mockRejectedValueOnce(err401('需要访问密码'))
      .mockResolvedValueOnce({
        标题: '销售周报', 图表类型: 'bar', 图表配置: { 类型: 'bar' },
        报表数据: [{ 城市: '杭州', 销量: 10 }], 结论: '杭州领先', 风险提示: [],
      });
    render(<ShareView />);

    fireEvent.change(await screen.findByPlaceholderText('访问密码'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: '查看报表' }));

    expect(await screen.findByText('销售周报')).toBeInTheDocument();
    expect(screen.getByText('只读视图')).toBeInTheDocument();
  });
});