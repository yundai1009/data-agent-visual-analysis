// 阶段七十四 · C（续）：默认模式从专业版翻成基础版后的两条规则。
// 反馈原话是「产品偏离初始定位——目标用户是 0 基础的普通人，现在复杂度偏高」。
// 默认基础版后，侧栏第一眼没有「对比分析」这个术语入口，
// 它改由数据管理页勾选 ≥2 份后的「对比这几份」进入；?mode=pro 或账号页切换可回专业版。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({ submitFeedback: vi.fn() }));
vi.mock('../AppContext', () => ({
  useApp: () => ({
    user: { username: 'guest', role: 'analyst' },
    logout: vi.fn(),
  }),
}));

import Sidebar from './Sidebar';

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar collapsed={false} onToggle={() => {}} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/');
});

describe('默认基础版下的侧边栏（阶段七十四 C · 默认模式翻转）', () => {
  it('默认不渲染「对比分析」这个术语入口', () => {
    renderSidebar();
    expect(screen.getByText('数据管理')).toBeInTheDocument();
    expect(screen.getByText('智能分析')).toBeInTheDocument();
    expect(screen.getByText('报表历史')).toBeInTheDocument();
    // 「对比分析」是行话，新手不认识——入口改到数据管理页的「对比这几份」
    expect(screen.queryByText('对比分析')).not.toBeInTheDocument();
  });

  it('?mode=pro 时「对比分析」入口回来', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderSidebar();
    expect(screen.getByText('对比分析')).toBeInTheDocument();
  });
});
