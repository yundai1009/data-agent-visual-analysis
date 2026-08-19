// LLM 配置弹窗（面试讲解）
//
// 做了什么：账号设置里的"模型配置"——选供应商/模型、填 API Key
//   （BYOK 自带 Key）、管理自定义供应商（新增/测试连通性/删除）。
// 为什么这样设计：
//   - 分预设（服务端白名单 providers）与自定义（用户自建 base_url +
//     Key，后端做 SSRF 校验）两个 tab，自定义供应商先"测试"拉取
//     模型列表再保存，避免手填模型名出错；
//   - 选择结果存 localStorage（llm_config），分析请求时前端从
//     localStorage 读取、经请求头 x-llm-provider / x-llm-model /
//     x-llm-api-key 传给后端——Key 不落 localStorage 明文以外的
//     任何前端持久化（不写库），后端也只在本请求内存中使用；
//   - 账号级 Key 可一键保存到后端（加密落库），实现"登录即用"。
// 删除它会怎样：用户无法切换模型/供应商，自定义供应商功能失效。
import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, Loader2, Check } from 'lucide-react';
import { getAccountLLMKey, saveAccountLLMKey, clearAccountLLMKey, fetchLLMProviders, saveCustomProvider, deleteCustomProvider, testCustomProvider } from '../api';

const STORAGE_KEY = 'llm_config';

const DEFAULTS = { provider: 'deepseek', model: 'deepseek-chat' };

function loadLLMConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const sess = sessionStorage.getItem(STORAGE_KEY);
    const config = raw ? JSON.parse(raw) : {};
    // F-M10：sessionStorage 覆盖（仅本次会话的 Key 优先于持久配置）
    if (sess) return { ...config, ...JSON.parse(sess) };
    return raw ? config : null;
  } catch { return null; }
}

export default function LLMConfig() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('preset'); // preset | custom
  const [providers, setProviders] = useState([]); // 预设 + 自定义
  const [config, setConfig] = useState(() => loadLLMConfig() || DEFAULTS);
  const [apiKey, setApiKey] = useState(() => loadLLMConfig()?.apiKey || '');
  const [saved, setSaved] = useState(!!loadLLMConfig());
  const [accountKey, setAccountKey] = useState(null);
  // 自定义供应商表单
  const [form, setForm] = useState({ name: '', base_url: '', api_key: '', models: [], default: '' });
  const [formError, setFormError] = useState('');
  const [testing, setTesting] = useState(false);

  const refreshAll = useCallback(() => {
    getAccountLLMKey().then(setAccountKey).catch(() => {});
    fetchLLMProviders().then(res => setProviders(res.providers || [])).catch(() => {});
  }, []);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  const presets = providers.filter(p => !p.custom);
  const customs = providers.filter(p => p.custom);
  const activeProvider = providers.find(p => p.id === config.provider) || presets[0];
  const modelOptions = activeProvider?.models?.length ? activeProvider.models : [activeProvider?.default].filter(Boolean);

  const handleSave = async () => {
    const finalModel = modelOptions.includes(config.model) ? config.model : (activeProvider?.default || modelOptions[0] || '');
    const key = apiKey.trim();
    const providerId = activeProvider?.id || config.provider;
    if (key) {
      // F-M10 修复：Key 持久化必须二次确认；取消则"仅本次会话"（sessionStorage）。
      const keep = window.confirm(
        '将 API Key 保存到本机浏览器（下次打开自动带出）？\n确定＝长期保存到 localStorage；取消＝仅本次会话使用，关闭页面后需重新填写。'
      );
      try {
        const payload = { provider: providerId, model: finalModel, apiKey: key };
        if (keep) localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      } catch { /* 隐私模式等：忽略，仅内存生效 */ }
      // 保存到账号（服务端加密落库）也需单独确认
      if (keep && window.confirm('同时绑定到账号？（加密存服务端，登录后任意设备自动生效）')) {
        try { await saveAccountLLMKey(key); refreshAll(); } catch { /* ignore */ }
      }
    } else {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ provider: providerId, model: finalModel, apiKey: '' })); } catch { /* ignore */ }
    }
    setConfig({ provider: providerId, model: finalModel, apiKey: key });
    setSaved(true);
    setOpen(false);
  };

  const handleClear = async () => {
    localStorage.removeItem(STORAGE_KEY);
    setConfig(DEFAULTS);
    setApiKey('');
    setSaved(false);
    try { await clearAccountLLMKey(); refreshAll(); } catch { /* ignore */ }
    setOpen(false);
  };

  const handleTest = async () => {
    if (!form.base_url || !form.api_key) { setFormError('请先填写 API 地址和 Key'); return; }
    setFormError('');
    setTesting(true);
    try {
      const res = await testCustomProvider(form.base_url, form.api_key);
      setForm(f => ({ ...f, models: res.models || [], default: (res.models || [])[0] || '' }));
    } catch (e) {
      setFormError(e.message || '测试失败');
    }
    setTesting(false);
  };

  const handleAddCustom = async () => {
    if (!form.name || !form.base_url) { setFormError('名称和 API 地址必填'); return; }
    setFormError('');
    try {
      await saveCustomProvider({ ...form, api_key: form.api_key });
      // F-M10 修复：写入 localStorage 的 Key 也需确认；取消则"仅本次会话"。
      const key = form.api_key || '';
      const payload = { provider: form.name, model: form.default || '', apiKey: key };
      try {
        if (key && !window.confirm('将 API Key 保存到本机浏览器（下次打开自动带出）？取消＝仅本次会话使用。')) {
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } else {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        }
      } catch { /* 隐私模式等：忽略 */ }
      setConfig({ provider: form.name, model: form.default || '', apiKey: key });
      setSaved(true);
      setForm({ name: '', base_url: '', api_key: '', models: [], default: '' });
      refreshAll();
      setTab('preset');
    } catch (e) {
      setFormError(e.message || '保存失败');
    }
  };

  const handleDeleteCustom = async (name) => {
    if (!window.confirm(`删除自定义供应商「${name}」？`)) return;
    try {
      await deleteCustomProvider(name);
      refreshAll();
    } catch { /* ignore */ }
  };

  const buttonLabel = accountKey?.has_key && !saved
    ? `AI: 账号Key ${accountKey.masked}`
    : saved
      ? `AI: ${config.model}${config.apiKey ? ' · 自带Key' : ''}`
      : '+ AI 模型';

  return (
    <div className="relative">
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

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-20 w-[22rem] bg-white border border-gray-200 rounded-xl shadow-xl p-0 overflow-hidden">
            {/* 标签页：推荐预设 / 自定义供应商 */}
            <div className="flex border-b border-gray-100">
              {[['preset', '推荐预设'], ['custom', '自定义供应商']].map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
                    tab === id ? 'bg-accent text-white' : 'text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="p-4 max-h-[26rem] overflow-y-auto">
              {tab === 'preset' && (
                <>
                  {accountKey?.has_key && (
                    <div className="px-3 py-2 rounded-lg bg-accent-soft text-[11px] text-accent flex items-center justify-between mb-3">
                      <span>账号已绑定：{accountKey.masked}</span>
                      <button className="text-gray-400 hover:text-red-500 transition-colors" onClick={handleClear}>解绑</button>
                    </div>
                  )}
                  {/* 供应商卡片 */}
                  <div className="grid grid-cols-2 gap-2">
                    {presets.map(p => (
                      <button
                        key={p.id}
                        onClick={() => setConfig(c => ({ ...c, provider: p.id, model: p.default || '' }))}
                        className={`rounded-lg border p-2.5 text-left transition-all ${
                          config.provider === p.id ? 'border-accent bg-accent-soft/60' : 'border-gray-200 hover:border-accent/40 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium text-gray-800">{p.label}</span>
                          {config.provider === p.id && <Check className="w-3.5 h-3.5 text-accent" />}
                        </div>
                        <p className="text-[10px] text-gray-400 mt-0.5">{p.models.length} 个模型</p>
                      </button>
                    ))}
                  </div>

                  {/* 选中供应商的模型 + Key */}
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="text-[11px] text-gray-400 block mb-1">模型</label>
                      <select
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                        value={config.model}
                        onChange={e => setConfig(c => ({ ...c, model: e.target.value }))}
                      >
                        {modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
                        {modelOptions.length === 0 && <option value="">（暂无模型，请填 Key 或选其他供应商）</option>}
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
                    <p className="text-[10px] text-gray-400 leading-relaxed">填 Key 后同时保存到账号（任意设备登录生效）；留空用服务端统一配置。</p>
                    <div className="flex gap-2">
                      <button className="flex-1 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all" onClick={handleSave}>使用此供应商</button>
                      <button className="px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-all" onClick={() => setOpen(false)}>取消</button>
                    </div>
                  </div>
                </>
              )}

              {tab === 'custom' && (
                <>
                  {/* 已添加的自定义供应商 */}
                  {customs.length > 0 && (
                    <div className="space-y-2 mb-3">
                      {customs.map(p => (
                        <div key={p.id} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200">
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-gray-700">{p.label}{p.has_key ? '' : '（未填 Key）'}</p>
                            <p className="text-[10px] text-gray-400 truncate">{p.base_url}</p>
                          </div>
                          <button
                            onClick={() => setConfig({ provider: p.id, model: p.default || '', apiKey: '' })}
                            className="text-[11px] px-2 py-1 rounded-md bg-accent-soft text-accent hover:bg-accent-soft/70 transition-colors"
                          >选用</button>
                          <button className="text-gray-300 hover:text-red-500 transition-colors" onClick={() => handleDeleteCustom(p.id)}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 添加表单 */}
                  <div className="space-y-3">
                    <p className="text-xs font-medium text-gray-700">添加自定义供应商</p>
                    <div>
                      <label className="text-[11px] text-gray-400 block mb-1">供应商名称</label>
                      <input
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                        value={form.name}
                        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                        placeholder="如：我的中转站"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-gray-400 block mb-1">API 地址（base_url）</label>
                      <input
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                        value={form.base_url}
                        onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
                        placeholder="https://api.example.com/v1"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-gray-400 block mb-1">API Key</label>
                      <input
                        type="password"
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                        value={form.api_key}
                        onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                        placeholder="输入 API Key（保存到你的账号）"
                      />
                    </div>

                    <button
                      className="w-full py-2 rounded-lg border border-accent/30 text-xs text-accent hover:bg-accent-soft/50 transition-all flex items-center justify-center gap-1.5"
                      onClick={handleTest}
                      disabled={testing}
                    >
                      {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                      测试并获取模型
                    </button>

                    {form.models.length > 0 && (
                      <div>
                        <label className="text-[11px] text-gray-400 block mb-1">模型列表（{form.models.length} 个，来自接口）</label>
                        <select
                          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs bg-gray-50 focus:outline-none focus:border-accent"
                          value={form.default}
                          onChange={e => setForm(f => ({ ...f, default: e.target.value }))}
                        >
                          {form.models.map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </div>
                    )}

                    {formError && <p className="text-[11px] text-red-500">{formError}</p>}

                    <button
                      className="w-full py-2 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-deep transition-all"
                      onClick={handleAddCustom}
                      disabled={testing} // 优化：测试连通性期间禁保存，防误提交未验证配置
                    >{testing ? '测试中…' : '保存供应商'}</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
