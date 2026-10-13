// 阶段 六十：血缘抽屉测试（点关系图节点后回答"这个节点是谁、被谁用着"）
// 三种节点三种内容：数据集（谁在用它）/ 报表（它的字段与结论）/ 字段（谁在复用它）。
// 断言文案以实现为准（例如行数渲染成「120 行」、复用度数字被 <b> 拆开），不照抄计划里的字符串。
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LineageDrawer from './LineageDrawer';

const 数据集节点 = {
  节点ID: 'ds:d1', 名称: '销售.csv', 类型: '数据集', 度: 2, 数据集ID: 'd1',
  明细: {
    文件名: '销售.csv', 行数: 120, 列数: 5, 来源数据集ID: '',
    本看板报表: [{ 报表ID: 'r1', 标题: '各区域销售额', 图表类型: 'bar' }],
    其他报表: [{ 报表ID: 'r9', 标题: '历史报表', 图表类型: 'line' }],
  },
};

// 预检修正：listDatasets 列表项没有 来源数据集ID（后端_核心/存储/sqlite_repo.py:335 只 SELECT 5 列），
// 「源自清洗/合并」只能做成"键存在才渲染"；这里用带值 fixture 锁定该分支真的有渲染（零后端改动）。
const 清洗后数据集节点 = {
  ...数据集节点,
  节点ID: 'ds:d0', 名称: '清洗后.csv', 数据集ID: 'd0',
  明细: { ...数据集节点.明细, 文件名: '清洗后.csv', 来源数据集ID: 'd_raw', 本看板报表: [], 其他报表: [] },
};

const 报表节点 = {
  节点ID: 'rp:r1', 名称: '各区域销售额', 类型: '报表', 度: 4, 报表ID: 'r1', 数据集ID: 'd1',
  明细: {
    标题: '各区域销售额', 图表类型: 'bar', 创建时间: '2026-10-01', 数据集ID: 'd1', 数据集名: '销售.csv',
    结论: '华东最高', 字段: [{ 字段名: '区域', 角色: ['X轴'] }, { 字段名: '销售额', 角色: ['Y轴'] }],
  },
};

const 字段节点 = {
  节点ID: 'fd:d1::区域', 名称: '区域', 类型: '字段', 度: 2, 字段名: '区域', 数据集ID: 'd1',
  明细: {
    字段名: '区域', 数据集名: '销售.csv', 角色: ['X轴'],
    报表: [{ 报表ID: 'r1', 标题: '各区域销售额', 图表类型: 'bar' }, { 报表ID: 'r2', 标题: '各区域销量', 图表类型: 'line' }],
  },
};

// 长列表 fixture：12 个字段 > 折叠阈值，用来测"展开/收起"与"关闭后清空内部状态"
const 宽报表节点 = {
  节点ID: 'rp:rw', 名称: '全字段宽表', 类型: '报表', 度: 13, 报表ID: 'rw', 数据集ID: 'd1',
  明细: {
    标题: '全字段宽表', 图表类型: 'bar', 创建时间: '2026-10-02', 数据集ID: 'd1', 数据集名: '销售.csv', 结论: '',
    字段: Array.from({ length: 12 }, (_, i) => ({ 字段名: `字段${String(i + 1).padStart(2, '0')}`, 角色: ['Y轴'] })),
  },
};

describe('LineageDrawer', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('数据集节点：展示行/列、本看板引用、未入看板的同源报表', () => {
    render(<LineageDrawer 节点={数据集节点} />);
    expect(screen.getByText('销售.csv')).toBeInTheDocument();
    expect(screen.getByText(/120\s*行/)).toBeInTheDocument();          // 行数渲染成「120 行」
    expect(screen.getByText(/5\s*列/)).toBeInTheDocument();
    expect(screen.getByText('各区域销售额')).toBeInTheDocument();
    expect(screen.getByText('历史报表')).toBeInTheDocument();
    expect(screen.getByText('未加入本看板')).toBeInTheDocument();
  });

  it('数据集节点：来源数据集ID 存在才渲染"源自清洗/合并"徽章', () => {
    const { unmount } = render(<LineageDrawer 节点={数据集节点} />);
    expect(screen.queryByText('源自清洗/合并')).not.toBeInTheDocument();  // listDatasets 常态：拿不到就不渲染
    unmount();
    render(<LineageDrawer 节点={清洗后数据集节点} />);
    expect(screen.getByText('源自清洗/合并')).toBeInTheDocument();
  });

  it('数据集节点没有其他报表时给空态文案，不留空白块', () => {
    render(<LineageDrawer 节点={清洗后数据集节点} />);
    expect(screen.getByText('没有其他报表复用这份数据')).toBeInTheDocument();
  });

  it('报表节点：展示结论与字段角色，点"查看完整报表"回传报表ID', () => {
    const onOpenReport = vi.fn();
    render(<LineageDrawer 节点={报表节点} onOpenReport={onOpenReport} />);
    expect(screen.getByText('华东最高')).toBeInTheDocument();
    expect(screen.getByText('区域')).toBeInTheDocument();
    expect(screen.getByText('X轴')).toBeInTheDocument();
    expect(screen.getByText('2026-10-01')).toBeInTheDocument();
    fireEvent.click(screen.getByText('查看完整报表'));
    expect(onOpenReport).toHaveBeenCalledWith('r1');
  });

  it('字段节点：展示复用度与复用它的报表', () => {
    render(<LineageDrawer 节点={字段节点} />);
    // 数字被 <b> 包着，直接文本节点不连续 → 用容器 textContent 断言（空白会归一）
    expect(screen.getByText(/张报表复用/)).toHaveTextContent(/被\s*2\s*张报表复用/);
    expect(screen.getByText('各区域销量')).toBeInTheDocument();
  });

  it('点关联节点（报表的数据来源 / 字段的所属数据集）回传 ds: 节点ID', () => {
    const onSelectNode = vi.fn();
    const { unmount } = render(<LineageDrawer 节点={报表节点} onSelectNode={onSelectNode} />);
    fireEvent.click(screen.getByText('销售.csv'));
    expect(onSelectNode).toHaveBeenCalledWith('ds:d1');
    unmount();
    render(<LineageDrawer 节点={字段节点} onSelectNode={onSelectNode} />);
    fireEvent.click(screen.getByText('销售.csv'));
    expect(onSelectNode).toHaveBeenCalledWith('ds:d1');
  });

  it('关闭按钮回调 onClose（点图上空白不产生节点信号，抽屉必须自带关闭入口）', () => {
    const onClose = vi.fn();
    render(<LineageDrawer 节点={报表节点} onClose={onClose} />);
    fireEvent.click(screen.getByTitle('关闭'));
    expect(onClose).toHaveBeenCalled();
  });

  it('Esc 关闭回调 onClose', () => {
    const onClose = vi.fn();
    render(<LineageDrawer 节点={报表节点} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('带 role="dialog" 与 aria-label，读屏与自动化都能定位', () => {
    render(<LineageDrawer 节点={报表节点} />);
    expect(screen.getByRole('dialog', { name: /节点详情/ })).toBeInTheDocument();
  });

  it('点遮罩关闭，点抽屉内容本身不关闭', () => {
    const onClose = vi.fn();
    render(<LineageDrawer 节点={报表节点} onClose={onClose} />);
    fireEvent.click(screen.getByText('华东最高'));       // 面板内部：stopPropagation
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(document.querySelector('[data-testid="血缘抽屉遮罩"]'));
    expect(onClose).toHaveBeenCalled();
  });

  it('节点为空（父组件关闭抽屉后）不渲染任何内容', () => {
    const { container } = render(<LineageDrawer 节点={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('明细字段缺失时安全降级，不崩且有兜底文案', () => {
    render(<LineageDrawer 节点={{ 节点ID: 'ds:d2', 名称: '残缺.csv', 类型: '数据集' }} />);
    expect(screen.getByText('残缺.csv')).toBeInTheDocument();
    expect(screen.getByText('没有其他报表复用这份数据')).toBeInTheDocument();
    expect(screen.queryByText(/行$/)).not.toBeInTheDocument();
  });

  it('长列表默认折叠，关闭再重开会清空内部展开态', () => {
    const { rerender } = render(<LineageDrawer 节点={宽报表节点} />);
    expect(screen.queryByText('字段09')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('展开全部 12 条'));
    expect(screen.getByText('字段09')).toBeInTheDocument();

    rerender(<LineageDrawer 节点={null} />);                 // 父组件关闭：节点传 null
    rerender(<LineageDrawer 节点={宽报表节点} />);           // 再打开同一节点
    expect(screen.queryByText('字段09')).not.toBeInTheDocument();
    expect(screen.getByText('展开全部 12 条')).toBeInTheDocument();
  });

  it('回调缺省也不崩（纯展示组件，不取数不发请求）', () => {
    render(<LineageDrawer 节点={字段节点} />);
    fireEvent.click(screen.getByText('各区域销售额'));
    fireEvent.click(screen.getByTitle('关闭'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});