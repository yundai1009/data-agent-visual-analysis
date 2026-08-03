import { Inbox } from 'lucide-react';

// 统一空状态组件（藏青图标 + 描述 + 动作按钮）
export default function EmptyState({ message = '暂无数据', description, actionText, onAction }) {
  return (
    <div className="py-14 text-center flex flex-col items-center">
      <div className="w-14 h-14 rounded-2xl bg-accent-soft flex items-center justify-center mb-4">
        <Inbox className="w-6 h-6 text-accent" />
      </div>
      <p className="text-sm font-medium text-gray-600">{message}</p>
      {description && <p className="text-xs text-gray-400 mt-1.5 max-w-xs leading-relaxed">{description}</p>}
      {actionText && (
        <button
          className="mt-5 px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all"
          onClick={onAction}
        >
          {actionText}
        </button>
      )}
    </div>
  );
}
