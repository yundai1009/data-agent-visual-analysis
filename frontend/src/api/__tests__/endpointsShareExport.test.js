/**
 * 阶段 52 回归测试：api/endpoints.js 导出/分享接口的运行时崩溃。
 *
 * 缺陷背景：api.js 拆分到 endpoints.js 时漏了 import 三个符号——
 *   REQUEST_TIMEOUT_MS / handleAuthExpired（request.js 导出）
 *   parseContentDispositionFilename（validators/exportFilename.js default 导出）
 * 这三个符号只在函数体内被引用，Vite 构建与 oxlint 都不报，运行时才炸：
 *   - 导出 Excel/CSV → "导出失败：REQUEST_TIMEOUT_MS is not defined"
 *   - 导出 PDF 完整报告 → 同上
 *   - 打开分享链接 → "REQUEST_TIMEOUT_MS is not defined"（分享页整体不可用）
 *   - 合规导出我的数据 → parseContentDispositionFilename is not defined
 *
 * 这些测试直接调用真实实现（只 mock fetch），保证"调用即不崩"。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  exportReport,
  exportFullReport,
  getSharedReport,
  exportUserData,
} from '../endpoints';

function mockFetchOnce(impl) {
  const fn = vi.fn(impl);
  globalThis.fetch = fn;
  return fn;
}

function blobResponse(body = 'x', headers = {}) {
  return {
    ok: true,
    status: 200,
    headers: { get: (k) => headers[k.toLowerCase()] ?? null },
    blob: async () => new Blob([body]),
    json: async () => JSON.parse(body),
  };
}

describe('阶段52：endpoints.js 导出/分享接口不得运行时崩溃', () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    try {
      localStorage.setItem('access_token', 'test-token');
    } catch { /* ignore */ }
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('exportReport(xlsx) 正常返回 blob 与后端文件名（不抛 ReferenceError）', async () => {
    mockFetchOnce(async () => blobResponse('xlsx-bytes', {
      'content-disposition': "attachment; filename*=UTF-8''%E9%94%80%E5%94%AE.xlsx",
    }));
    const res = await exportReport('rep-1', 'xlsx');
    expect(res.filename).toBe('销售.xlsx');
    expect(res.blob).toBeInstanceOf(Blob);
  });

  it('exportFullReport(pdf) 正常返回（此前同样引用未导入的超时常量）', async () => {
    mockFetchOnce(async () => blobResponse('pdf-bytes', {
      'content-disposition': "attachment; filename*=UTF-8''%E6%8A%A5%E8%A1%A8.pdf",
    }));
    const res = await exportFullReport('rep-1', 'data:image/png;base64,AAA');
    expect(res.filename).toBe('报表.pdf');
  });

  it('getSharedReport 正常返回报表数据（分享页此前整体白屏报错）', async () => {
    mockFetchOnce(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ 标题: '测试报表', 图表配置: { 类型: 'bar' } }),
    }));
    const res = await getSharedReport('share-1');
    expect(res.标题).toBe('测试报表');
  });

  it('getSharedReport 404 时抛中文错误而不是内部变量名', async () => {
    mockFetchOnce(async () => ({
      ok: false,
      status: 404,
      json: async () => ({}),
    }));
    await expect(getSharedReport('missing')).rejects.toThrow('分享链接不存在或已过期');
  });

  it('getSharedReport 401 保留后端 message（需要访问密码 vs 访问密码不正确）【阶段 53 · A3】', async () => {
    // 未带密码：后端 message = 需要访问密码
    mockFetchOnce(async () => ({
      ok: false,
      status: 401,
      json: async () => ({ message: '需要访问密码', code: 'HTTP_401' }),
    }));
    await expect(getSharedReport('share-pwd')).rejects.toThrow('需要访问密码');

    // 带密码但错误：后端 message = 访问密码不正确 —— 前端必须拿到区分信息，
    // 才能做到"首次打开不指责密码不对，输错才提示"
    mockFetchOnce(async () => ({
      ok: false,
      status: 401,
      json: async () => ({ message: '访问密码不正确', code: 'HTTP_401' }),
    }));
    await expect(getSharedReport('share-pwd', 'wrong')).rejects.toThrow('访问密码不正确');
  });

  it('getSharedReport 429 限频提示（防暴破状态可感知）', async () => {
    mockFetchOnce(async () => ({
      ok: false,
      status: 429,
      json: async () => ({ message: '尝试次数过多，请稍后再试' }),
    }));
    await expect(getSharedReport('share-pwd', 'x')).rejects.toThrow('尝试次数过多，请稍后再试');
  });

  it('exportUserData 用 Content-Disposition 解析文件名（未导入解析器会崩）', async () => {
    mockFetchOnce(async () => blobResponse('json-bytes', {
      'content-disposition': "attachment; filename*=UTF-8''%E6%88%91%E7%9A%84%E6%95%B0%E6%8D%AE.json",
    }));
    const res = await exportUserData();
    expect(res.filename).toBe('我的数据.json');
  });

  it('exportReport 401 走全局登出（handleAuthExpired 未导入会崩）', async () => {
    const fired = vi.fn();
    window.addEventListener('auth:expired', fired);
    mockFetchOnce(async () => ({ ok: false, status: 401, json: async () => ({}) }));
    await expect(exportReport('rep-1', 'xlsx')).rejects.toThrow(/HTTP 401/);
    expect(fired).toHaveBeenCalled();
    window.removeEventListener('auth:expired', fired);
  });
});