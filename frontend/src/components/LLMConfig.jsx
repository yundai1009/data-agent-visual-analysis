import { useState, useEffect } from 'react';

const STORAGE_KEY = 'llm_config';
const DEFAULTS = { baseUrl: 'https://api.deepseek.com/v1', apiKey: '', model: 'deepseek-chat' };

export function loadLLMConfig() {
  try { const c = localStorage.getItem(STORAGE_KEY); return c ? JSON.parse(c) : null; }
  catch { return null; }
}

export default function LLMConfig() {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(() => loadLLMConfig() || DEFAULTS);
  const [saved, setSaved] = useState(!!loadLLMConfig());

  useEffect(() => { setSaved(!!loadLLMConfig()); }, []);

  const handleSave = () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    setSaved(true);
    setOpen(false);
  };

  const handleClear = () => {
    localStorage.removeItem(STORAGE_KEY);
    setConfig(DEFAULTS);
    setSaved(false);
    setOpen(false);
  };

  return (
    <div className="relative">
      {/* 状态行 */}
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border transition-all whitespace-nowrap ${
          saved
            ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
            : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${saved ? 'bg-emerald-500' : 'bg-gray-300'}`} />
        {saved ? `AI: ${config.model}` : '+ AI 模型'}
        {saved && (
          <span className="ml-1 text-emerald-400 hover:text-red-500" onClick={(e) => { e.stopPropagation(); handleClear(); }}>✕</span>
        )}
      </button>

      {/* 浮层 */}
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-20 w-80 bg-white border border-gray-200 rounded-xl shadow-lg p-4 space-y-3">
            <p className="text-xs font-medium text-gray-700">配置 AI 模型（可选）</p>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">API 地址</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-indigo-400"
                value={config.baseUrl} onChange={e => setConfig(c => ({ ...c, baseUrl: e.target.value }))} />
            </div>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">API Key</label>
              <input type="password" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-indigo-400"
                value={config.apiKey} onChange={e => setConfig(c => ({ ...c, apiKey: e.target.value }))} />
            </div>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">模型名</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-indigo-400"
                value={config.model} onChange={e => setConfig(c => ({ ...c, model: e.target.value }))} />
            </div>
            <div className="flex gap-2">
              <button className="flex-1 py-2 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-all" onClick={handleSave}>保存</button>
              <button className="px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => setOpen(false)}>取消</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}