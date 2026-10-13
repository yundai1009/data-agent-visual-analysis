// 路由兜底页：任何没命中的路径都渲染它，给出一条回到数据管理的出路；无状态、零请求、零 props。
// 做了什么：默认导出 NotFound 组件，渲染 96px 半透明 404 数字 + SearchX 图标 + 一句解释 +
//   「返回数据管理」按钮，onClick 用 useNavigate() 跳到 /data；不读 URL、不发请求。
// 为什么按钮跳到固定的 /data 而不是 history.back()：用户很可能是粘贴了一条旧链接直接进来的，
//   back() 会把他退到浏览器空白页甚至外部站点；跳到一个确定的分析入口才可预期。
// 为什么不回显 location.pathname 告诉用户「哪个地址不存在」：路径里可能带用户拼错的隐私信息，
//   回显等于把它再写进 DOM 与截图；404 只回答「没有这个页面」，不回答「你想找什么」。
// 为什么不把这几行 JSX 内联进 App.jsx 的路由表：路由表只留 path → element 映射，文案与样式独立成文件，
//   改文案不必碰路由结构，也更符合「pages/ 下每个文件一个路由终点」的既有布局。
// 坑：它渲染在主内容区内部（h-full 撑满父容器），不是全屏遮罩——侧边栏因此保留，用户不必先回首页才能换页；
//   若改成 fixed 全屏就会切断这条自救路径，而 App.jsx 里 path="*" 是套在受保护路由内的。
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, SearchX } from 'lucide-react';

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
