import { useState, useEffect } from 'react';

const STORAGE_KEY = 'llm_config';

// 只允许选择服务端白名单内的 provider + model，不输入 Key / Base-URL
const PROVIDERS = [
  { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-reasoner'] },
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4o'] },
  { id: 'siliconflow', label: '硅基流动', models: [] },
];

const DEFAULTS = { provider: 'deepseek', model: 'deepseek-chat' };

export function loadLLMConfig() {
  try { const c = localStorage.getItem(STORAGE_KEY); return c ? JSON.parse(c) : null; }
  catch { return null; }
}

export default function LLMConfig() {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(() => loadLLMConfig() || DEFAULTS);
  const [apiKey, setApiKey] = useState(() => loadLLMConfig()?.apiKey || '');
  const [saved, setSaved] = useState(!!loadLLMConfig());

  useEffect(() => { setSaved(!!loadLLMConfig()); }, []);

  const activeProvider = PROVIDERS.find(p => p.id === config.provider) || PROVIDERS[0];
  const modelOptions = activeProvider.models.length > 0 ? activeProvider.models : [activeProvider.models[0]].filter(Boolean);

  const handleSave = () => {
    // 若当前模型不在新 provider 的模型列表里，回退到该 provider 默认
    const finalModel = modelOptions.includes(config.model) ? config.model : (activeProvider.models[0] || '');
    const final = { provider: config.provider, model: finalModel, apiKey: apiKey.trim() };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(final));
    setConfig(final);
    setSaved(true);
    setOpen(false);
  };

  const handleClear = () => {
    localStorage.removeItem(STORAGE_KEY);
    setConfig(DEFAULTS);
    setApiKey('');
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
        {saved ? `AI: ${config.model}${config.apiKey ? ' · 自带Key' : ''}` : '+ AI 模型'}
        {saved && (
          <span className="ml-1 text-emerald-400 hover:text-red-500" onClick={(e) => { e.stopPropagation(); handleClear(); }}>✕</span>
        )}
      </button>

      {/* 浮层 */}
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-20 w-72 bg-white border border-gray-200 rounded-xl shadow-lg p-4 space-y-3">
            <p className="text-xs font-medium text-gray-700">选择 AI 模型（可选）</p>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">服务商</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                value={config.provider}
                onChange={e => setConfig(c => ({ provider: e.target.value, model: '' }))}
              >
                {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">模型</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                value={config.model}
                onChange={e => setConfig(c => ({ ...c, model: e.target.value }))}
                disabled={modelOptions.length === 0}
              >
                {modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-gray-400 block mb-1">API Key（可选）</label>
              <input
                type="password"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="留空则使用服务端配置的 Key"
                autoComplete="off"
              />
            </div>
            <p className="text-[11px] text-gray-300">填写自己的 Key 时，生成报表消耗你自己的额度；留空使用服务端统一配置。Key 仅保存在本机浏览器。</p>
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
