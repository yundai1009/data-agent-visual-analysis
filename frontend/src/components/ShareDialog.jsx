/**
 * components/ShareDialog.jsx — 分享弹窗（生成/撤销/复制链接）
 *
 * 从 Report.jsx 拆分，职责：创建分享链接 + 管理已有链接（列表/撤销/复制）。
 * 入参：showShare、onClose、currentReportId（触发加载/创建/撤销的报表ID）
 * 状态：弹窗内部管理自己的 shareHours/sharePassword/shareCollaborators/shareLinks/shareMsg/shareErr/copied
 */
import { useEffect, useState } from 'react';
import { Share2, Link2, Copy, Check, Clock, Eye, X } from 'lucide-react';
import { createShare, listShares, revokeShare } from '../api';

function fmtExpire(iso) {
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch { return iso; }
}

function fmtRemain(iso) {
  try {
    const ms = new Date(iso).getTime() - Date.now();
    if (Number.isNaN(ms)) return '';
    if (ms <= 0) return '（已过期）';
    const hours = Math.floor(ms / 3600000);
    if (hours >= 48) return `（剩余 ${Math.floor(hours / 24)} 天）`;
    if (hours >= 1) return `（剩余 ${hours} 小时）`;
    return `（剩余 ${Math.max(0, Math.floor(ms / 60000))} 分钟）`;
  } catch { return ''; }
}

export default function ShareDialog({ showShare, onClose, currentReportId }) {
  const [shareHours, setShareHours] = useState(24);
  const [sharePassword, setSharePassword] = useState('');
  const [shareCollaborators, setShareCollaborators] = useState('');
  const [shareLinks, setShareLinks] = useState([]);
  const [shareMsg, setShareMsg] = useState('');
  const [shareErr, setShareErr] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!showShare || !currentReportId) return;
    setShareMsg('');
    setShareErr('');
    setCopied(false);
    (async () => {
      try {
        const res = await listShares(currentReportId);
        setShareLinks(res?.分享列表 || []);
      } catch (e) {
        setShareErr('加载分享列表失败：' + (e.message || e));
      }
    })();
  }, [showShare, currentReportId]);

  if (!showShare) return null;

  const handleCreateShare = async () => {
    if (!currentReportId) return;
    try {
      const res = await createShare(currentReportId, shareHours, sharePassword.trim(), shareCollaborators.trim());
      setShareMsg(`已生成，有效期 ${shareHours} 小时${res.需密码 ? '，需访问密码' : ''}${res.协作者?.length ? `，协作者 ${res.协作者.length} 人` : ''}`);
      setShareErr('');
      setSharePassword('');
      setShareCollaborators('');
      const res2 = await listShares(currentReportId);
      setShareLinks(res2?.分享列表 || []);
    } catch (e) {
      setShareMsg('');
      setShareErr('生成失败：' + (e.message || e));
    }
  };

  const handleRevokeShare = async (sid) => {
    if (!window.confirm('撤销后链接立即失效，确定？')) return;
    try {
      await revokeShare(currentReportId, sid);
      setShareMsg('已撤销');
      setShareErr('');
      const res = await listShares(currentReportId);
      setShareLinks(res?.分享列表 || []);
    } catch (e) {
      setShareErr('撤销失败：' + (e.message || e));
    }
  };

  const handleCopyShare = async (link) => {
    try {
      await navigator.clipboard.writeText(window.location.origin + link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setShareErr('复制失败，请手动复制链接');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Share2 className="w-4 h-4 text-emerald-600" /> 分享报表
          </h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400"><X className="w-4 h-4" /></button>
        </div>

        {/* 生成区 */}
        <div className="flex items-center gap-2 mb-2">
          <select value={shareHours} onChange={(e) => setShareHours(Number(e.target.value))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent">
            <option value={1}>1 小时</option><option value={24}>24 小时</option><option value={72}>3 天</option><option value={168}>7 天</option>
          </select>
          <input value={sharePassword} onChange={(e) => setSharePassword(e.target.value)} placeholder="访问密码（可选）"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent" />
          <button onClick={handleCreateShare}
            className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-all whitespace-nowrap">
            <Link2 className="w-3.5 h-3.5" /> 生成分享链接
          </button>
        </div>
        <input value={shareCollaborators} onChange={(e) => setShareCollaborators(e.target.value)}
          placeholder="协作者 username（逗号分隔，留空 = 公开链接）"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-white focus:outline-none focus:border-accent mb-3" />

        {shareMsg && <p className="text-xs text-emerald-600 mb-3">{shareMsg}</p>}
        {shareErr && <p className="text-xs text-red-500 mb-3">{shareErr}</p>}

        {/* 已有链接列表 */}
        {shareLinks.length > 0 && (
          <div className="space-y-2 max-h-56 overflow-auto">
            {shareLinks.map((s) => {
              const link = `/s/${s.链接ID}`;
              return (
                <div key={s.链接ID} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] text-gray-700 font-mono truncate">{window.location.origin}{link}</p>
                    <p className="text-[10px] text-gray-400 flex items-center gap-2 mt-0.5">
                      <Clock className="w-3 h-3" /> {fmtExpire(s.过期时间)}
                      {(() => { const r = fmtRemain(s.过期时间); return r ? <span className={r === '（已过期）' ? 'text-red-400 font-medium' : 'text-amber-500'}>{r}</span> : null; })()}
                      {typeof s.浏览次数 === 'number' && <span className="flex items-center gap-1"><Eye className="w-3 h-3" /> {s.浏览次数}</span>}
                    </p>
                  </div>
                  <button className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-accent transition-colors" title="复制链接" onClick={() => handleCopyShare(link)}>
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                  <button className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors" title="撤销链接" onClick={() => handleRevokeShare(s.链接ID)}>
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {shareLinks.length === 0 && !shareMsg && !shareErr && (
          <p className="text-xs text-gray-400 text-center py-4">还没有分享链接</p>
        )}
      </div>
    </div>
  );
}
