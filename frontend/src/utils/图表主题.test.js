import { describe, expect, test } from 'vitest';
import { COLORS, 转义HTML } from './图表主题';

describe('图表主题 · 阶段 六十', () => {
  test('色板是 8 色藏青系且与 EChartsChart 旧常量一致', () => {
    expect(COLORS).toEqual(['#0f4c81', '#3d7bb8', '#5b8cb8', '#8aa9c4', '#b45309', '#0f766e', '#64748b', '#334155']);
  });

  test('转义HTML 覆盖 5 个危险字符，null/undefined 不炸', () => {
    expect(转义HTML('<img src=x onerror=alert(1)>'))
      .toBe('&lt;img src=x onerror=alert(1)&gt;');
    expect(转义HTML(`a&b"c'd`)).toBe('a&amp;b&quot;c&#39;d');
    expect(转义HTML(undefined)).toBe('');
    expect(转义HTML(null)).toBe('');
  });
});
