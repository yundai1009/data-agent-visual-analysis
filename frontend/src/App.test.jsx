import { render, screen, waitFor } from '@testing-library/react';
import App from './App';

// 阶段 33 修复的 P0 回归测试：App() 顶层曾直接在 AppProvider 外调用 useApp()，
// context 为 null 导致解构 isAuthed 抛错、整页白屏。此测试确保根组件可渲染。
test('渲染 App 根组件不抛错（useApp 必须在 Provider 内调用）', () => {
  expect(() => render(<App />)).not.toThrow();
  // 懒加载首屏至少出现加载占位（路由已挂载）
  expect(screen.getByText('加载中…')).toBeInTheDocument();
});

// ---- Fix 3（阶段54-7）：窄屏侧边栏默认折叠 ----
// 说明：侧边栏只在受保护页面的应用壳里渲染（/login 是独立布局无侧边栏），
// 因此测试需先造登录态（localStorage access_token）再渲染。
function withAuthedSetup(fn) {
  localStorage.setItem('access_token', 'test-token');
  localStorage.setItem('onboard_done', '1');
  try {
    fn();
  } finally {
    localStorage.removeItem('access_token');
    localStorage.removeItem('onboard_done');
  }
}

test('Fix3 窄屏(375px)侧边栏默认折叠为窄栏 w-14，不再占屏过半', () => {
  // 重置路由到 "/"：前序测试的 <Navigate replace> 会把 jsdom history 停在 /login
  // （独立布局无侧边栏），不重置则后续用例测不到应用壳。
  window.history.pushState({}, '', '/');
  // jsdom 默认 innerWidth=1024；mock 成 375 模拟手机视口
  const originalWidth = window.innerWidth;
  Object.defineProperty(window, 'innerWidth', { value: 375, configurable: true, writable: true });
  withAuthedSetup(() => {
    const { container } = render(<App />);
    const aside = container.querySelector('aside');
    expect(aside).not.toBeNull();
    expect(aside.className).toContain('w-14');
    expect(aside.className).not.toContain('w-52');
  });
  Object.defineProperty(window, 'innerWidth', { value: originalWidth, configurable: true, writable: true });
});

test('Fix3 宽屏(1280px)侧边栏默认展开 w-52（原有桌面行为不变）', () => {
  window.history.pushState({}, '', '/');
  const originalWidth = window.innerWidth;
  Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true, writable: true });
  withAuthedSetup(() => {
    const { container } = render(<App />);
    const aside = container.querySelector('aside');
    expect(aside.className).toContain('w-52');
    expect(aside.className).not.toContain('w-14');
  });
  Object.defineProperty(window, 'innerWidth', { value: originalWidth, configurable: true, writable: true });
});

// ---- Fix 5（阶段54-7）：根路径 / 重定向 /data（不再渲染 404 页）----
test('Fix5 访问根路径 "/" 重定向 /data（未登录继续跳登录页，不出现 404）', async () => {
  window.history.pushState({}, '', '/');
  render(<App />);
  // 回归锁定：修复前 "/" 落到内层 path="*" → NotFound（应用壳 + 404 页）
  await waitFor(() => {
    expect(screen.queryByText('页面走丢了')).not.toBeInTheDocument();
  });
  // 未登录时 "/"→/data→ProtectedRoute→/login（/data 受保护继续跳登录页）
  expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument();
});
