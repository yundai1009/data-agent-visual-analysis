import { useNavigate } from 'react-router-dom';
import { ArrowLeft, SearchX } from 'lucide-react';

// 404 页面：藏在主内容区居中展示，保留侧边栏导航
export default function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="text-center max-w-sm">
        <div
          className="text-[96px] font-bold leading-none text-accent/15 select-none"
          style={{ letterSpacing: '-0.04em' }}
        >
          404
        </div>
        <div className="-mt-5">
          <div className="w-12 h-12 rounded-2xl bg-accent-soft flex items-center justify-center mx-auto mb-4">
            <SearchX className="w-5 h-5 text-accent" />
          </div>
          <p className="text-lg font-semibold text-gray-900">页面走丢了</p>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            你访问的页面不存在或已被移除，
            <br />
            回到数据管理继续分析吧。
          </p>
          <button
            onClick={() => navigate('/data')}
            className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all active:scale-[.98]"
          >
            <ArrowLeft className="w-4 h-4" /> 返回数据管理
          </button>
        </div>
      </div>
    </div>
  );
}
