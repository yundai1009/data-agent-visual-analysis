/**
 * 阶段 52 回归测试：Login 页在 React StrictMode 下必须能完成注册/登录/发验证码。
 *
 * 缺陷（P0，真实用户走查发现）：
 *   Login.jsx 的卸载守卫写成 `useEffect(() => () => { mountedRef.current = false }, [])`，
 *   cleanup 置 false 却**没有 setup 复位**。React 19 StrictMode 在开发模式会
 *   setup → cleanup → setup 双调用，于是 mountedRef 永久停在 false，
 *   所有 await 后的回调（setSending(false) / setAuth+navigate）全部提前 return：
 *     - 「获取验证码」成功后按钮永远卡在"发送中"，倒计时不启动；
 *     - 注册 / 登录 POST 已 200，前端永远卡"处理中…"且不跳转。
 *
 * 本测试用 StrictMode 包裹渲染 Login，复现并锁定该行为。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StrictMode } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const apiMock = vi.hoisted(() => ({
  sendCode: vi.fn(),
  sendResetCode: vi.fn(),
  register: vi.fn(),
  login: vi.fn(),
  resetPassword: vi.fn(),
}));

vi.mock('../api', () => apiMock);

const appMock = vi.hoisted(() => ({
  setAuth: vi.fn(),
}));

vi.mock('../AppContext', () => ({
  useApp: () => appMock,
}));

const navMock = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => navMock.navigate }));

import Login from './Login';

function renderStrict() {
  return render(
    <StrictMode>
      <Login />
    </StrictMode>,
  );
}

describe('Login 页 StrictMode 回归（阶段 52）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.sendCode.mockResolvedValue({});
    apiMock.register.mockResolvedValue({ access_token: 'tok', user: { username: 'u' } });
    apiMock.login.mockResolvedValue({ access_token: 'tok', user: { username: 'u' } });
    apiMock.resetPassword.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('获取验证码成功后按钮离开"发送中"并开始倒计时', async () => {
    renderStrict();
    fireEvent.click(screen.getByText('去注册'));
    fireEvent.change(screen.getByPlaceholderText('用于接收注册验证码'), {
      target: { value: 'stage52@test.com' },
    });

    const btn = screen.getByRole('button', { name: '获取验证码' });
    fireEvent.click(btn);

    // 回归锁定：不能停在"发送中"——倒计时或按钮名必须变化
    await waitFor(() => {
      const name = btn.textContent;
      expect(name).not.toBe('发送中');
    }, { timeout: 3000 });
  });

  it('注册成功后 setAuth + 跳转 /data（不能卡"处理中…"）', async () => {
    renderStrict();
    fireEvent.click(screen.getByText('去注册'));
    fireEvent.change(screen.getByPlaceholderText('输入用户名'), { target: { value: 'u' } });
    fireEvent.change(screen.getByPlaceholderText('用于接收注册验证码'), { target: { value: 'stage52@test.com' } });
    fireEvent.change(screen.getByPlaceholderText('6 位验证码'), { target: { value: '123456' } });
    fireEvent.change(screen.getByPlaceholderText('至少 6 位'), { target: { value: 'secret123' } });

    const submit = screen.getByRole('button', { name: '注册' });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(appMock.setAuth).toHaveBeenCalled();
      expect(navMock.navigate).toHaveBeenCalledWith('/data');
    }, { timeout: 3000 });
    await waitFor(() => {
      expect(submit.textContent).not.toBe('处理中…');
    }, { timeout: 3000 });
  });

  it('登录成功后 setAuth + 跳转 /data', async () => {
    renderStrict();
    fireEvent.change(screen.getByPlaceholderText('输入用户名或邮箱'), { target: { value: 'u' } });
    fireEvent.change(screen.getByPlaceholderText('至少 6 位'), { target: { value: 'secret123' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await waitFor(() => {
      expect(navMock.navigate).toHaveBeenCalledWith('/data');
    }, { timeout: 3000 });
  });

  it('验证码发送失败时恢复按钮并展示错误（异常路径也不卡死）', async () => {
    apiMock.sendCode.mockRejectedValue(new Error('发送失败，请稍后重试'));
    renderStrict();
    fireEvent.click(screen.getByText('去注册'));
    fireEvent.change(screen.getByPlaceholderText('用于接收注册验证码'), { target: { value: 'bad@test.com' } });
    const btn = screen.getByRole('button', { name: '获取验证码' });
    fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByText('发送失败，请稍后重试')).toBeInTheDocument();
    }, { timeout: 3000 });
    await waitFor(() => {
      expect(btn.textContent).not.toBe('发送中');
    }, { timeout: 3000 });
  });
});