// 新手引导（阶段 32 · 批4）：首次登录 3 步引导浮层
// 做了什么：新用户首次进入工作台时，用 3 张卡片带他走完
//   ① 上传数据 → ② 智能分析 → ③ 查看报表 的核心路径；
//   完成后写 localStorage（onboard_done），下次不再弹出。
// 为什么这样设计：
//   - 只拦第一次：老用户完全无感（读 localStorage 立即判断，零请求）；
//   - 不打断操作：右上角"跳过"，点任意一步直接跳到对应页面；
//   - 零依赖：纯前端组件，不引入引导库，控制包体积。
// 删除后果：新用户裸奔，第一次面对空页面不知道从哪开始。

import { useState } from 'react';
import { Upload, Sparkles, BarChart3, ChevronRight, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const STEPS = [
  {
    icon: Upload,
    title: '① 上传你的数据',
    desc: '支持 CSV / Excel，上传后自动识别字段与数据质量，可一键清洗。',
    route: '/data',
    btn: '去上传数据',
  },
  {
    icon: Sparkles,
    title: '② 用一句话分析',
    desc: '在智能分析页输入"按地区统计销售额占比"，AI 自动选图表、做聚合、写结论。',
    route: '/analysis',
    btn: '去智能分析',
  },
  {
    icon: BarChart3,
    title: '③ 查看与分享报表',
    desc: '报表自动保存到历史，可导出图文 PDF、收藏星标、生成分享链接。',
    route: '/reports',
    btn: '去看报表',
  },
];

export default function Onboarding({ onDone }) {
  const [step, setStep] = useState(0);
  const navigate = useNavigate();
  const s = STEPS[step];

  const finish = () => {
    try { localStorage.setItem('onboard_done', '1'); } catch { /* ignore */ }
    onDone?.();
  };
  const go = () => {
    navigate(s.route);
    finish();
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 p-4" onClick={finish}>
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-card-lg p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <p className="text-xs font-semibold text-accent">新手上路 · 三步开始分析</p>
          <button onClick={finish} className="p-1 rounded hover:bg-gray-100 text-gray-400" title="跳过引导">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex justify-center mb-4">
          <s.icon className="w-14 h-14 text-accent" strokeWidth={1.5} />
        </div>
        <h3 className="text-base font-semibold text-gray-900 mb-2 text-center">{s.title}</h3>
        <p className="text-xs text-gray-500 leading-relaxed mb-6 text-center">{s.desc}</p>

        {/* 步骤指示点 */}
        <div className="flex justify-center gap-1.5 mb-6">
          {STEPS.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              className={`h-1.5 rounded-full transition-all ${i === step ? 'w-6 bg-accent' : 'w-1.5 bg-gray-300 hover:bg-gray-400'}`}
              aria-label={`第 ${i + 1} 步`}
            />
          ))}
        </div>

        <div className="flex gap-2">
          {step < STEPS.length - 1 && (
            <button onClick={() => setStep(step + 1)} className="flex-1 flex items-center justify-center gap-1 px-4 py-2.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 transition-all">
              下一步 <ChevronRight className="w-3 h-3" />
            </button>
          )}
          <button onClick={go} className="flex-1 px-4 py-2.5 rounded-lg bg-accent text-white text-xs font-medium hover:opacity-90 transition-all">
            {s.btn}
          </button>
        </div>
      </div>
    </div>
  );
}
