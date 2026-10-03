// 阶段 53 · C9：结论附数据依据（前端从报表聚合数据计算"合计/最高分组/占比"，
// 让结论可被数据验证，而不是只听 AI 一句话）
import { describe, it, expect } from 'vitest';
import { 计算数据依据 } from '../结论依据';

describe('计算数据依据（阶段 53 · C9）', () => {
  it('无数据 → 空数组（不渲染多余卡片）', () => {
    expect(计算数据依据([])).toEqual([]);
    expect(计算数据依据(null)).toEqual([]);
    expect(计算数据依据(undefined)).toEqual([]);
  });

  it('全是非数值列 → 空数组（无法求合计占比）', () => {
    expect(计算数据依据([{ 名称: 'a' }, { 名称: 'b' }])).toEqual([]);
  });

  it('正常数据：给出分组数、合计、最高分组及其占比', () => {
    const rows = [
      { 地区: '杭州', 销售额: 30 },
      { 地区: '上海', 销售额: 70 },
    ];
    const out = 计算数据依据(rows);
    expect(out[0]).toContain('2');
    expect(out[0]).toContain('合计 100');
    expect(out[1]).toContain('上海');
    expect(out[1]).toContain('70');
    expect(out[1]).toContain('70.0%');
  });

  it('大数用千分位格式化（避免科学计数法吓到用户）', () => {
    const rows = [
      { 地区: '华东', 销售额: 1234567 },
      { 地区: '华北', 销售额: 765433 },
    ];
    const out = 计算数据依据(rows);
    expect(out[0]).toContain('2,000,000');
    expect(out[1]).toContain('1,234,567');
  });

  it('最高并列取第一条也能正常计算', () => {
    const rows = [
      { 城市: 'A', 值: 5 },
      { 城市: 'B', 值: 5 },
    ];
    const out = 计算数据依据(rows);
    expect(out[1]).toContain('A');
    expect(out[1]).toContain('50.0%');
  });

  it('多数值列：只用第一列做合计（聚合报表通常单数值列）', () => {
    const rows = [
      { 月份: '1月', 销量: 10, 退货: 2 },
      { 月份: '2月', 销量: 20, 退货: 3 },
    ];
    const out = 计算数据依据(rows);
    expect(out[0]).toContain('合计 30');
    expect(out[1]).toContain('2月');
  });
});