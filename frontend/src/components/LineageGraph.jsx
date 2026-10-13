// 阶段 六十 · 看板血缘关系视图的 ECharts 渲染层。
//
// 做了什么：把 utils/看板血缘.js 算好的 节点/连线 画成有向关系图，并把点击的节点ID回传父组件。
// 为什么单独一个组件、不复用 EChartsChart：
//   - EChartsChart 的输入是"报表数据 + 图表配置"（buildOption 面向 18 种业务图表），
//     关系图的输入是图结构 + 点击交互，硬塞进去会污染那条已测路径；
//   - 但渲染范式（懒加载 echarts / notMerge / dispose / resize 监听）保持一致，
//     避免仓库里出现两套图表生命周期写法。
//
// 实例生命周期：echarts 实例只 init 一次；数据/高亮变化只走 setOption(notMerge)；
// 只有卸载才 dispose。不这么做的话，每次点节点换高亮都要销毁重建实例——
// 重建期间画布会闪空白，用户的 roam 缩放与拖拽位置也会被重置。
// option 一律来自 utils/看板血缘.js 的 构建血缘Option，本组件不自己拼色板/提示样式。
import { useEffect, useRef, useState } from 'react';
import { 构建血缘Option } from '../utils/看板血缘';

export default function LineageGraph({ 图数据, 高亮节点ID = '', onSelectNode, height = 520 }) {
  const 容器 = useRef(null);
  const 图实例 = useRef(null);
  const echarts模块 = useRef(null);
  const 回调 = useRef(onSelectNode);      // 事件回调用 ref 取最新值，避免注册时闭包过期
  const [就绪, set就绪] = useState(false);
  const 无数据 = !((图数据?.节点 || []).length);

  useEffect(() => { 回调.current = onSelectNode; }, [onSelectNode]);

  // echarts 懒加载：与 EChartsChart 同款（约 1MB 独立 chunk，不进主 bundle）
  useEffect(() => {
    let 已取消 = false;
    (async () => {
      try {
        const mod = await import('echarts');
        if (已取消) return;
        echarts模块.current = mod;
        set就绪(true);
      } catch (e) {
        console.error('图表库加载失败:', e);
      }
    })();
    return () => { 已取消 = true; };
  }, []);

  // 1) 建实例：懒加载完成后只建一次；卸载时 dispose（实例销毁后监听随之失效，无需手动 off）
  useEffect(() => {
    if (!就绪 || !容器.current || !echarts模块.current) return;
    const chart = echarts模块.current.init(容器.current, null, { renderer: 'canvas' });
    图实例.current = chart;

    // 点击节点回传（点连线不回传）
    chart.on('click', (p) => {
      if (p?.dataType !== 'node') return;
      const id = p.data?.节点ID;
      if (id) 回调.current?.(id);
    });

    return () => {
      chart.dispose();
      图实例.current = null;
    };
  }, [就绪]);

  // 2) 数据/高亮变化走 setOption（notMerge 全量替换，避免残留上一轮的高亮/节点）
  useEffect(() => {
    const chart = 图实例.current;
    if (!就绪 || !chart) return;
    try {
      const option = 构建血缘Option(图数据, { 高亮节点ID });
      if (option) {
        chart.setOption(option, { notMerge: true });
        chart.resize();
      }
    } catch (e) {
      console.error('血缘图渲染异常:', e);
      chart.setOption({
        title: { text: `关系图渲染异常: ${e.message}`, left: 'center', textStyle: { fontSize: 13, color: '#ef4444' } },
      }, { notMerge: true });
    }
    // 图数据每次渲染都是新对象引用 → 用内容签名，避免无谓的 setOption（同 EChartsChart）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [就绪, 高亮节点ID, JSON.stringify(图数据?.节点), JSON.stringify(图数据?.连线)]);

  // resize 监听：handler 动态读取最新 图实例，避免图表重建后调用已 dispose 的旧实例
  useEffect(() => {
    const handler = () => { if (图实例.current) 图实例.current.resize(); };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return (
    <div className="relative w-full" style={{ height }}>
      {!就绪 && (
        <p className="absolute inset-0 flex items-center justify-center text-xs text-gray-400">关系图加载中…</p>
      )}
      {就绪 && 无数据 && (
        <p
          className="absolute inset-0 flex items-center justify-center text-xs text-gray-400 pointer-events-none"
          data-testid="血缘图空态"
        >
          当前看板暂无可展示的血缘关系
        </p>
      )}
      <div ref={容器} className="w-full h-full" data-testid="血缘图画布" />
    </div>
  );
}
