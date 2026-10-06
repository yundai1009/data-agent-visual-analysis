import { describe, expect, test } from 'vitest';
import { buildOption } from './EChartsChart';

// 阶段 33 修复回归测试：饼图"全 0.0% + 图例重复"bug。
// 场景：历史/异常报表把原始明细行当报表数据，值列取到文本或缺失 → value 全 0
// → 兜底为按名称计数，图例合并重复分类，占比可正常显示。

describe('EChartsChart buildOption · 饼图取值兜底', () => {
  test('值列全部无效（文本/缺失）时按名称计数合并', () => {
    // 模拟历史坏报表：数据是原始明细、值列是文本（Number→NaN→0）
    const opt = buildOption('pie', {
      X轴: '工作经验要求',
      Y轴: [],
      名称: '工作经验要求',
      值: '时间',
      数据: [
        { 工作经验要求: '一年以上', 时间: '2025年09月22日' },
        { 工作经验要求: '一年以上', 时间: '2025年09月23日' },
        { 工作经验要求: '五年以上', 时间: '2025年09月24日' },
      ],
    });
    const data = opt.series[0].data;
    // 兜底后：按名称计数，重复分类合并
    expect(data).toEqual([
      { name: '一年以上', value: 2 },
      { name: '五年以上', value: 1 },
    ]);
  });

  test('值列正常时不兜底，保持原值', () => {
    const opt = buildOption('pie', {
      X轴: '地区',
      Y轴: ['记录数'],
      名称: '地区',
      值: '记录数',
      数据: [
        { 地区: '华东', 记录数: 32 },
        { 地区: '华南', 记录数: 27 },
      ],
    });
    expect(opt.series[0].data).toEqual([
      { name: '华东', value: 32 },
      { name: '华南', value: 27 },
    ]);
  });

  test('空数据返回 null（组件层显示空状态）', () => {
    const opt = buildOption('pie', { X轴: 'x', Y轴: [], 数据: [] });
    expect(opt).toBeNull();
  });
});

// ---- Fix 4（阶段54-7）：标题超长渲染截断（前端展示兜底）----
describe('EChartsChart buildOption · 标题截断', () => {
  test('长标题（188 字需求原文）截断为 30 字 + 省略号，不铺满图形区', () => {
    const longTitle = '图表类型:饼图 请分析数据中各个类别的分布情况并给出详细建议和后续改进方向。'.repeat(3);
    expect(longTitle.length).toBeGreaterThan(100);
    const opt = buildOption('bar', {
      X轴: '地区', Y轴: ['销售额'], 标题: longTitle,
      数据: [{ 地区: '华东', 销售额: 100 }],
    });
    expect(opt.title.text.length).toBeLessThanOrEqual(31);
    expect(opt.title.text.endsWith('…')).toBe(true);
  });

  test('短标题保持原样不截断', () => {
    const opt = buildOption('bar', {
      X轴: '地区', Y轴: ['销售额'], 标题: '各地区销售额对比',
      数据: [{ 地区: '华东', 销售额: 100 }],
    });
    expect(opt.title.text).toBe('各地区销售额对比');
  });
});
// ---- 阶段55 修复：展示类编辑键真正生效（前后端契约对齐）----
describe('EChartsChart buildOption · 展示类编辑键消费', () => {
  const base = { X轴: '行业', Y轴: ['金额'], 数据: [{ 行业: 'A', 金额: 10 }, { 行业: 'B', 金额: 20 }] };

  test('子标题 → title.subtext', () => {
    const opt = buildOption('bar', { ...base, 标题: '主标题', 子标题: '副标题' });
    expect(opt.title.subtext).toBe('副标题');
  });

  test('X轴别名/Y轴别名 → 轴 name', () => {
    const opt = buildOption('bar', { ...base, X轴别名: '行业名称', Y轴别名: '金额(元)' });
    expect(opt.xAxis.name).toBe('行业名称');
    expect(opt.yAxis.name).toBe('金额(元)');
  });

  test('坐标范围 → yAxis min/max', () => {
    const opt = buildOption('bar', { ...base, 坐标范围: [0, 100] });
    expect(opt.yAxis.min).toBe(0);
    expect(opt.yAxis.max).toBe(100);
  });

  test('改系列颜色 → series itemStyle.color 生效', () => {
    const opt = buildOption('bar', { ...base, 系列颜色: ['#ff0000'] });
    expect(opt.series[0].itemStyle.color).toBe('#ff0000');
  });

  test('显示数据标签=false → label.show=false；true → true', () => {
    const off = buildOption('bar', { ...base, 显示数据标签: false });
    expect(off.series[0].label.show).toBe(false);
    const on = buildOption('bar', { ...base, 显示数据标签: true });
    expect(on.series[0].label.show).toBe(true);
  });

  test('改图例位置 → legend.top/bottom', () => {
    const opt = buildOption('bar', { ...base, 分组字段: '城市', 图例位置: 'top',
      数据: [{ 行业: 'A', 城市: 'X', 金额: 10 }, { 行业: 'B', 城市: 'Y', 金额: 20 }] });
    expect(opt.legend.top).toBe(0);
    expect(opt.legend.bottom).toBeUndefined();
  });

  test('改图例名称 → legend.data 用映射名', () => {
    const opt = buildOption('bar', { ...base, 分组字段: '城市', 图例名称: { X: '华东组', Y: '华南组' },
      数据: [{ 行业: 'A', 城市: 'X', 金额: 10 }, { 行业: 'B', 城市: 'Y', 金额: 20 }] });
    expect(opt.legend.data).toEqual(['华东组', '华南组']);
  });
});
