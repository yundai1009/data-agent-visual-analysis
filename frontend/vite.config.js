// Vite 构建配置（面试讲解）
//
// 做了什么：前端开发/构建工具链配置——React 插件 + Tailwind v4 插件、
//   打包分 chunk（react 全家桶独立 vendor chunk 长缓存；echarts 保持
//   懒加载独立 chunk）、开发服务器把 /health /auth /datasets /reports
//   等 API 前缀代理到后端 127.0.0.1:8000（前端不跨域直连）。
// 为什么这样配置：调整 manualChunks 与 chunkSizeWarningLimit 是为
//   了控制首屏体积与缓存命中率（详见下方各注释）。
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss(), cspPlugin()],
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
      // F-S2 修复：补 4 个 dev 代理缺失，避免分享/看板/模板/定时任务 dev 环境 404
      '/share-data': 'http://127.0.0.1:8000',
      '/dashboards': 'http://127.0.0.1:8000',
      '/templates': 'http://127.0.0.1:8000',
      '/schedules': 'http://127.0.0.1:8000',
    },
  },
});

// F-M11 修复：在生产构建时注入 CSP meta。
// 仅 apply:'build' 生效：开发模式（vite dev）不注入，保证 HMR/React-refresh
// 的 inline script 与 ws 连接不受影响；生产 build 产出静态文件，CSP 严格约束
// 脚本/样式/请求来源，降低 XSS 与明文 Key 回归 RCE 风险。
function cspPlugin() {
  const CSP = [
    "default-src 'self'",
    "script-src 'self'",
    // Tailwind/echarts 需内联样式
    "style-src 'self' 'unsafe-inline'",
    // echarts 导出 dataURL 图片、头像等需 data:
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    // 注意：frame-ancestors 只能通过 HTTP 响应头生效，meta CSP 中会被浏览器忽略
    // 并打警告——如需防点击劫持，应在部署层（nginx/uvicorn 头）配置。
  ].join('; ');
  return {
    name: 'csp-inject',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace('<head>', `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
    },
  };
}
