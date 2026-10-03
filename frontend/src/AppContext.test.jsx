/**
 * 阶段 52 补测：删除数据集后 localStorage.dataset_cache 必须同步清除。
 *
 * 缺陷（P2，真实用户走查发现）：
 *   删除数据集（单个/批量）只 setDataset(null) 清内存，AppContext 的持久化
 *   effect 是 `if (dataset) setItem(...)` —— dataset 为 null 时**既不写也不删**，
 *   旧缓存留在 localStorage。刷新页面后 `loadState('dataset_cache')` 恢复已删除
 *   数据集 → 分析页显示「当前数据集：已删除的文件」，点开始分析报
 *   「分析失败：数据集不存在」。合并/清洗产物删除同样触发。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AppProvider, useApp } from './AppContext';

// 消费 useApp 的探针组件：显示当前 dataset 文件名 + 两个按钮直接设置/清空
function Probe() {
  const { dataset, setDataset } = useApp();
  return (
    <div>
      <span data-testid="current">{dataset?.文件名 ?? '(空)'}</span>
      <button onClick={() => setDataset({ 数据集ID: 'x1', 文件名: '销售.csv' })}>set</button>
      <button onClick={() => setDataset(null)}>clear</button>
    </div>
  );
}

function renderProvider() {
  return render(
    <AppProvider>
      <Probe />
    </AppProvider>,
  );
}

describe('AppContext dataset_cache 对称持久化（阶段 52 回归）', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('选中数据集 → 写入缓存；清空 dataset → 缓存同步移除（回归：残留导致刷新恢复已删数据集）', () => {
    renderProvider();
    expect(screen.getByTestId('current').textContent).toBe('(空)');

    // 设置数据集 → 缓存写入
    fireEvent.click(screen.getByText('set'));
    expect(screen.getByTestId('current').textContent).toBe('销售.csv');
    expect(localStorage.getItem('dataset_cache')).toContain('销售.csv');

    // 清空 dataset（模拟删除数据集）→ 缓存必须移除
    fireEvent.click(screen.getByText('clear'));
    expect(screen.getByTestId('current').textContent).toBe('(空)');
    expect(localStorage.getItem('dataset_cache')).toBeNull();
  });

  it('初始缓存恢复：有缓存时挂载即恢复（保住刷新保持选择体验）', () => {
    localStorage.setItem('dataset_cache', JSON.stringify({ 数据集ID: 'x2', 文件名: '恢复.csv' }));
    renderProvider();
    expect(screen.getByTestId('current').textContent).toBe('恢复.csv');
  });
});