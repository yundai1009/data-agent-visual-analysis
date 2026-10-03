// dev 代理表（纯数据模块：vite.config.js 与单测共用，避免在 vitest 里 import vite.config）
//
// 阶段 52 修复（P2）：'/admin' 是**页面路由**，'/admin/xxx' 才是后端 API。
// 原来代理键写 '/admin'（前缀匹配），浏览器访问 /admin 页面也被转发到
// 后端 spa_fallback，拿回**构建产物** index.html（引用 /assets/*.js），
// 而 vite dev 不提供这些文件 → 404 → 管理端页面稳定白屏。
// 改为 '/admin/'：精确前缀匹配仅拦截 /admin/statistics、/admin/users 等
// 真实 API；页面 /admin 不再被代理，交给 vite dev 的 SPA fallback 渲染。
export const DEV_PROXY = {
  '/health': 'http://127.0.0.1:8000',
  '/auth': 'http://127.0.0.1:8000',
  '/datasets': 'http://127.0.0.1:8000',
  '/reports': 'http://127.0.0.1:8000',
  '/clean': 'http://127.0.0.1:8000',
  '/examples': 'http://127.0.0.1:8000',
  '/admin/': 'http://127.0.0.1:8000',
  '/feedback': 'http://127.0.0.1:8000',
  // F-S2 修复：补 4 个 dev 代理缺失，避免分享/看板/模板/定时任务 dev 环境 404
  '/share-data': 'http://127.0.0.1:8000',
  '/dashboards': 'http://127.0.0.1:8000',
  '/templates': 'http://127.0.0.1:8000',
  '/schedules': 'http://127.0.0.1:8000',
}