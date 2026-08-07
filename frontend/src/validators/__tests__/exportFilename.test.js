import { describe, it, expect } from 'vitest';
import parseContentDispositionFilename from '../exportFilename';

describe('parseContentDispositionFilename', () => {
  it('RFC 5987 filename*=UTF-8 解码中文', () => {
    const cd = "attachment; filename=report.xlsx; filename*=UTF-8''%E9%94%80%E5%94%AE.xlsx";
    expect(parseContentDispositionFilename(cd, 'report.xlsx')).toBe('销售.xlsx');
  });

  it('无 filename*= 时回退 filename="..."', () => {
    expect(parseContentDispositionFilename('attachment; filename="报表.csv"', 'report.csv')).toBe('报表.csv');
  });

  it('无文件名头时用 fallback', () => {
    expect(parseContentDispositionFilename('', 'report.pdf')).toBe('report.pdf');
    expect(parseContentDispositionFilename(undefined, 'report.xlsx')).toBe('report.xlsx');
  });

  it('filename*= 内容无法解码时返回原样而非抛错', () => {
    const cd = "attachment; filename*=UTF-8''%ZZ%E4%B8%AD";
    expect(parseContentDispositionFilename(cd, 'x.pdf')).toBe(cd.match(/UTF-8''(.+)$/)[1]);
  });

  it('优先 RFC 5987（即使前面有普通 filename）', () => {
    const cd = "attachment; filename=old.csv; filename*=UTF-8''%E6%96%B0%E6%8E%92%E5%90%8D.csv";
    expect(parseContentDispositionFilename(cd, 'report.csv')).toBe('新排名.csv');
  });
});