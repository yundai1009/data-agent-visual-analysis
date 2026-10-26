// 对比分析页测试：多选数据集 → 防抖预检 → 生成对比报表 → 跳转 / 失败提示
// 覆盖点：
//   1. 只勾 1 个数据集时「生成对比报表」禁用（并提示还需再选）
//   2. 勾 2 个后防抖调用 previewCompare（对比标签为空 = 交给后端推导）
//   3. 手动改来源标签 → 生成 payload 里的「对比标签」是改后的值
//   4. 生成成功 → navigate('/report/<报表ID>')
//   5. 生成失败 → 页面内显示后端 message（不弹 alert、不跳转）
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// useNavigate 必须 mock 掉：组件没有路由上下文，也不能真的跳页
const navMock = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => navMock.navigate }));

// 只 mock 页面真正用到的三个端点，其余保持原样（不会被调用）
vi.mock('../api', () => ({
  listDatasets: vi.fn(),
  previewCompare: vi.fn(),
  compareReport: vi.fn(),
}));

import { listDatasets, previewCompare, compareReport } from '../api';
import Compare from './Compare';

const 数据集列表 = [
  { 数据集ID: 'd1', 文件名: '销售1月.csv', 行数: 12, 列数: 3 },
  { 数据集ID: 'd2', 文件名: '销售2月.csv', 行数: 12, 列数: 3 },
  { 数据集ID: 'd3', 文件名: '销售10月.csv', 行数: 13, 列数: 3 },
];

const 预检结果 = {
  共同字段: ['地区', '销售额'],
  指标候选: ['销售额'],
  主体轴候选: [{ 列: '地区', 基数: 3 }],
  来源轴候选: [{ 列: '月份', 各数据集取值: ['1月', '2月', '10月'], 类型: '时间型' }],
  推荐: {
    来源轴: null,
    来源标签: ['1月', '2月', '10月'],
    推导方式: '文件名',
    主体轴: '地区',
    指标: '销售额',
    聚合方式: '求和',
    轴类型: '类别型',
  },
  行数: 37,
  警告: [],
};

// 按文件名点击勾选框（列表卡片里的 checkbox 用文件名做 aria-label）
async function 勾选(...文件名列表) {
  for (const 名 of 文件名列表) {
    fireEvent.click(await screen.findByRole('checkbox', { name: 名 }));
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  listDatasets.mockResolvedValue({ 数据集列表, 统计: { 总数: 3, 总行数: 37 } });
  previewCompare.mockResolvedValue(预检结果);
  compareReport.mockResolvedValue({ 报表ID: 'r-100', 数据集ID: 'd1', agent_mode: 'compare' });
});

describe('Compare 对比分析页', () => {
  it('只勾选 1 个数据集时「生成对比报表」按钮禁用，并提示至少 2 个', async () => {
    render(<Compare />);
    await 勾选('销售1月.csv');

    expect(screen.getByRole('button', { name: /生成对比报表/ })).toBeDisabled();
    expect(screen.getByText(/至少选择 2 个数据集/)).toBeInTheDocument();
    // 勾 1 个不发预检（预检要求 ≥2）
    expect(previewCompare).not.toHaveBeenCalled();
  });

  it('勾选 2 个数据集后防抖调用 previewCompare，标签为空表示交给后端推导', async () => {
    render(<Compare />);
    await 勾选('销售1月.csv', '销售10月.csv');

    await waitFor(() => expect(previewCompare).toHaveBeenCalledTimes(1));
    const 入参 = previewCompare.mock.calls[0][0];
    expect(入参.数据集ID列表).toEqual(['d1', 'd3']); // 按勾选顺序
    expect(入参.对比标签).toEqual([]);               // 没手改 → 不传标签
    expect(入参.来源轴).toBeNull();

    // 预检返回的推荐值成为默认选中
    await waitFor(() => expect(screen.getByLabelText('主体轴')).toHaveValue('地区'));
    expect(screen.getByLabelText('指标')).toHaveValue('销售额');
  });

  it('手动改来源标签后，生成 payload 里的「对比标签」是改后的值', async () => {
    render(<Compare />);
    await 勾选('销售1月.csv', '销售2月.csv');
    await waitFor(() => expect(previewCompare).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('来源标签 1'), { target: { value: '一月' } });
    fireEvent.click(screen.getByRole('button', { name: /生成对比报表/ }));

    await waitFor(() => expect(compareReport).toHaveBeenCalledTimes(1));
    const 入参 = compareReport.mock.calls[0][0];
    // 改过的用「一月」，没改的回落到文件名去扩展名
    expect(入参.对比标签).toEqual(['一月', '销售2月']);
    expect(入参.数据集ID列表).toEqual(['d1', 'd2']);
    expect(入参.维度).toBe('地区');
    expect(入参.指标).toBe('销售额');
    expect(入参.聚合方式).toBe('求和');
    expect(入参.图表类型).toBe('自动推荐');
    expect(入参.来源轴).toBeNull();
    expect(入参.筛选条件).toEqual([]);
  });

  it('生成成功跳转到 /report/<报表ID>', async () => {
    render(<Compare />);
    await 勾选('销售1月.csv', '销售2月.csv');

    fireEvent.click(screen.getByRole('button', { name: /生成对比报表/ }));

    await waitFor(() => expect(navMock.navigate).toHaveBeenCalledWith('/report/r-100'));
  });

  it('生成失败时页面内显示后端错误文案，且不跳转', async () => {
    compareReport.mockRejectedValue(new Error('对比数据集至少要 2 个'));
    render(<Compare />);
    await 勾选('销售1月.csv', '销售2月.csv');

    fireEvent.click(screen.getByRole('button', { name: /生成对比报表/ }));

    expect(await screen.findByText(/对比数据集至少要 2 个/)).toBeInTheDocument();
    expect(navMock.navigate).not.toHaveBeenCalled();
  });

  it('preview 失败只提示，不阻塞生成', async () => {
    previewCompare.mockRejectedValue(new Error('预检炸了'));
    render(<Compare />);
    await 勾选('销售1月.csv', '销售2月.csv');

    expect(await screen.findByText(/预检没成功/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /生成对比报表/ })).not.toBeDisabled();
  });

  it('勾选超过 10 个数据集时拒绝并提示上限', async () => {
    const 多 = Array.from({ length: 11 }, (_, i) => ({
      数据集ID: `x${i}`, 文件名: `数据${i}.csv`, 行数: 5, 列数: 2,
    }));
    listDatasets.mockResolvedValue({ 数据集列表: 多, 统计: { 总数: 11, 总行数: 55 } });
    render(<Compare />);

    await 勾选(...多.slice(0, 10).map((d) => d.文件名));
    fireEvent.click(await screen.findByRole('checkbox', { name: '数据10.csv' }));

    expect(await screen.findByText(/最多同时对比 10 个数据集/)).toBeInTheDocument();
    expect(screen.getByText(/已选 10\/10/)).toBeInTheDocument();
  });

  // ---- 阶段七十四 · B：从数据管理页带 ?datasets=ID,ID 过来时预选 ----
  // 用户反馈「对比分析找不到」的真正修法：不指望用户自己去侧栏找这个词，
  // 而是在"刚上传完/刚勾选完"的那一刻给一个入口，带参数跳过来直接选好。
  describe('从 ?datasets= 预选（阶段七十四 B）', () => {
    const 原始地址 = window.location.search;

    afterEach(() => {
      window.history.replaceState({}, '', `/${原始地址}`);
    });

    it('按 URL 顺序预选，且顺序 = 对比顺序', async () => {
      window.history.replaceState({}, '', '/compare?datasets=d3,d1');
      render(<Compare />);

      // 列表是异步的 → 等「已选 2/10」出现，证明预选在列表到达后才生效
      await waitFor(() => expect(screen.getByText(/已选 2\/10/)).toBeInTheDocument());
      // 标签框只有 placeholder（值来自后端推导或手改），所以断言 placeholder：
      // d3 在前 → 第一个框兜底文案是 d3 的文件名。这证明顺序按 URL 而不是按列表。
      expect(screen.getByLabelText('来源标签 1')).toHaveAttribute('placeholder', '销售10月');
      expect(screen.getByLabelText('来源标签 2')).toHaveAttribute('placeholder', '销售1月');
    });

    it('URL 里混入不存在的 ID 时忽略它，不影响可用的那几个', async () => {
      window.history.replaceState({}, '', '/compare?datasets=不存在,d2');
      render(<Compare />);

      await waitFor(() => expect(screen.getByText(/已选 1\/10/)).toBeInTheDocument());
      expect(screen.getByLabelText('来源标签 1')).toHaveAttribute('placeholder', '销售2月');
    });
  });
});
