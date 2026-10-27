// 阶段七十四 · C（续）：默认模式从专业版翻成基础版后的两条规则。
// 反馈原话是「产品偏离初始定位——目标用户是 0 基础的普通人，现在复杂度偏高」。
// 默认基础版后，侧栏第一眼没有「对比分析」这个术语入口，
// 它改由数据管理页勾选 ≥2 份后的「对比这几份」进入；?mode=pro 或账号页切换可回专业版。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

describe('默认基础版下的侧边栏（阶段七十六 · 对比分析入口加回）', () => {
  it('默认仍渲染「对比分析」入口（阶段七十六按用户要求从基础版加回）', () => {
    renderSidebar();
    expect(screen.getByText('数据管理')).toBeInTheDocument();
    expect(screen.getByText('智能分析')).toBeInTheDocument();
    expect(screen.getByText('报表历史')).toBeInTheDocument();
    // C3 拍板：基础版也保留「对比分析」侧栏入口（与数据管理页「对比这几份」并存）
    expect(screen.getByText('对比分析')).toBeInTheDocument();
  });

  it('?mode=pro 时仍是全量入口', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderSidebar();
    expect(screen.getByText('对比分析')).toBeInTheDocument();
  });
});

// ---- 阶段八十二：专业版要有「显式入口」 ----
// 用户原话：「我想要一开始点进去是基础版，然后专门做一个专业版的入口」
// 之前切到专业版只有「账号设置 → 产品模式」里的两张卡，位置太深，
// 用户根本不知道还有专业版这回事。这两条锁住侧栏入口存在 + 真的会写模式。
describe('侧栏的专业版入口（阶段八十二）', () => {
  const 原location = window.location;
  let reloadSpy;

  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
    reloadSpy = vi.fn();
    // jsdom 的 location.reload 会真的尝试导航并报 "Not implemented"；
    // 这里换成可观测的桩。注意 search/href 必须用 getter 透传真实 location：
    // 取模式() 靠 window.location.search 读 ?mode=，若直接 {...原location} 展开
    // 会丢掉原型上的这些访问器，测试里 ?mode=pro 就失效了（踩过）。
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        get href() { return 原location.href; },
        get search() { return 原location.search; },
        get pathname() { return 原location.pathname; },
        get hash() { return 原location.hash; },
        get origin() { return 原location.origin; },
        reload: reloadSpy,
        assign: () => {},
        replace: () => {},
      },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', { configurable: true, value: 原location });
  });

  it('基础版侧栏显示「切换到专业版」入口', () => {
    renderSidebar();
    expect(screen.getByRole('button', { name: '切换到专业版' })).toBeInTheDocument();
  });

  it('点它写入 daa_mode=pro 并重载（下次进来就是专业版）', () => {
    renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: '切换到专业版' }));
    expect(localStorage.getItem('daa_mode')).toBe('pro');
    expect(reloadSpy).toHaveBeenCalled();
  });

  it('专业版不再显示这个入口（没有"再升一级"）', () => {
    window.history.replaceState({}, '', '/?mode=pro');
    renderSidebar();
    expect(screen.queryByRole('button', { name: '切换到专业版' })).not.toBeInTheDocument();
  });
});
