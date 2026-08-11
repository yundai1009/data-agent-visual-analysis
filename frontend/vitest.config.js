import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端组件测试：jsdom 环境 + jest-dom matchers + globals（describe/it/expect）
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx,ts,tsx}'],
  },
});
