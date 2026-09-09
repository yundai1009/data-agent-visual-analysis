/**
 * components/ExportDialog.jsx — 统一导出弹窗（格式选择 + 确认下载）
 *
 * 从 Report.jsx 拆分，职责：展示 7 种导出格式 + 另存为（showSaveFilePicker）逻辑。
 * 入参：showDl（弹窗开关）、onClose（关闭）、onExport(格式, 完成回调)（格式选择后回调）
 *       chartTypeKey / trace / exportData（用于判断各格式的可用性）
 * 注意：确认下载为异步流程——内部管理 dlBusy 状态，导出完成后自动关闭弹窗
 *       （与旧内联实现行为一致：导出结束 → setDlBusy(false) → setShowDl(false)）。
 */
import { useState } from 'react';
import { Download, X } from 'lucide-react';

export default function ExportDialog({ showDl, onClose, onExport, dlFmt, setDlFmt, chartTypeKey, trace, exportData }) {
  const [dlBusy, setDlBusy] = useState(false);
  if (!showDl) return null;

  const dlOptions = [
    { key: 'xlsx', label: 'Excel 表格', desc: '数据明细（.xlsx）' },
    { key: 'csv', label: 'CSV 数据', desc: '数据明细（.csv）' },
    { key: 'pdf', label: 'PDF 报告', desc: '结论 + 数据表（.pdf）' },
    { key: 'png', label: '图表图片', desc: '当前可视化图表（.png）', available: chartTypeKey !== 'table' },
    { key: 'trace', label: 'Agent 决策记录', desc: '分析过程（.md）', available: trace.length > 0 },
    { key: 'html', label: 'HTML 报告', desc: '静态网页（.html）', available: !!exportData?.HTML },
    { key: 'json', label: 'JSON 数据', desc: '结构化数据（.json）', available: !!exportData?.JSON },
  ];

  const handleConfirm = async () => {
    setDlBusy(true);
    try {
      // onExport 返回 Promise（Report.jsx 的 handleExportFormat 是 async）
      await onExport(dlFmt);
    } finally {
      setDlBusy(false);
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Download className="w-4 h-4 text-accent" /> 导出报表
          </h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-1.5 max-h-72 overflow-y-auto">
          {dlOptions.filter(o => o.available !== false).map((opt) => (
            <button key={opt.key} onClick={() => setDlFmt(opt.key)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-all ${dlFmt === opt.key ? 'border-accent bg-accent-soft' : 'border-gray-200 hover:bg-gray-50'}`}>
              <span>
                <span className={`block text-sm ${dlFmt === opt.key ? 'text-accent-deep' : 'text-gray-700'}`}>{opt.label}</span>
                <span className="block text-[11px] text-gray-400">{opt.desc}</span>
              </span>
              <span className={`w-3.5 h-3.5 rounded-full border-2 shrink-0 ${dlFmt === opt.key ? 'border-accent bg-accent' : 'border-gray-300'}`} />
            </button>
          ))}
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-200 text-sm text-gray-500 hover:bg-gray-50 transition-all">取消</button>
          <button onClick={handleConfirm} disabled={dlBusy}
            className="flex-1 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all disabled:opacity-50">
            {dlBusy ? '下载中…' : '确认下载'}
          </button>
        </div>
      </div>
    </div>
  );
}
