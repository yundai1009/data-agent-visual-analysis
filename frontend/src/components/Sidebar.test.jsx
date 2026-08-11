// 侧边栏组件测试：导航项（含账号设置）/ 退出 / 意见反馈入口
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({ submitFeedback: vi.fn() }));
vi.mock('../AppContext', () => ({
  useApp: () => ({
    user: { username: 'admin', role: 'admin' },
    logout: mockLogout,
  }),
}));

import Sidebar from './Sidebar';

const mockLogout = vi.fn();

function renderSidebar(collapsed = false) {
  return render(
    <MemoryRouter>
      <Sidebar collapsed={collapsed} onToggle={() => {}} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Sidebar 侧边栏', () => {
  it('渲染核心导航项（含账号设置）', () => {
    renderSidebar();
    expect(screen.getByText('数据管理')).toBeInTheDocument();
    expect(screen.getByText('智能分析')).toBeInTheDocument();
    expect(screen.getByText('报表历史')).toBeInTheDocument();
    expect(screen.getByText('图表看板')).toBeInTheDocument();
    expect(screen.getByText('账号设置')).toBeInTheDocument();
  });

  it('管理员显示管理后台入口', () => {
    renderSidebar();
    expect(screen.getByText('管理后台')).toBeInTheDocument();
  });

  it('显示当前用户名', () => {
    renderSidebar();
    expect(screen.getByText('admin')).toBeInTheDocument();
  });

  it('点击「退出」调用 logout', () => {
    renderSidebar();
    fireEvent.click(screen.getByText('退出'));
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it('点击「意见反馈」打开反馈弹窗', () => {
    renderSidebar();
    fireEvent.click(screen.getByText('意见反馈'));
    expect(screen.getByText(/使用体验/)).toBeInTheDocument();
  });
});
