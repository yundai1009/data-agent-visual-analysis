import { useState, useEffect, useCallback } from 'react';
import { getAccountLLMKey, saveAccountLLMKey, clearAccountLLMKey } from '../api';

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
  // 账号级 Key 状态（后端存储，登录任意设备生效）
  const [accountKey, setAccountKey] = useState(null); // { has_key: bool, masked: string }

  // 挂载时加载账号 Key 状态（登录后才可能有）
  useEffect(() => {
    let cancelled = false;
    getAccountLLMKey()
      .then(info => { if (!cancelled) setAccountKey(info); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const refreshAccountKey = useCallback(() => {
    getAccountLLMKey().then(setAccountKey).catch(() => {});
  }, []);

  const activeProvider = PROVIDERS.find(p => p.id === config.provider) || PROVIDERS[0];
  const modelOptions = activeProvider.models.length > 0 ? activeProvider.models : [activeProvider.models[0]].filter(Boolean);

  const handleSave = async () => {
    const finalModel = modelOptions.includes(config.model) ? config.model : (activeProvider.models[0] || '');
    const final = { provider: config.provider, model: finalModel, apiKey: apiKey.trim() };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(final));
    setConfig(final);
    setSaved(true);
    // 浏览器级 key 保存后同步到账号（若填了 key）
    if (final.apiKey) {
      try { await saveAccountLLMKey(final.apiKey); refreshAccountKey(); } catch { /* 忽略 */ }
    }
    setOpen(false);
  };

  const handleClear = async () => {
    localStorage.removeItem(STORAGE_KEY);
    setConfig(DEFAULTS);
    setApiKey('');
    setSaved(false);
    // 同步清除账号级 Key
    try { await clearAccountLLMKey(); refreshAccountKey(); } catch { /* 忽略 */ }
    setOpen(false);
  };

  // 状态按钮显示文字
  const buttonLabel = accountKey?.has_key && !saved
    ? `AI: 账号Key ${accountKey.masked}`
    : saved
      ? `AI: ${config.model}${config.apiKey ? ' · 浏览器Key' : ''}`
      : '+ AI 模型';

  return (
    <div className="relative">
      {/* 状态行 */}
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border transition-all whitespace-nowrap ${
          saved || accountKey?.has_key
            ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
            : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${(saved || accountKey?.has_key) ? 'bg-emerald-500' : 'bg-gray-300'}`} />
        {buttonLabel}
        {(saved || accountKey?.has_key) && (
          <span className="ml-1 text-emerald-400 hover:text-red-500" onClick={(e) => { e.stopPropagation(); handleClear(); }}>✕</span>
        )}
      </button>

      {/* 浮层 */}
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-20 w-72 bg-white border border-gray-200 rounded-xl shadow-lg p-4 space-y-3">
            <p className="text-xs font-medium text-gray-700">选择 AI 模型（可选）</p>
            {accountKey?.has_key && (
              <div className="px-3 py-2 rounded-lg bg-accent-soft text-[11px] text-accent flex items-center justify-between">
                <span>账号已绑定：{accountKey.masked}</span>
                <button
                  className="text-[11px] text-gray-400 hover:text-red-500 transition-colors"
                  onClick={async () => {
                    try { await clearAccountLLMKey(); refreshAccountKey(); } catch {}
                  }}
                >解绑</button>
              </div>
            )}
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
                placeholder="留空则用服务端/账号绑定的 Key"
                autoComplete="off"
              />
            </div>
            <p className="text-[11px] text-gray-500">填写 Key 后同时保存到账号（任意设备登录生效）；留空则用服务端统一配置。</p>
            <div className="flex gap-2">
              <button className="flex-1 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all" onClick={handleSave}>保存</button>
              <button className="px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => setOpen(false)}>取消</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
