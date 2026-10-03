// 账号设置页组件测试：改名 / 改密 / 注销三条核心交互路径
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// mock API 层：避免真实 fetch
vi.mock('../api', () => ({
  changeUsername: vi.fn(),
  changePassword: vi.fn(),
  deleteAccount: vi.fn(),
  getMyUsage: vi.fn(),
}));

import * as api from '../api';
import Account from './Account';

const mockLogout = vi.fn();
const mockSetAuth = vi.fn();
const mockNavigate = vi.fn();

// mock 全局 context + router
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../AppContext', () => ({
  useApp: () => ({
    user: { username: 'admin', role: 'admin' },
    logout: mockLogout,
    setAuth: mockSetAuth,
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <Account />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // 旧用例不关心用量：默认给"全 0 + 不限"避免挂载动作用量接口报错
  api.getMyUsage.mockResolvedValue({
    今日分析次数: 0, 今日token: 0, 每日次数上限: 0, 每日token上限: 0,
    剩余次数: null, 剩余token: null, 近30天分析次数: 0, 近30天token: 0,
  });
});

describe('Account 账号设置页', () => {
  it('渲染当前用户名与管理员标记', () => {
    renderPage();
    expect(screen.getByText(/^账号设置/)).toBeInTheDocument();
    expect(screen.getByText(/admin/)).toBeInTheDocument();
    expect(screen.getByText(/管理员/)).toBeInTheDocument();
  });

  it('修改用户名：提交成功 → 调用 changeUsername 并用 setAuth 同步状态', async () => {
    api.changeUsername.mockResolvedValue({
      message: '用户名已修改',
      username: 'yundai',
      access_token: 'new-token',
    });
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('2-50 个字符，需唯一'), {
      target: { value: 'yundai' },
    });
    fireEvent.click(screen.getByRole('button', { name: /确认修改用户名/ }));

    await waitFor(() => expect(api.changeUsername).toHaveBeenCalledWith('yundai'));
    await waitFor(() =>
      expect(mockSetAuth).toHaveBeenCalledWith('new-token', expect.objectContaining({ username: 'yundai' }))
    );
    expect(screen.getByText(/用户名已修改/)).toBeInTheDocument();
  });

  it('修改用户名：后端拒绝 → 展示错误消息且不调用 setAuth', async () => {
    api.changeUsername.mockRejectedValue(new Error('用户名已被使用，请换一个'));
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('2-50 个字符，需唯一'), {
      target: { value: 'taken' },
    });
    fireEvent.click(screen.getByRole('button', { name: /确认修改用户名/ }));

    await waitFor(() => expect(screen.getByText('用户名已被使用，请换一个')).toBeInTheDocument());
    expect(mockSetAuth).not.toHaveBeenCalled();
  });

  it('修改密码：旧密码+新密码提交 → 调用 changePassword 并更新会话', async () => {
    api.changePassword.mockResolvedValue({ message: '密码已修改', access_token: 'new-token' });
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('输入当前密码'), { target: { value: 'old-pass' } });
    fireEvent.change(screen.getByPlaceholderText('至少 6 位'), { target: { value: 'new-pass-1' } });
    fireEvent.click(screen.getByRole('button', { name: /确认修改密码/ }));

    await waitFor(() => expect(api.changePassword).toHaveBeenCalledWith('old-pass', 'new-pass-1'));
    await waitFor(() => expect(mockSetAuth).toHaveBeenCalledWith('new-token', expect.anything()));
    expect(screen.getByText('密码已修改')).toBeInTheDocument();
  });

  it('修改密码：新密码不足 6 位 → 按钮禁用', () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('输入当前密码'), { target: { value: 'old-pass' } });
    fireEvent.change(screen.getByPlaceholderText('至少 6 位'), { target: { value: '123' } });
    expect(screen.getByRole('button', { name: /确认修改密码/ })).toBeDisabled();
  });

  it('注销账号：输入密码确认 → deleteAccount + logout + 跳转登录页', async () => {
    api.deleteAccount.mockResolvedValue({ message: '账号已注销' });
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('输入当前密码确认注销'), { target: { value: 'my-password' } });
    fireEvent.click(screen.getByRole('button', { name: /永久注销账号/ }));

    await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledWith('my-password'));
    await waitFor(() => expect(mockLogout).toHaveBeenCalled());
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/login'));
  });
});

describe('Account 用量透明（阶段 53 · C10）', () => {
  const 用量样本 = {
    今日分析次数: 12,
    今日token: 98000,
    每日次数上限: 200,
    每日token上限: 1000000,
    剩余次数: 188,
    剩余token: 902000,
    近30天分析次数: 130,
    近30天token: 1200000,
  };

  it('展示今日次数/配额剩余/近 30 天用量', async () => {
    api.getMyUsage.mockResolvedValue(用量样本);
    renderPage();
    await waitFor(() => expect(screen.getByText('用量概览')).toBeInTheDocument());
    expect(screen.getByText(/12 \/ 200 次/)).toBeInTheDocument();   // 今日已用 / 上限
    expect(screen.getByText(/今日剩余 188 次/)).toBeInTheDocument();
    expect(screen.getByText(/近 30 天：130 次/)).toBeInTheDocument();
    expect(screen.getByText(/98,000 \/ 1,000,000 token/)).toBeInTheDocument();
  });

  it('配额不限（剩余为 null）→ 展示"不限"而不是 0', async () => {
    api.getMyUsage.mockResolvedValue({
      ...用量样本, 每日次数上限: 0, 剩余次数: null, 每日token上限: 0, 剩余token: null,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('用量概览')).toBeInTheDocument());
    // 次数卡与 token 卡都展示"不限"（getAllByText 避免多元素报错）
    expect(screen.getAllByText(/不限/).length).toBeGreaterThanOrEqual(2);
  });

  it('用量接口失败 → 页面其余功能不受影响，不显示崩溃', async () => {
    api.getMyUsage.mockRejectedValue(new Error('网络错误'));
    renderPage();
    await waitFor(() => expect(api.getMyUsage).toHaveBeenCalled());
    expect(screen.getByText(/^账号设置/)).toBeInTheDocument();
    expect(screen.getByText(/用量加载失败/)).toBeInTheDocument();
  });
});
