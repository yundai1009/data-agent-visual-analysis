import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // echarts(≈647KB) 是 EChartsChart 内动态 import 的懒加载 chunk，仅报表页用到时加载；
    // 阈值声明为 800 免除噪音警告（该 chunk 不出现在登录/数据管理首屏）。
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        // react 全家桶独立 vendor chunk：浏览器可长缓存，页面级懒加载 chunk 间共享不重复
        // （rolldown 的 manualChunks 仅支持函数形式）
        manualChunks(id) {
          if (/node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/.test(id)) {
            return 'react-vendor';
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/datasets': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/clean': 'http://127.0.0.1:8000',
      '/examples': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/feedback': 'http://127.0.0.1:8000',
    },
  },
})
