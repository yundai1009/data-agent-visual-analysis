import { render, screen } from '@testing-library/react';
import App from './App';

// 阶段 33 修复的 P0 回归测试：App() 顶层曾直接在 AppProvider 外调用 useApp()，
// context 为 null 导致解构 isAuthed 抛错、整页白屏。此测试确保根组件可渲染。
test('渲染 App 根组件不抛错（useApp 必须在 Provider 内调用）', () => {
  expect(() => render(<App />)).not.toThrow();
  // 懒加载首屏至少出现加载占位（路由已挂载）
  expect(screen.getByText('加载中…')).toBeInTheDocument();
});