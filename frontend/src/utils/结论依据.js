/**
 * 阶段 53 · C9：结论附数据依据。
 *
 * 动机（用户视角）：报表页只给一句"分析结论"，用户无法验证 AI 是不是
 * 拍脑袋。这里从报表的聚合数据（chartConfig.数据：[{分类, 数值}]）算出
 * "共 N 个分组 / 合计 X / 最高是 Y 占 Z%"，贴在结论下方，让结论可核对。
 *
 * 纯函数，无副作用；数据异常一律返回空数组（宁可没有依据，不要错依据）。
 */

/** 千分位格式化；非有限数回退为 0 */
function 格式化数值(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

export function 计算数据依据(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return [];
  const first = rows[0];
  if (!first || typeof first !== 'object') return [];

  const 列名 = Object.keys(first);
  if (列名.length === 0) return [];

  // 只认"每行都是数值"的列；文本/混合列直接排除（宁可少说，不可说错）
  const 数值列 = 列名.filter((k) => rows.every((r) => typeof r?.[k] === 'number' && Number.isFinite(r[k])));
  if (数值列.length === 0) return [];

  const 数值键 = 数值列[0];
  const 分类键 = 列名.find((k) => k !== 数值键) || null;
  const 合计 = rows.reduce((s, r) => s + (Number(r[数值键]) || 0), 0);

  const 依据 = [];
  依据.push(`共 ${rows.length} 个${分类键 ?? '分组'}，合计 ${格式化数值(合计)}`);

  const 最大行 = rows.reduce((a, b) => ((Number(b[数值键]) || 0) > (Number(a[数值键]) || 0) ? b : a));
  const 最大值 = Number(最大行[数值键]) || 0;
  const 占比 = 合计 ? (最大值 / 合计) * 100 : 0;
  const 最大名 = 分类键 ? String(最大行[分类键] ?? '') : '';
  依据.push(
    `${最大名 ? `最高：${最大名}，` : '最高值，'}${格式化数值(最大值)}`
    + `（占 ${占比.toFixed(1)}%）`,
  );
  return 依据;
}