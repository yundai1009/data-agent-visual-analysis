// 阶段 52：vite dev 代理表回归——'/admin' 是页面路由，不能被代理前缀吞掉。
// 历史缺陷：代理键写成 '/admin'（前缀匹配），浏览器访问 /admin 页面被转发到
// 后端 spa_fallback，拿回构建产物 HTML（引用 /assets/*.js）→ vite dev 404 → 白屏。
// 本测试锁定：仅 '/admin/'（带斜杠）可进代理表；精确页面路径 /admin 决不允许代代理。
import { describe, it, expect } from 'vitest';
import { DEV_PROXY } from '../../dev-proxy';

describe('vite dev 代理表（阶段 52 回归）', () => {
  it('绝不能代理精确页面路由 /admin', () => {
    expect(DEV_PROXY).not.toHaveProperty('/admin');
  });

  it('API 前缀 /admin/ 必须存在（/admin/statistics 等走后端）', () => {
    expect(DEV_PROXY['/admin/']).toBe('http://127.0.0.1:8000');
  });

  it('代理键都不应是任何前端页面路由（防同类白屏回归）', () => {
    const pageRoutes = ['/data', '/analysis', '/report', '/dashboard', '/account', '/s'];
    for (const route of pageRoutes) {
      expect(DEV_PROXY).not.toHaveProperty(route);
    }
  });
});