// 阶段八十九 · B5：看板导出 PDF/图片 纯逻辑层测试（无 DOM，直接断言布局与 HTML 模板）。
import { describe, it, expect } from 'vitest';
import { 计算拼接尺寸, 构建打印HTML, 每图宽, 每图高, 图间距 } from '../utils/看板导出';

describe('看板导出 · 计算拼接尺寸', () => {
  it('单图：一张 640x400，无间隔', () => {
    const { 宽, 高, 格, 缩放 } = 计算拼接尺寸([{ w: 640, h: 400 }]);
    expect(宽).toBe(每图宽);
    expect(高).toBe(每图高);
    expect(格).toEqual([{ x: 0, y: 0 }]);
    expect(缩放).toBe(1); // 不超限：不缩放
  });

  it('三图：两列网格，第三张换行且垂直下移', () => {
    const { 宽, 高, 格 } = 计算拼接尺寸([{}, {}, {}]);
    expect(宽).toBe(2 * 每图宽 + 图间距);
    expect(高).toBe(2 * 每图高 + 图间距);
    expect(格[0]).toEqual({ x: 0, y: 0 });
    expect(格[1]).toEqual({ x: 每图宽 + 图间距, y: 0 });
    expect(格[2]).toEqual({ x: 0, y: 每图高 + 图间距 });
  });

  it('空列表：至少返回一张的占位尺寸，不抛错', () => {
    const { 宽, 高 } = 计算拼接尺寸([]);
    expect(宽).toBe(每图宽);
    expect(高).toBe(每图高);
  });

  it('行高取最大，换行用行高而非单图高（高低图混排不错位）', () => {
    const { 高, 格 } = 计算拼接尺寸([{ w: 640, h: 500 }, {}], 1);
    expect(高).toBe(500 + 每图高 + 图间距);
    expect(格[1].y).toBe(500 + 图间距);
  });

  it('阶段九十 R10：超大画布自动等比降采样（不抛错、不静默黑图）', () => {
    // 100 张图两列 → 原高 100/2*400 + 间隔 ≈ 20000px，远超 8192 单边上限
    const { 宽, 高, 缩放, 格 } = 计算拼接尺寸(Array.from({ length: 100 }, () => ({ w: 640, h: 400 })));
    expect(缩放).toBeLessThan(1);
    expect(高).toBeLessThanOrEqual(8192);
    expect(宽).toBeLessThanOrEqual(8192);
    // 缩放后坐标仍落在画布内（最后一张的 y 不越界）
    expect(格[99].y).toBeLessThan(高);
    // 像素总量不超上限（约 80MB RGBA 的硬顶）
    expect(宽 * 高).toBeLessThanOrEqual(20000000 * 1.001);
  });
});

describe('看板导出 · 构建打印HTML', () => {
  it('空卡片也生成含标题与零图统计的完整文档', () => {
    const html = 构建打印HTML({ 看板名: '销售月报', 卡片: [], 生成时间: '2026-01-01 12:00' });
    expect(html).toContain('<title>销售月报 · 看板导出</title>');
    expect(html).toContain('<h1>销售月报</h1>');
    expect(html).toContain('共 0 张图表');
  });

  it('把每张图渲染成 <img>（dataURL 原样内联，白底不透明）', () => {
    const html = 构建打印HTML({
      看板名: '看板A',
      卡片: [{ 标题: '柱状图', 类型: 'bar', 结论: '华南最高', dataURL: 'data:image/png;base64,abc' }],
    });
    expect(html).toContain('data:image/png;base64,abc');
    expect(html).toContain('柱状图');
    expect(html).toContain('结论：华南最高');
    expect(html).toContain('background: #fff');
  });

  it('没有 dataURL 的卡片被过滤（表格类报表不混进 PDF）', () => {
    const html = 构建打印HTML({
      看板名: 'B',
      卡片: [{ 标题: '表格', 类型: 'table', dataURL: '' }, { 标题: '饼图', 类型: 'pie', dataURL: 'data:image/png;base64,x' }],
    });
    expect(html).not.toContain('表格');
    expect(html).toContain('饼图');
    expect(html).toContain('共 1 张图表');
  });

  it('标题/结论里的 HTML 被转义（用户文本不注入）', () => {
    const html = 构建打印HTML({
      看板名: '<script>alert(1)</script>',
      卡片: [{ 标题: 'a<b>', 结论: 'c"d', dataURL: 'data:image/png;base64,z' }],
    });
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('a&lt;b&gt;');
    expect(html).toContain('c&quot;d');
  });
});
