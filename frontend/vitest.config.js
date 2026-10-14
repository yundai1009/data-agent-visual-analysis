// ============================================================================
// 【文件定位】前端单元/组件测试的 vitest 配置（与 vite.config.js 分开：构建配置
//            不该掺测试插件，且 vitest 自己的 defineConfig 才有 test 字段类型）。
// 【做了什么】只做三件事：jsdom 环境、globals（省掉每个文件 import describe/it/expect）、
//            加载 src/test/setup.js 注册 jest-dom 匹配器（toBeInTheDocument 等）。
// 【为什么这么做】
//   - 测试**不引入** vite.config.js 里的开发代理/构建插件：测试里发请求应当被
//     mock（各测试文件自行 vi.mock('../api')），而不是真的打到 127.0.0.1:8000，
//     否则 CI 上没起后端就会红成一片、且测试之间互相污染。
//   - globals: true 是为了让测试文件与 jest 风格一致、少一行样板。
// 【关键约定与坑】
//   - 跑测试必须 `cd frontend` 再 `npx vitest run`：配置里的 include/setupFiles
//     都是相对本文件所在目录解析，在仓库根跑会一个用例都收不到（静默 0 测试通过）。
//   - include 只认 `src/**/*.test.{js,jsx,ts,tsx}`——新增测试文件若放在 src 之外
//     不会被收集，这种漏测不报错，所以别把测试挪出 src。
//   - node_modules 已随仓库安装好，**不要主动 npm install**（会改 lockfile 版本）。
// ============================================================================
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
