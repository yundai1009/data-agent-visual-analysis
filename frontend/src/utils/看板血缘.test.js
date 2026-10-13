// 阶段 六十：看板血缘纯函数测试（不碰 DOM、不碰 echarts）
import { describe, expect, test } from 'vitest';
import { 提取图表字段, 构建血缘图, 构建血缘Option } from './看板血缘';

// listDatasets(200) 列表项
const 数据集列表 = [
  { 数据集ID: 'd1', 文件名: '销售.csv', 行数: 120, 列数: 5 },
  { 数据集ID: 'd2', 文件名: '库存.csv', 行数: 30, 列数: 2 },
];

// getDashboard(id).报表列表 —— 注意：列表项里【没有】数据集ID（dashboards.py:73-79）
const 看板报表列表 = [
  {
    报表ID: 'r1',
    标题: '各区域销售额',
    图表类型: 'bar',
    创建时间: '2026-10-01',
    报表: { 结论: '华东最高', 图表配置: { 类型: 'bar', X轴: '区域', Y轴: ['销售额'], 颜色: '城市', 数据: [{ 区域: '华东', 销售额: 100, 城市: '上海' }] } },
  },
  {
    报表ID: 'r2',
    标题: '各区域销量',
    图表类型: 'line',
    创建时间: '2026-10-02',
    报表: { 结论: '与销售额同向', 图表配置: { 类型: 'line', X轴: '区域', Y轴: ['销量'], 数据: [{ 区域: '华东', 销量: 8 }] } },
  },
  {
    报表ID: 'r3',
    标题: '库存结构',
    图表类型: 'pie',
    创建时间: '2026-10-03',
    报表: { 结论: '长尾明显', 图表配置: { 类型: 'pie', 名称: '类别', 值: '数量', 数据: [{ 类别: 'A', 数量: 3 }] } },
  },
];

// listReports(100) 列表项 —— 含数据集ID
const 报表列表 = [
  { 报表ID: 'r1', 数据集ID: 'd1', 标题: '各区域销售额', 图表类型: 'bar' },
  { 报表ID: 'r2', 数据集ID: 'd1', 标题: '各区域销量', 图表类型: 'line' },
  { 报表ID: 'r3', 数据集ID: 'd2', 标题: '库存结构', 图表类型: 'pie' },
  { 报表ID: 'r9', 数据集ID: 'd1', 标题: '历史报表（未入本看板）', 图表类型: 'bar' },
];

const 建索引 = (键, 列) => new Map(列.map((r) => [r[键], r]));
const 图 = (报表 = 看板报表列表, 索引 = 报表列表) => 构建血缘图({
  报表列表: 报表,
  报表索引: 建索引('报表ID', 索引),
  数据集索引: 建索引('数据集ID', 数据集列表),
});

describe('提取图表字段', () => {
  test('抽出 X轴/Y轴/分组 并记角色', () => {
    expect(提取图表字段({
      类型: 'bar', X轴: '区域', Y轴: ['销售额'], 颜色: '城市',
      数据: [{ 区域: '华东', 销售额: 100, 城市: '上海' }],
    })).toEqual([
      { 字段名: '区域', 角色: ['X轴'] },
      { 字段名: '销售额', 角色: ['Y轴'] },
      { 字段名: '城市', 角色: ['分组'] },
    ]);
  });

  test('丢弃 boxplot 的哨兵值 name/value（report_generator.py:986-988）', () => {
    const 字段 = 提取图表字段({
      类型: 'boxplot', X轴: '日期', 名称: 'name', 值: 'value',
      数据: [{ 日期: '2026-01', 下限: 1, 上限: 9 }],
    });
    expect(字段.map((f) => f.字段名)).toEqual(['日期']);
    expect(字段.map((f) => f.字段名)).not.toContain('name');
    expect(字段.map((f) => f.字段名)).not.toContain('value');
  });

  test('老报表 数据 为空时不做白名单校验，仍能抽字段', () => {
    expect(提取图表字段({ 类型: 'bar', X轴: '区域', Y轴: ['销售额'] }))
      .toEqual([{ 字段名: '区域', 角色: ['X轴'] }, { 字段名: '销售额', 角色: ['Y轴'] }]);
  });

  test('空配置返回空数组，不抛', () => {
    expect(提取图表字段(undefined)).toEqual([]);
    expect(提取图表字段({})).toEqual([]);
  });

  // ---- 预检 ②-8 的两个边界输入（计划没覆盖，这里补死行为）----

  test('数据首行为 null 时降级为不做白名单校验（不因脏数据整张图丢字段）', () => {
    expect(提取图表字段({ 类型: 'bar', X轴: '区域', Y轴: ['销售额'], 数据: [null] }))
      .toEqual([{ 字段名: '区域', 角色: ['X轴'] }, { 字段名: '销售额', 角色: ['Y轴'] }]);
  });

  test('数据列名带首尾空格时，键 trim 后仍能匹配上（Excel 表头空格很常见）', () => {
    expect(提取图表字段({ 类型: 'bar', X轴: ' 区域 ', Y轴: ['销售额'], 数据: [{ '区域 ': 1, 销售额: 2 }] }))
      .toEqual([{ 字段名: '区域', 角色: ['X轴'] }, { 字段名: '销售额', 角色: ['Y轴'] }]);
  });

  // ---- 对照测试（预检修正 · 哨兵黑名单语义）----

  test('对照①：boxplot 的数据行就是 {name,value} → 白名单失效，X轴/颜色 等真实字段照留、name/value 照丢', () => {
    const 配置 = {
      类型: 'boxplot', X轴: '日期', 颜色: '地区', 名称: 'name', 值: 'value',
      数据: [{ name: 'A组', value: [1, 2, 3] }],
    };
    const 字段名 = 提取图表字段(配置).map((f) => f.字段名);
    expect(字段名).toEqual(['日期', '地区']);   // 用户真实选择（report_generator.py:965-966）不能被白名单清空
    expect(字段名).not.toContain('name');
    expect(字段名).not.toContain('value');
  });

  // 【已知取舍，不是认可该行为】`every` 判定下混合形状 → 数据键是角色名为 false，白名单恢复生效，
  // 于是 name 这个角色名又被当成真实字段留下。原先「后端不产生混合形状」这个前提已被审查证伪
  // （图表配置取自请求参数，reports.py:1084 的历史重放会把旧配置打到新数据集上）。
  // 本例的职责是把「跳过白名单 / 校验白名单」这个分支钉死，防止后人重构时静默翻转；
  // 而 bar/line 里真实列就叫 name 时保留 name 恰恰是正确语义，两种情况无法靠本函数区分。
  test('【已知取舍】混合形状（数据行既有角色名又有真实列）→ 白名单恢复生效，按数据行键校验', () => {
    expect(提取图表字段({
      类型: 'bar', X轴: '地区', 名称: 'name',
      数据: [{ name: 'A', 地区: '华东' }],
    })).toEqual([
      { 字段名: '地区', 角色: ['X轴'] },   // 真实列：数据行里有 → 留下
      { 字段名: 'name', 角色: ['名称'] }, // 已知残留：白名单恢复 → name 重新被当成字段
    ]);
    // 白名单确实恢复生效：数据行里没有的脏列名仍被丢弃
    expect(提取图表字段({
      类型: 'bar', X轴: '已删除的列', 名称: 'name',
      数据: [{ name: 'A', 地区: '华东' }],
    }).map((f) => f.字段名)).toEqual(['name']);
  });

  test('对照②：waterfall/candlestick/wordcloud 的 name/value 同样被排除', () => {
    const 样例 = [
      ['waterfall', [{ name: 'A', value: 1 }]],
      ['candlestick', [{ name: 'A', value: [1, 2, 3, 4] }]],
      ['wordcloud', [{ name: 'Python', value: 12 }]],
    ];
    样例.forEach(([类型, 数据]) => {
      const 字段名 = 提取图表字段({ 类型, 名称: 'name', 值: 'value', 数据 }).map((f) => f.字段名);
      expect(字段名, `${类型} 不应产出占位字段`).toEqual([]);
    });
  });

  test('对照③：sunburst 的 名称/value、sankey 的 源/value 被排除', () => {
    expect(提取图表字段({
      类型: 'sunburst', 名称: '名称', 值: 'value',
      数据: [{ 层级: 'L1', 名称: 'A', value: 3 }],
    }).map((f) => f.字段名)).toEqual([]);
    expect(提取图表字段({
      类型: 'sankey', 名称: '源', 值: 'value',
      数据: [{ 源: 'A', 目标: 'B', value: 5 }],
    }).map((f) => f.字段名)).toEqual([]);
  });

  test('对照④：pie/donut/funnel 的 名称/值 是真实列名，必须保留', () => {
    expect(提取图表字段({
      类型: 'pie', 名称: '地区', 值: '销售额',
      数据: [{ 地区: '华东', 销售额: 100 }],
    }).map((f) => f.字段名)).toEqual(['地区', '销售额']);
    expect(提取图表字段({
      类型: 'funnel', 名称: '地区', 值: '销售额',
      数据: [{ 地区: '华东', 销售额: 100 }],
    }).map((f) => f.字段名)).toEqual(['地区', '销售额']);
  });

  test('对照⑤：白名单没被黑名单取代——配置里写了数据里没有的列名仍被丢弃', () => {
    expect(提取图表字段({
      类型: 'bar', X轴: '不存在的列', Y轴: ['销售额'],
      数据: [{ 区域: '华东', 销售额: 100 }],
    })).toEqual([{ 字段名: '销售额', 角色: ['Y轴'] }]);
    // pie 的 名称/值 是真实列名 → 数据键不是角色名，白名单对它照常生效（别被新分支误伤）
    expect(提取图表字段({
      类型: 'pie', 名称: '地区', 值: '不存在的列',
      数据: [{ 地区: '华东', 销售额: 100 }],
    })).toEqual([{ 字段名: '地区', 角色: ['名称'] }]);
  });

  test('非聚合类型但数据行键恰为 {name,value}（脏数据/旧配置）→ 白名单跳过，占位名仍被黑名单挡掉', () => {
    const 字段 = 提取图表字段({
      类型: 'bar', X轴: '旧字段', 名称: 'Name', 值: 'VALUE',
      数据: [{ name: 'A', value: 1 }],
    });
    const 字段名 = 字段.map((f) => f.字段名);
    expect(字段名).toEqual(['旧字段']);   // 白名单失效 → 真实字段不被误杀
    expect(字段名).not.toContain('Name');  // 大小写兼容：占位名仍要挡
    expect(字段名).not.toContain('VALUE');
    expect(字段名.map((s) => s.toLowerCase())).not.toContain('name');
    expect(字段名.map((s) => s.toLowerCase())).not.toContain('value');
  });
});

describe('构建血缘图', () => {
  test('三层节点：2 数据集 + 3 报表 + 1 个复用字段', () => {
    const g = 图();
    expect(g.节点.filter((n) => n.类型 === '数据集')).toHaveLength(2);
    expect(g.节点.filter((n) => n.类型 === '报表')).toHaveLength(3);
    // 只有「区域」被 2 张报表引用 → 只有它成节点
    expect(g.节点.filter((n) => n.类型 === '字段').map((n) => n.字段名)).toEqual(['区域']);
    expect(g.统计.高价值字段).toEqual([
      expect.objectContaining({ 字段名: '区域', 数据集名: '销售.csv', 报表数: 2 }),
    ]);
    expect(g.统计.报表数).toBe(3);
    expect(g.统计.数据集数).toBe(2);
  });

  test('连线：3 条归属 + 2 条引用', () => {
    const g = 图();
    expect(g.连线.filter((l) => l.类型 === '归属')).toHaveLength(3);
    expect(g.连线.filter((l) => l.类型 === '引用')).toHaveLength(2);
    expect(g.连线.find((l) => l.类型 === '引用')).toMatchObject({ 起点: 'rp:r1', 终点: 'fd:d1::区域' });
  });

  test('只被 1 张报表引用的字段（销售额/销量/类别）不建节点', () => {
    const 字段名们 = 图().节点.filter((n) => n.类型 === '字段').map((n) => n.字段名);
    expect(字段名们).not.toContain('销售额');
    expect(字段名们).not.toContain('销量');
    expect(字段名们).not.toContain('类别');
    // 但仍留在报表明细里，抽屉要展示
    expect(图().节点索引['rp:r1'].明细.字段.map((f) => f.字段名)).toEqual(['区域', '销售额', '城市']);
  });

  test('同名不同数据集的字段不合并', () => {
    const g = 图([
      { 报表ID: 'a1', 标题: 'A1', 报表: { 图表配置: { X轴: '金额', 数据: [{ 金额: 1 }] } } },
      { 报表ID: 'a2', 标题: 'A2', 报表: { 图表配置: { X轴: '金额', 数据: [{ 金额: 2 }] } } },
      { 报表ID: 'b1', 标题: 'B1', 报表: { 图表配置: { X轴: '金额', 数据: [{ 金额: 3 }] } } },
      { 报表ID: 'b2', 标题: 'B2', 报表: { 图表配置: { X轴: '金额', 数据: [{ 金额: 4 }] } } },
    ], [
      { 报表ID: 'a1', 数据集ID: 'd1' }, { 报表ID: 'a2', 数据集ID: 'd1' },
      { 报表ID: 'b1', 数据集ID: 'd2' }, { 报表ID: 'b2', 数据集ID: 'd2' },
    ]);
    const 字段节点 = g.节点.filter((n) => n.类型 === '字段');
    expect(字段节点).toHaveLength(2);
    expect(字段节点.every((n) => n.度 === 2)).toBe(true);
  });

  test('入口按报表ID去重：同一张报表重复出现不会双计（否则造出假的高价值字段）', () => {
    const 重复报表 = (标题) => ({
      报表ID: 'r1', 标题, 图表类型: 'bar',
      报表: { 图表配置: { 类型: 'bar', X轴: '区域', 数据: [{ 区域: '华东' }] } },
    });
    const g = 图([重复报表('各区域销售额'), 重复报表('各区域销售额（重复项）')], [{ 报表ID: 'r1', 数据集ID: 'd1' }]);
    expect(g.节点.filter((n) => n.类型 === '报表')).toHaveLength(1);
    expect(g.连线.filter((l) => l.类型 === '归属')).toHaveLength(1);
    expect(g.节点索引['rp:r1'].度).toBe(2);                       // 1 个字段 + 1 条归属，不因重复翻倍
    expect(g.节点索引['ds:d1'].度).toBe(1);
    expect(g.节点索引['ds:d1'].明细.本看板报表).toHaveLength(1);
    // 关键：只被 1 张报表引用的「区域」不该凑够阈值 2 而凭空变成高价值字段节点
    expect(g.节点.filter((n) => n.类型 === '字段')).toHaveLength(0);
  });

  test('数据集节点带上未入本看板的同源报表（反链）', () => {
    expect(图().节点索引['ds:d1'].明细.其他报表).toEqual([
      { 报表ID: 'r9', 标题: '历史报表（未入本看板）', 图表类型: 'bar' },
    ]);
    expect(图().节点索引['ds:d2'].明细.其他报表).toEqual([]);
  });

  test('报表不在 listReports 结果里（>100 截断）→ 落到未知数据集，不丢节点', () => {
    const g = 图(看板报表列表, 报表列表.filter((r) => r.报表ID !== 'r2'));
    expect(g.节点.filter((n) => n.类型 === '报表')).toHaveLength(3);
    expect(g.节点索引['ds:__未知数据集__']).toBeTruthy();
    expect(g.节点索引['rp:r2'].明细.数据集名).toBe('未知数据集');
  });

  test('报表结论被截断到 80 字', () => {
    const 长 = 'x'.repeat(200);
    const g = 图(
      [{ 报表ID: 'z1', 标题: 'Z', 报表: { 结论: 长, 图表配置: {} } }],
      [{ 报表ID: 'z1', 数据集ID: 'd1' }],
    );
    expect(g.节点索引['rp:z1'].明细.结论).toHaveLength(81);   // 80 + 省略号
    expect(g.节点索引['rp:z1'].明细.结论.endsWith('…')).toBe(true);
  });

  test('空输入不抛，返回空图', () => {
    expect(图([]).节点).toEqual([]);
    expect(构建血缘图().统计).toMatchObject({ 数据集数: 0, 报表数: 0 });
  });
});

describe('构建血缘Option', () => {
  test('手动布局：graph + layout none，节点坐标归一化到 0-100', () => {
    const opt = 构建血缘Option(图());
    const s = opt.series[0];
    expect(s.type).toBe('graph');
    expect(s.layout).toBe('none');
    expect(s.data).toHaveLength(6);
    s.data.forEach((d) => {
      expect(d.节点ID).toBeTruthy();
      expect(d.x).toBeGreaterThanOrEqual(0);
      expect(d.x).toBeLessThanOrEqual(100);
      expect(d.y).toBeGreaterThan(0);
      expect(d.y).toBeLessThan(100);
    });
    // 三层 x 递增：数据集最左、字段最右
    expect(s.data.find((d) => d.节点ID === 'ds:d1').x).toBeLessThan(s.data.find((d) => d.节点ID === 'rp:r1').x);
    expect(s.data.find((d) => d.节点ID === 'rp:r1').x).toBeLessThan(s.data.find((d) => d.节点ID === 'fd:d1::区域').x);
  });

  test('连线 source/target 对应节点 id', () => {
    const s = 构建血缘Option(图()).series[0];
    const ids = new Set(s.data.map((d) => d.id));
    s.links.forEach((l) => {
      expect(ids.has(l.source)).toBe(true);
      expect(ids.has(l.target)).toBe(true);
    });
  });

  test('高亮：自身 + 邻居不透明，其余淡出', () => {
    const s = 构建血缘Option(图(), { 高亮节点ID: 'rp:r1' }).series[0];
    const 透明度 = (id) => s.data.find((d) => d.节点ID === id).itemStyle.opacity;
    expect(透明度('rp:r1')).toBe(1);
    expect(透明度('ds:d1')).toBe(1);        // 上游邻居
    expect(透明度('fd:d1::区域')).toBe(1);  // 下游邻居
    expect(透明度('ds:d2')).toBe(0.18);
    expect(透明度('rp:r3')).toBe(0.18);
  });

  test('未高亮时全部不透明', () => {
    const s = 构建血缘Option(图()).series[0];
    expect(s.data.every((d) => d.itemStyle.opacity === 1)).toBe(true);
  });

  test('tooltip 对用户数据里的 HTML 做转义（防存储型 XSS，P0-6）', () => {
    const 恶意 = '<img src=x onerror=alert(1)>';
    const g = 图([
      { 报表ID: 'x1', 标题: 'A', 报表: { 图表配置: { X轴: 恶意, 数据: [{ [恶意]: 1 }] } } },
      { 报表ID: 'x2', 标题: 'B', 报表: { 图表配置: { X轴: 恶意, 数据: [{ [恶意]: 2 }] } } },
    ], [{ 报表ID: 'x1', 数据集ID: 'd1' }, { 报表ID: 'x2', 数据集ID: 'd1' }]);
    // tooltip 在 option 顶层（与 series 平级），不是 series[0].tooltip
    const opt = 构建血缘Option(g);
    const html = opt.tooltip.formatter({ dataType: 'node', data: { 节点ID: 'fd:d1::' + 恶意 }, name: 恶意 });
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });

  test('空图也返回可渲染 option', () => {
    const opt = 构建血缘Option(图([]));
    expect(opt.series[0].data).toEqual([]);
    expect(opt.series[0].links).toEqual([]);
  });
});
