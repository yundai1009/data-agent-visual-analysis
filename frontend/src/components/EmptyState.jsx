// 统一空状态组件
export default function EmptyState({ message = '暂无数据', actionText, onAction }) {
  return (
    <div className="p-10 text-center">
      <p className="text-gray-400 text-sm mb-4">{message}</p>
      {actionText && (
        <button
          className="px-5 py-2 rounded-lg bg-gray-900 text-white text-sm hover:bg-gray-800 transition-all"
          onClick={onAction}
        >
          {actionText}
        </button>
      )}
    </div>
  );
}
