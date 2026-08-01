// 统一错误提示组件（页面内，非弹窗）
export default function ErrorMessage({ message, onClose }) {
  if (!message) return null;
  return (
    <div className="mt-3 px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
      <span>⚠</span>
      <span className="flex-1">{message}</span>
      {onClose && (
        <button className="text-red-400 hover:text-red-600 text-xs" onClick={onClose}>✕</button>
      )}
    </div>
  );
}
