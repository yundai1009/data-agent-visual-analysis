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
          <p className="text-xs text-gray-300 mb-4">{this.state.error?.message || ''}</p>
          <button
            className="px-5 py-2 rounded-lg bg-gray-900 text-white text-sm hover:bg-gray-800 transition-all"
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
