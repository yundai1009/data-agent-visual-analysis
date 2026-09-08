// 错误边界组件（面试讲解）
//
// 做了什么：包裹子组件树，"接住"渲染期抛出的 JS 错误——一旦子组件
//   渲染崩溃，不再让整个白屏，而是显示"页面渲染异常 + 刷新按钮"。
// 为什么用它：React 默认任何渲染错误都会卸载整棵树；用类组件的
//   getDerivedStateFromError 生命周期可把错误转成状态（hasError），
//   render() 据此切换成兜底 UI。函数组件没有这个能力，所以必须是类。
// 删除它会怎样：页面任何一处出错都会整页白屏，且无提示、无法恢复。
// 替代方案：也可用 react-error-boundary 库，但一个类组件就够，零依赖。
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
    this.reloadTimer = null;
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidUpdate(prevProps) {
    // 【Bug16 修复】resetKeys（路由 pathname）变化时自动重置错误态——
    // 导航到其他页面应允许重新渲染，错误页自动消失，无需手动刷新。
    if (this.state.hasError && prevProps.resetKeys !== this.props.resetKeys) {
      // eslint-disable-next-line react/no-did-update-set-state
      this.setState({ hasError: false, error: null });
    }
  }

  componentWillUnmount() {
    // 清理可能的定时器，避免卸载后触发 setState
    if (this.reloadTimer) clearTimeout(this.reloadTimer);
  }

  handleRetry = () => {
    // 【Bug16 修复】原地重试：重置错误态触发子组件重新渲染（比整页刷新轻）
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 max-w-5xl mx-auto text-center">
          <p className="text-gray-400 text-sm mb-2">页面渲染异常</p>
          <p className="text-xs text-gray-500 mb-4">{this.state.error?.message || ''}</p>
          <div className="flex gap-2 justify-center">
            <button
              className="px-5 py-2 rounded-lg bg-accent text-white text-sm hover:bg-accent-deep transition-all"
              onClick={this.handleRetry}
            >
              重试
            </button>
            <button
              className="px-5 py-2 rounded-lg border border-gray-200 text-sm text-gray-500 hover:bg-gray-50 transition-all"
              onClick={() => window.location.reload()}
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
