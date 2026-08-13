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
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 max-w-5xl mx-auto text-center">
          <p className="text-gray-400 text-sm mb-2">页面渲染异常</p>
          <p className="text-xs text-gray-500 mb-4">{this.state.error?.message || ''}</p>
          <button
            className="px-5 py-2 rounded-lg bg-accent text-white text-sm hover:bg-accent-deep transition-all"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
