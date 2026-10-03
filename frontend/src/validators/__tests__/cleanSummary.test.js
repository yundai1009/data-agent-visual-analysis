// 阶段 52：清洗操作摘要可读化（原实现把原始 JSON 直出给用户）
import { describe, it, expect } from 'vitest';
import { 清洗摘要转文本 } from '../cleanSummary';

describe('清洗摘要转文本', () => {
  it('把 JSON 摘要转成中文可读描述，不含 JSON 语法', () => {
    const 摘要 = {
      去重: { 执行: true, 删除行数: 3 },
      填充缺失: { 执行: true, 策略: 'auto', 填充列数: 2 },
      删除空行: { 执行: true, 删除行数: 0 },
    };
    const text = 清洗摘要转文本(摘要);
    expect(text).toContain('去重：删除 3 行重复数据');
    expect(text).toContain('填充缺失：2 列');
    expect(text).toContain('删除空行：删除 0 行');
    expect(text).not.toMatch(/[{}\[\],"']/); // 不再直出 JSON
  });

  it('未执行的操作用"未执行"表述', () => {
    const 摘要 = { 去重: { 执行: false, 删除行数: 0 } };
    expect(清洗摘要转文本(摘要)).toContain('去重：未执行');
  });

  it('空值返回空串', () => {
    expect(清洗摘要转文本(null)).toBe('');
    expect(清洗摘要转文本(undefined)).toBe('');
  });
});