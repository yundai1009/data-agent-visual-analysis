/* =============================================================================
 * 文件：frontend/src/components/ChartRefinePanel.jsx —— 图表局部精细化编辑抽屉
 * 功能（阶段 55）：
 *   1. 自然语言指令输入（例："把X轴换成城市" / "标题改为【销售额TOP】" / "切换成饼图"）
 *   2. 结构化快捷编辑（改标题 / 换X轴 / 切饼图 / 加筛选）
 *   3. 调用后端 POST /reports/{id}/refine（本地重算，不触发 Agent / 外部工具）
 *   4. 展示「旧 → 新」变更对比清单；命中标识符禁作 Y 轴时展示拒绝原因；
 *      NL 模糊时展示需确认提示
 * 约束（用户定义）：
 *   - 只做图表层编辑；标识符/编码 ID 字段禁作 Y 轴（后端校验，前端只负责展示原因）
 *   - 确认后才落库（另存新报表，不覆盖原报表）
 * 依赖：api.js 的 refineReport；EChartsChart 渲染新 spec（由父组件 Report.jsx 处理）
 * ============================================================================= */
import { useState } from 'react';
import { X, Pencil, Loader2, Filter } from 'lucide-react';
import { refineReport } from '../api';

// 结构化快捷动作：把面板输入映射为后端编辑模型
function 快捷动作(动作, 标题, x轴, 筛选字段, 筛选值) {
  switch (动作) {
    case '改标题': return { 动作: '改标题', 标题 };
    case '换X轴': return { 动作: '换X轴', X轴: x轴 };
    case '切饼图': return { 动作: '切图表类型', 图表类型: '饼图' };
    case '加筛选': return { 动作: '加筛选', 筛选: { 字段: 筛选字段, 值: 筛选值 } };
    default: return null;
  }
}

export default function ChartRefinePanel({ show, onClose, reportId, 画像, onRefined }) {
  const [指令, set指令] = useState('');
  const [标题, set标题] = useState('');
  const [x轴, setX轴] = useState('');
  const [选中动作, set选中动作] = useState('');
  const [筛选字段, set筛选字段] = useState('');
  const [筛选值, set筛选值] = useState('');
  const [busy, setBusy] = useState(false);
  const [变更, set变更] = useState([]);       // [{字段, 旧, 新}]
  const [需确认, set需确认] = useState('');
  const [拒绝原因, set拒绝原因] = useState('');
  const [错误, set错误] = useState('');

  if (!show) return null;

  const 字段列表 = (画像?.字段列表 || []);
  const reset状态 = () => { set变更([]); set需确认(''); set拒绝原因(''); set错误(''); };

  const 提交 = async (body) => {
    reset状态();
    setBusy(true);
    try {
      const res = await refineReport(reportId, body);
      if (res.需确认) {
        set需确认(res.拒绝原因 || '需要确认修改内容');
        return;
      }
      if (res.拒绝原因) {
        set拒绝原因(res.拒绝原因);
        return;
      }
      set变更(res.变更清单 || []);
      // 成功后把新 spec 交回父组件渲染
      if (onRefined && res.新spec) onRefined(res.新spec, res.新报表ID);
    } catch (e) {
      set错误(e.message || '编辑失败，请稍后重试');
    } finally {
      setBusy(false);
    }
  };

  const 提交NL = () => {
    if (!指令.trim()) { set错误('请输入编辑指令'); return; }
    提交({ 指令: 指令.trim() });
  };

  const 提交结构化 = () => {
    if (!选中动作) { set错误('请选择编辑操作'); return; }
    const body = 快捷动作(选中动作, 标题, x轴, 筛选字段, 筛选值);
    if (!body) { set错误('请填写完整参数'); return; }
    提交({ 编辑: body });
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="w-full max-w-md h-full bg-white shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Pencil className="w-4 h-4 text-accent" /> 精细化编辑图表
          </h2>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* 描述 */}
          <p className="text-xs text-gray-400 leading-relaxed">
            对本图表做局部修改（不重新分析数据）。标识符/编码字段（如订单ID）不能作为数值 Y 轴。
            修改后另存为新报表，原报表保留。
          </p>

          {/* NL 指令 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">自然语言指令</label>
            <textarea
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent resize-none"
              placeholder="例：把X轴换成城市 / 标题改为【销售额TOP】 / 切换成饼图 / 筛选只看华东"
              value={指令}
              onChange={(e) => set指令(e.target.value)}
            />
            <button
              onClick={提交NL}
              disabled={busy}
              className="mt-2 w-full py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 inline animate-spin mr-1" /> : null}执行编辑
            </button>
          </div>

          <div className="flex items-center gap-3 text-[11px] text-gray-400">
            <span className="h-px flex-1 bg-gray-100" /> 或 <span className="h-px flex-1 bg-gray-100" />
          </div>

          {/* 结构化面板 */}
          <div className="space-y-3">
            <select
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent"
              value={选中动作}
              onChange={(e) => set选中动作(e.target.value)}
            >
              <option value="">选择编辑操作…</option>
              <option value="改标题">改标题</option>
              <option value="换X轴">换X轴（分类字段）</option>
              <option value="切饼图">切换成饼图</option>
              <option value="加筛选">增加筛选（原始数据）</option>
            </select>

            {选中动作 === '改标题' && (
              <input
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent"
                placeholder="新标题"
                value={标题}
                onChange={(e) => set标题(e.target.value)}
              />
            )}
            {选中动作 === '换X轴' && (
              <select
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent"
                value={x轴}
                onChange={(e) => setX轴(e.target.value)}
              >
                <option value="">选择 X 轴字段…</option>
                {(画像?.分类字段 || []).map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            )}
            {选中动作 === '加筛选' && (
              <div className="flex gap-2">
                <select
                  className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent"
                  value={筛选字段}
                  onChange={(e) => set筛选字段(e.target.value)}
                >
                  <option value="">筛选字段…</option>
                  {字段列表.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
                <input
                  className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-accent"
                  placeholder="筛选值"
                  value={筛选值}
                  onChange={(e) => set筛选值(e.target.value)}
                />
              </div>
            )}

            <button
              onClick={提交结构化}
              disabled={busy || !选中动作}
              className="w-full py-2 rounded-lg border border-accent text-accent text-xs font-medium hover:bg-accent-soft transition-all disabled:opacity-50"
            >
              应用结构化编辑
            </button>
          </div>

          {/* 需确认 / 拒绝原因 / 错误 */}
          {需确认 && (
            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700">
              <p className="font-semibold mb-1"><Filter className="w-3 h-3 inline mr-1" />需要确认</p>
              <p>{需确认}</p>
            </div>
          )}
          {拒绝原因 && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700 leading-relaxed">
              <p className="font-semibold mb-1">编辑被拒绝</p>
              <p>{拒绝原因}</p>
            </div>
          )}
          {错误 && <p className="text-xs text-red-600">{错误}</p>}

          {/* 变更对比清单 */}
          {变更.length > 0 && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 overflow-hidden">
              <p className="text-xs font-semibold text-emerald-700 px-3 py-2 bg-emerald-50 border-b border-emerald-200">
                ✅ 已生成新图表（另存为新报表）
              </p>
              <ul className="divide-y divide-emerald-100">
                {变更.map((it, i) => (
                  <li key={i} className="px-3 py-2 text-xs">
                    <span className="text-gray-500">{it.字段}</span>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="text-gray-400 line-through">{String(it.旧 ?? '—')}</span>
                      <span className="text-gray-300">→</span>
                      <span className="text-emerald-700 font-medium">{String(it.新 ?? '—')}</span>
                    </div>
                  </li>
                ))}
              </ul>
              <button
                onClick={onClose}
                className="w-full py-2 bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-colors"
              >
                查看新图表
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}