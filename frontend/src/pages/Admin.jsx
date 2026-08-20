// 管理员后台页（面试讲解）
//
// 做了什么：admin 角色专属的运营视图——平台统计卡片（注册用户/
//   数据集/报表/看板数）、最近 7 天报表生成趋势图（ECharts）、
//   用户列表管理。
// 为什么这样设计：
//   - 前端先按 user.role 做一次"软拦截"（非 admin 显示无权限页），
//     真正的拦截在后端依赖 get_current_user（角色校验），前端不
//     是安全边界，只是提体验；
//   - 统计与用户列表用 Promise.all 并行拉取，一次加载两路数据；
//   - 趋势数据复用报表图表的数据结构（标题/X轴/Y轴/数据），
//     直接喂给 EChartsChart 组件，不另造一套渲染逻辑。
// 删除它会怎样：管理员失去运营监控入口（接口仍在，仅前端无入口）。
import { useEffect, useMemo, useState } from 'react';
import { Shield, Users, Database, FileBarChart2, LayoutDashboard, RefreshCw, ShieldAlert, ScrollText, Gauge, Coins, FileDown } from 'lucide-react';
import { fetchStatistics, fetchAdminUsers, fetchAuditLog, fetchUsage, fetchMetrics, exportEvents } from '../api';
import { useApp } from '../AppContext';
import EChartsChart from '../components/EChartsChart';

const TABS = [
  { key: 'overview', label: '数据总览', icon: LayoutDashboard },
  { key: 'audit', label: '审计日志', icon: ScrollText },
  { key: 'usage', label: 'LLM 用量', icon: Coins },
  { key: 'metrics', label: '平台指标', icon: Gauge },
  { key: 'events', label: '事件导出', icon: FileDown },
];

const STAT_CARDS = [
  { key: '用户数', label: '注册用户', icon: Users, color: '#0f4c81' },
  { key: '数据集数', label: '数据集', icon: Database, color: '#0f766e' },
  { key: '报表数', label: '分析报表', icon: FileBarChart2, color: '#b45309' },
  { key: '看板数', label: '图表看板', icon: LayoutDashboard, color: '#64748b' },
];

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }); } catch { return iso; }
}

export default function Admin() {
  const { user } = useApp();
  const [tab, setTab] = useState('overview');
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  // 优化⑦：审计 / 用量 / 指标 / 事件导出 数据
  const [audit, setAudit] = useState([]);
  const [usage, setUsage] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [events, setEvents] = useState(null);

  const isAdmin = (user?.role === 'admin' || user?.roles?.includes?.('admin'));

  const load = async () => {
    try {
      setLoading(true);
      setError('');
      const [s, u] = await Promise.all([fetchStatistics(), fetchAdminUsers()]);
      setStats(s);
      setUsers(u?.用户列表 || []);
      // 各 tab 数据按需加载
      const tasks = [];
      if (tab === 'audit') tasks.push(fetchAuditLog().then(setAudit));
      if (tab === 'usage') tasks.push(fetchUsage().then(setUsage));
      if (tab === 'metrics') tasks.push(fetchMetrics().then(setMetrics));
      if (tab === 'events') tasks.push(exportEvents().then(setEvents));
      await Promise.all(tasks);
    } catch (e) {
      setError('加载失败：' + (e.message || e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (isAdmin) load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [tab]);

  // 趋势 → ECharts 柱状配置（复用报表图表组件的 chartConfig 结构）
  const trendChart = useMemo(() => {
    if (!stats?.趋势) return null;
    return {
      标题: '最近 7 天报表生成趋势',
      X轴: '日期',
      Y轴: ['数量'],
      数据: stats.趋势.map((d) => ({ 日期: (d?.日期 || '').slice(5), 数量: d?.数量 ?? 0 })),
    };
  }, [stats]);

  if (!isAdmin) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <div className="bg-white rounded-2xl border border-gray-200 p-14 text-center">
          <ShieldAlert className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500 mb-1">需要管理员权限</p>
          <p className="text-xs text-gray-400">当前账号无权限访问管理后台</p>
        </div>
      </div>
    );
  }

  const overview = stats?.总览 || {};

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Shield className="w-5 h-5 text-accent" /> 管理后台
          </h1>
          <p className="text-xs text-gray-400 mt-1">用户与平台用量统计 · 管理员专属</p>
          {error && <p className="mt-1.5 text-xs text-red-500">{error}</p>}
        </div>
        <button
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all"
          onClick={load}
          disabled={loading}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </button>
      </div>

      {/* 优化⑦：Tab 切换（总览 / 审计 / 用量 / 指标 / 事件导出） */}
      <div className="flex items-center gap-1 mb-5 border-b border-gray-100">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs transition-colors border-b-2 ${
              tab === t.key ? 'border-accent text-accent font-medium' : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            <t.icon className="w-3.5 h-3.5" /> {t.label}
          </button>
        ))}
      </div>

      {/* 统计卡片 */}
      {tab === 'overview' && (
        <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        {STAT_CARDS.map((c) => (
          <div key={c.key} className="bg-white rounded-2xl border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-400">{c.label}</p>
              <c.icon className="w-4 h-4" style={{ color: c.color }} />
            </div>
            <p className="text-2xl font-semibold text-gray-900 mt-1.5" style={{ color: c.color }}>
              {loading && stats == null ? '…' : (overview[c.key] ?? 0)}
            </p>
          </div>
        ))}
      </div>

      {/* 趋势图 */}
      {trendChart && (
        <div className="bg-white rounded-2xl border border-gray-200 p-5 mb-5">
          <EChartsChart chartType="bar" chartConfig={trendChart} height={220} />
        </div>
      )}

      {/* 用户表格 */}
      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-800">用户列表（{users.length}）</p>
          <span className="text-[11px] text-gray-400">按注册时间排序，敏感字段已脱敏</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-100">
                <th className="text-left px-5 py-3 font-medium">用户名</th>
                <th className="text-left px-4 py-3 font-medium">邮箱</th>
                <th className="text-left px-4 py-3 font-medium">角色</th>
                <th className="text-left px-4 py-3 font-medium">注册时间</th>
                <th className="text-right px-4 py-3 font-medium">数据集</th>
                <th className="text-right px-4 py-3 font-medium">报表</th>
                <th className="text-left px-5 py-3 font-medium">最近报表</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {users.map((u) => (
                <tr key={u.用户ID} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-5 py-3 font-medium text-gray-800">{u.用户名}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{u.邮箱 || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`text-[10px] px-2 py-0.5 rounded-md font-medium ${
                      u.角色 === 'admin' ? 'bg-accent-soft text-accent' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {u.角色 === 'admin' ? '管理员' : '分析师'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{fmtTime(u.注册时间)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{u.数据集数}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{u.报表数}</td>
                  <td className="px-5 py-3 text-xs text-gray-500 whitespace-nowrap">{fmtTime(u.最近报表时间)}</td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={7} className="text-center py-8 text-xs text-gray-400">暂无用户</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
        </>
      )}

      {/* 优化⑦：审计日志 */}
      {tab === 'audit' && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-800">操作审计日志（最近 {audit.length} 条）</p>
            <span className="text-[11px] text-gray-400">谁在何时做了什么，支持按用户过滤</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b border-gray-100">
                  <th className="text-left px-5 py-3 font-medium">时间</th>
                  <th className="text-left px-4 py-3 font-medium">用户名</th>
                  <th className="text-left px-4 py-3 font-medium">操作</th>
                  <th className="text-left px-4 py-3 font-medium">对象</th>
                  <th className="text-left px-5 py-3 font-medium">详情</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {audit.map((a) => (
                  <tr key={a.id} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-5 py-2.5 text-xs text-gray-500 whitespace-nowrap">{fmtTime(a.时间)}</td>
                    <td className="px-4 py-2.5 text-xs font-medium text-gray-700">{a.用户名 || '—'}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-700">{a.操作}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">{a.对象类型 ? `${a.对象类型}:${(a.对象ID || '').slice(0, 10)}` : '—'}</td>
                    <td className="px-5 py-2.5 text-xs text-gray-400 max-w-[320px] truncate">{a.详情 || '—'}</td>
                  </tr>
                ))}
                {audit.length === 0 && <tr><td colSpan={5} className="text-center py-8 text-xs text-gray-400">暂无审计记录</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 优化⑦：LLM 用量 */}
      {tab === 'usage' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-800 mb-3">LLM Token 用量（近 7 天）</p>
          {usage && (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                {[
                  ['请求数', usage.记录数],
                  ['输入 tokens', usage.prompt_tokens],
                  ['输出 tokens', usage.completion_tokens],
                  ['总 tokens', usage.total_tokens],
                ].map(([label, val]) => (
                  <div key={label} className="border border-gray-100 rounded-xl p-3">
                    <p className="text-[11px] text-gray-400">{label}</p>
                    <p className="text-lg font-semibold text-gray-900 mt-0.5">{(val ?? 0).toLocaleString()}</p>
                  </div>
                ))}
              </div>
              {usage.按天 && usage.按天.length > 0 && (
                <>
                  <p className="text-[11px] text-gray-400 mb-1.5">按天分布</p>
                  <table className="w-full text-sm">
                    <tbody className="divide-y divide-gray-50">
                      {usage.按天.map((d) => (
                        <tr key={d.日期}>
                          <td className="py-1.5 text-xs text-gray-600">{d.日期}</td>
                          <td className="py-1.5 text-right text-xs text-gray-700">{d.记录数} 次 · {(d.tokens ?? 0).toLocaleString()} tokens</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </>
          )}
          {!usage && !loading && <p className="text-xs text-gray-400 py-4 text-center">暂无用量数据</p>}
        </div>
      )}

      {/* 优化⑦：平台指标 */}
      {tab === 'metrics' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-800 mb-3">平台监控指标</p>
          {metrics && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                ['用户数', metrics.用户数],
                ['数据集数', metrics.数据集数],
                ['报表数', metrics.报表数],
                ['看板数', metrics.看板数],
                ['今日生成报表', metrics.今日生成报表],
                ['近7天生成报表', metrics.近7天生成报表],
              ].map(([label, val]) => (
                <div key={label} className="border border-gray-100 rounded-xl p-3">
                  <p className="text-[11px] text-gray-400">{label}</p>
                  <p className="text-lg font-semibold text-gray-900 mt-0.5">{val ?? 0}</p>
                </div>
              ))}
            </div>
          )}
          {!metrics && !loading && <p className="text-xs text-gray-400 py-4 text-center">暂无指标数据</p>}
        </div>
      )}

      {/* 优化⑦：预测事件导出 */}
      {tab === 'events' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-800 mb-1">预测数据事件导出</p>
          <p className="text-xs text-gray-400 mb-4">导出四张事件表 CSV 到服务端 data/export/，供预测系统使用</p>
          {events && (
            <>
              <p className="text-xs text-gray-600 mb-2">导出目录：{events.导出目录}</p>
              <div className="space-y-1 mb-3">
                {Object.entries(events.文件 || {}).map(([table, info]) => (
                  <div key={table} className="flex items-center justify-between text-xs text-gray-600 border border-gray-100 rounded-lg px-3 py-2">
                    <span>{table}.csv</span>
                    <span className="text-gray-400">{info.路径}</span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-amber-600">{events.提示}</p>
            </>
          )}
          {!events && !loading && <p className="text-xs text-gray-400 py-4 text-center">暂无导出信息</p>}
        </div>
      )}
    </div>
  );
}