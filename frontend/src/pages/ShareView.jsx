// 分享只读页（面试讲解）
//
// 做了什么：/s/:shareId —— 报表公开分享的"只读落地页"：无需登录
//   即可查看图表/结论/数据，分享者设了密码则先验证密码。
// 为什么这样设计：
//   - 与主站完全解耦：不依赖登录态，只调 getSharedReport(shareId)，
//     后端按分享链接的归属校验（过期时间/密码/是否撤销）；
//   - 只读：页面无任何编辑/导出入口，从入口上保证"分享出去的
//     报表不能被篡改"。
// 删除它会怎样：分享链接全部失效（后端接口仍在，无前端展示）。
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Share2, AlertTriangle, ShieldCheck, Lock, LayoutDashboard, BarChart3 } from 'lucide-react';
import { getSharedReport } from '../api';
import EChartsChart from '../components/EChartsChart';

// 公开分享只读页：/s/:shareId（无需登录，仅展示；可设访问密码）
export default function ShareView() {
  const { shareId } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('table');
  const [loading, setLoading] = useState(true);
  // 密码保护状态
  const [needsPassword, setNeedsPassword] = useState(false);
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  const load = (pwd) => {
    setLoading(true);
    setAuthError('');
    setError('');  // B16：重试成功后清除残留错误页
    getSharedReport(shareId, pwd)
      .then((data) => { setReport(data); setNeedsPassword(false); })
      .catch((e) => {
        if (e.status === 401) { setNeedsPassword(true); setAuthError('密码不正确，请重试'); }
        else setError(e.message || '分享内容加载失败');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(''); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [shareId]);

  // 需密码：先展示密码输入卡片
  if (!loading && needsPassword) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-8">
        <div className="bg-white popup-surface rounded-2xl border border-gray-200 p-8 text-center max-w-sm w-full">
          <Lock className="w-9 h-9 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-700 font-medium mb-1">此分享已设置访问密码</p>
          <p className="text-xs text-gray-400 mb-4">请输入分享者提供的密码后查看</p>
          {authError && <p className="text-xs text-red-500 mb-2">{authError}</p>}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load(password)}
            placeholder="访问密码"
            autoFocus
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent mb-3"
          />
          <button
            onClick={() => load(password)}
            disabled={!password}
            className="w-full px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all disabled:opacity-40"
          >
            查看报表
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-4">
        <div className="h-6 w-48 bg-gray-200 rounded-lg animate-pulse" />
        <div className="h-[320px] bg-gray-100 rounded-xl animate-pulse" />
        <div className="h-4 w-2/3 bg-gray-200 rounded-lg animate-pulse" />
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-8">
        <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center max-w-sm">
          <AlertTriangle className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-600 font-medium">{error || '分享内容不存在'}</p>
          <p className="text-xs text-gray-400 mt-1.5">链接可能已过期、被撤销，或报表已被删除</p>
        </div>
      </div>
    );
  }

  // 优化⑦：看板分享的只读视图（名称 + 报表标题列表）
  if (report.类型 === 'dashboard') {
    return (
      <div className="min-h-[70vh] flex items-center justify-center p-8">
        <div className="bg-white popup-surface rounded-2xl border border-gray-200 p-8 max-w-md w-full">
          <LayoutDashboard className="w-9 h-9 text-accent mx-auto mb-3" />
          <h2 className="text-base font-semibold text-gray-900 text-center mb-1">{report.名称 || '共享看板'}</h2>
          <p className="text-xs text-gray-400 text-center mb-5">
            共享者公开分享的看板（{report.报表列表?.length || 0} 份报表）
            {report.过期时间 && <span className="block mt-1">有效期至 {new Date(report.过期时间).toLocaleString('zh-CN', { hour12: false })}</span>}
          </p>
          <div className="space-y-1.5">
            {(report.报表列表 || []).map((it, i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 text-xs text-gray-700">
                <BarChart3 className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                <span className="truncate">{it.标题}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const chartConfig = report.图表配置 || {};
  const chartTypeKey = chartConfig.类型 || 'bar';
  const risks = report.风险提示 || [];
  const conclusion = report.结论 || '';
  const rows = report.报表数据 || [];

  return (
    <div className="p-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <p className="flex items-center gap-1.5 text-xs text-gray-400 mb-1">
            <Share2 className="w-3.5 h-3.5" /> 分享的报表
          </p>
          <h1 className="text-lg font-semibold text-gray-900">{report.标题}</h1>
        </div>
        <span className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-accent-soft text-accent border border-accent/20">
          <ShieldCheck className="w-3 h-3" /> 只读视图
        </span>
      </div>

      {/* 图表 */}
      <div className="rounded-xl p-5"
           style={{ background: 'radial-gradient(120% 100% at 50% 0%, #eef3f9 0%, #f8fafc 55%, #f1f5f9 100%)' }}>
        {chartTypeKey === 'table' ? (
          <p className="text-sm text-gray-400 text-center py-10">表格类数据请在下方「数据表」中查看</p>
        ) : (
          <EChartsChart chartType={chartTypeKey} chartConfig={chartConfig} height={360} />
        )}
      </div>

      {/* 结论 */}
      {conclusion && (
        <div className="mt-4 bg-white rounded-xl p-5"
             style={{ boxShadow: '0 8px 16px -8px rgba(15,76,129,.08)', borderLeft: '4px solid var(--color-accent, #0f4c81)' }}>
          <p className="text-xs text-gray-400 font-semibold tracking-wide mb-2">分析结论</p>
          <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">{conclusion}</p>
        </div>
      )}

      {/* 风险提示 */}
      {risks.length > 0 && (
        <div className="mt-3 rounded-xl p-4 flex gap-3 items-start" style={{ background: '#fef3c7' }}>
          <span className="text-xs font-semibold shrink-0" style={{ color: '#b45309' }}>⚠ 数据提示</span>
          <div className="flex flex-wrap gap-1.5">
            {risks.map((w, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md"
                    style={{ background: '#fff7ed', color: '#92400e', border: '1px solid #fed7aa' }}>{w}</span>
            ))}
          </div>
        </div>
      )}

      {/* 数据表 / 元信息 */}
      <div className="bg-white rounded-xl border border-gray-200 mt-5 overflow-hidden">
        <div className="flex items-center gap-6 px-5 pt-3.5 border-b border-gray-100">
          {['table', 'meta'].map((t) => (
            <span key={t}
              className={`pb-3 text-sm cursor-pointer transition-all ${tab === t ? 'text-gray-900 font-medium border-b-2 border-accent' : 'text-gray-400 hover:text-gray-600'}`}
              onClick={() => setTab(t)}>
              {{ table: '数据表', meta: '分享信息' }[t]}
            </span>
          ))}
        </div>

        {tab === 'table' && (
          <div className="overflow-auto max-h-56">
            {rows.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-400 border-b border-gray-100">
                    {Object.keys(rows[0]).map((k) => (
                      <th key={k} className="text-left px-5 py-3 font-medium">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {rows.map((row, i) => (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="px-5 py-2.5 font-mono">{String(v ?? '')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-sm text-gray-400 text-center py-8">暂无数据</p>}
          </div>
        )}

        {tab === 'meta' && (
          <div className="px-5 py-4 space-y-2 text-xs text-gray-500">
            <p>图表类型：<span className="text-gray-700">{report.图表类型 || '—'}</span></p>
            <p>数据规模：{report.数据画像?.行数 ? `${report.数据画像.行数} 行 × ${report.数据画像.列数} 列` : '—'}</p>
            {report.过期时间 && (() => {
              // 优化：非法日期（损坏数据）不再 RangeError 崩溃，直接跳过展示
              const d = new Date(report.过期时间);
              return Number.isNaN(d.getTime())
                ? null
                : <p>链接有效期至：<span className="text-gray-700">{d.toLocaleString('zh-CN', { hour12: false })}</span></p>;
            })()}
          </div>
        )}
      </div>
    </div>
  );
}