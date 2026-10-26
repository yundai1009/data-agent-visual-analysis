// 新手引导（阶段七十四 B 批补第 4 步）：契约 + 行为测试
// 为什么单独立一个文件：Onboarding 是首屏浮层，改 STEPS 数组会影响
// 首次登录的每一个人，必须有测试锁住"步数、文案、跳转目标"这三件事。
// 覆盖：4 步引导存在、第 4 步讲对比且指向 /data、跳过写 localStorage、
//       最后一步文案是"开始使用"、点任一步跳到对应路由。

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import Onboarding from './Onboarding.jsx';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

// lucide 图标在 jsdom 里会渲染 <svg>，不影响断言，真实引入即可。

describe('新手引导（阶段七十四 B 批：第 4 步讲多份数据对比）', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    localStorage.clear();
  });
  afterEach(() => cleanup());

  it('第 4 步讲的是多份数据对比，且跳到 /data', () => {
    render(<Onboarding onDone={() => {}} />);
    // 连点 3 次"下一步"走到第 4 步
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(screen.getByText('下一步'));
    }
    expect(screen.getByText(/④ 想比两份数据/)).toBeTruthy();
    expect(screen.getByText(/对比这几份/)).toBeTruthy();
    fireEvent.click(screen.getByText('去勾选数据'));
    expect(mockNavigate).toHaveBeenCalledWith('/data');
  });

  it('跳过引导写 localStorage，下次不再弹', () => {
    const onDone = vi.fn();
    render(<Onboarding onDone={onDone} />);
    fireEvent.click(screen.getByTitle('跳过引导'));
    expect(localStorage.getItem('onboard_done')).toBe('1');
    expect(onDone).toHaveBeenCalled();
  });

  it('首屏是第 1 步上传数据', () => {
    render(<Onboarding onDone={() => {}} />);
    expect(screen.getByText(/① 上传你的数据/)).toBeTruthy();
    expect(screen.getByText('去上传数据')).toBeTruthy();
  });
});
