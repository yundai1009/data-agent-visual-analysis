import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register, sendCode } from '../api';
import { useApp } from '../AppContext';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function Login() {
  const navigate = useNavigate();
  const { setAuth } = useApp();
  const [mode, setMode] = useState('login'); // login | register
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [cooldown, setCooldown] = useState(0); // 获取验证码倒计时（秒）
  const cooldownRef = useRef(null);

  // 验证码倒计时
  useEffect(() => {
    if (cooldown <= 0) return;
    cooldownRef.current = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(cooldownRef.current);
  }, [cooldown]);

  const switchMode = (m) => {
    setMode(m);
    setError('');
  };

  const handleSendCode = async () => {
    const target = email.trim();
    if (!EMAIL_RE.test(target)) {
      setError('请输入正确的邮箱地址');
      return;
    }
    setError('');
    setSending(true);
    try {
      await sendCode(target);
      setCooldown(60);
    } catch (err) {
      setError(err.message || '验证码发送失败');
    }
    setSending(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      let res;
      if (mode === 'register') {
        if (!EMAIL_RE.test(email.trim())) {
          setError('请输入正确的邮箱地址');
          setLoading(false);
          return;
        }
        if (!/^\d{6}$/.test(code.trim())) {
          setError('请输入 6 位数字验证码');
          setLoading(false);
          return;
        }
        res = await register(username.trim(), email.trim(), code.trim(), password);
      } else {
        res = await login(username.trim(), password);
      }
      setAuth(res.access_token, res.user);
      navigate('/data');
    } catch (err) {
      setError(err.message || '操作失败');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-dvh grid lg:grid-cols-[1.15fr_1fr] bg-surface">
      {/* 左：品牌区（大屏显示） */}
      <div className="hidden lg:flex flex-col justify-between p-12 text-white"
           style={{ background: 'linear-gradient(160deg, #0f4c81 0%, #123f68 60%, #0f2f4f 100%)' }}>
        <div className="w-12 h-12 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center text-2xl">📊</div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight leading-snug text-white">把数据说成一句话<br />图表就出来了</h1>
          <p className="mt-4 text-sm text-slate-300 leading-relaxed max-w-[30em]">上传 CSV，用自然语言描述分析需求，18 种图表自动选字段生成，附 Agent 决策记录。</p>
        </div>
        <p className="text-xs text-slate-400">登录后数据按账号隔离 · 演示模式免登录</p>
      </div>
      {/* 右：表单区 */}
      <div className="flex items-center justify-center px-4 py-10 bg-white">
        <div className="w-full max-w-sm">
          <div className="text-center mb-6">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-accent-soft flex items-center justify-center text-2xl lg:hidden">📊</div>
            <h1 className="text-xl font-bold tracking-tight text-ink">{mode === 'login' ? '登录' : '注册'}</h1>
            <p className="text-xs text-gray-400 mt-1">{mode === 'login' ? '使用用户名或邮箱' : '创建新账号（邮箱验证码）'}</p>
          </div>

          {error && (
            <div className="mb-4 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">{mode === 'login' ? '用户名或邮箱' : '用户名'}</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 focus:outline-none focus:border-accent"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={mode === 'login' ? '输入用户名或邮箱' : '输入用户名'}
                required
              />
            </div>

            {mode === 'register' && (
              <>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">邮箱</label>
                  <input
                    type="email"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 focus:outline-none focus:border-accent"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="用于接收注册验证码"
                    required
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">验证码</label>
                  <div className="flex gap-2">
                    <input
                      inputMode="numeric"
                      maxLength={6}
                      className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 focus:outline-none focus:border-accent"
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="6 位数字验证码"
                      required
                    />
                    <button
                      type="button"
                      disabled={sending || cooldown > 0}
                      onClick={handleSendCode}
                      className="shrink-0 px-3 py-2 rounded-lg border border-gray-200 text-xs text-accent hover:bg-accent-soft transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {cooldown > 0 ? `${cooldown} 秒后重发` : sending ? '发送中…' : '获取验证码'}
                    </button>
                  </div>
                </div>
              </>
            )}

            <div>
              <label className="text-xs text-gray-400 block mb-1">密码</label>
              <input
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 focus:outline-none focus:border-accent"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="至少 6 位"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-deep transition-all disabled:opacity-50"
            >
              {loading ? '处理中…' : mode === 'login' ? '登录' : '注册'}
            </button>
          </form>

          <p className="text-center text-xs text-gray-400 mt-4">
            {mode === 'login' ? '还没有账号？' : '已有账号？'}
            <button className="text-accent hover:text-accent-deep ml-1" onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}>
              {mode === 'login' ? '去注册' : '去登录'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
