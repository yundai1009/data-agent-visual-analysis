// 账号设置页组件测试：改名 / 改密 / 注销三条核心交互路径
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// mock API 层：避免真实 fetch
vi.mock('../api', () => ({
  changeUsername: vi.fn(),
  changePassword: vi.fn(),
  deleteAccount: vi.fn(),
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
