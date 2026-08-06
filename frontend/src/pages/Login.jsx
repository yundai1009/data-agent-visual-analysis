import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3 } from 'lucide-react';
import { login, register, sendCode } from '../api';
import { useApp } from '../AppContext';

const SciFiHero = lazy(() => import('../components/SciFiHero'));

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

  const inputCls = "w-full border border-white/10 rounded-lg px-3 py-2.5 text-sm bg-white/[0.06] text-white placeholder:text-gray-500 focus:outline-none focus:border-accent-soft focus:bg-white/[0.09] transition-all";
  const labelCls = "text-xs text-gray-400 block mb-1.5";

  return (
    <div
      className="min-h-dvh relative overflow-hidden flex items-stretch"
      style={{
        background:
          'radial-gradient(1100px 700px at 18% -8%, rgba(15,76,129,.45), transparent 60%), ' +
          'radial-gradient(900px 650px at 92% 110%, rgba(63,123,184,.22), transparent 55%), ' +
          'linear-gradient(155deg, #070d1a 0%, #0b1a2e 55%, #0a1424 100%)',
      }}
    >
      {/* 装饰：网格 + 光晕 + 浮动粒子 */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.35]"
           style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px)', backgroundSize: '48px 48px', maskImage: 'radial-gradient(ellipse 80% 70% at 50% 30%, black 30%, transparent 75%)' }} />
      <div className="absolute -top-32 -left-24 w-[480px] h-[480px] rounded-full pointer-events-none"
           style={{ background: 'radial-gradient(circle, rgba(15,76,129,.5), transparent 65%)', filter: 'blur(40px)', animation: 'motion-glow 9s ease-in-out infinite' }} />
      <div className="absolute bottom-[-160px] right-[-80px] w-[520px] h-[520px] rounded-full pointer-events-none"
           style={{ background: 'radial-gradient(circle, rgba(63,123,184,.35), transparent 62%)', filter: 'blur(44px)', animation: 'motion-glow 11s ease-in-out infinite reverse' }} />
      {/* 浮动粒子 */}
      {[['12%', '22%', 5, '6s'], ['78%', '18%', 4, '7.5s'], ['22%', '70%', 6, '8s'], ['68%', '64%', 4, '6.5s'], ['44%', '38%', 3, '9s'], ['88%', '82%', 5, '7s']].map(([x, y, s, d], i) => (
        <span key={i} className="absolute rounded-full bg-accent-soft/60 pointer-events-none"
              style={{ left: x, top: y, width: s, height: s, filter: 'blur(1px)', animation: `motion-float ${d} ease-in-out infinite`, animationDelay: `${i * 0.7}s` }} />
      ))}

      <div className="relative w-full max-w-[1400px] mx-auto lg:grid lg:grid-cols-[1.12fr_1fr]">
        {/* 左：品牌区（大屏，3D 玻璃球体 hero） */}
        <div className="hidden lg:flex flex-col justify-between p-12 pr-10 relative overflow-hidden">
          <div className="flex items-center gap-3 relative z-10">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shadow-lg"
                 style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)', boxShadow: '0 8px 24px -6px rgba(15,76,129,.6)' }}>
              <BarChart3 className="w-6 h-6 text-white" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">数据助手</p>
              <p className="text-xs text-slate-400">自助分析平台</p>
            </div>
          </div>

          {/* 科幻 3D 场景（Three.js：发光球体 + 光环 + 粒子星云 + 数据立方体 + 鼠标跟随） */}
          <div className="flex-1 relative min-h-[340px]">
            <Suspense fallback={<div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">3D 场景加载中…</div>}>
              <SciFiHero />
            </Suspense>
          </div>

          <div className="relative z-10">
            <h1
              className="text-[3.2rem] leading-[1.12] font-bold tracking-tight"
              style={{
                background: 'linear-gradient(92deg, #ffffff 18%, #8fc3ee 45%, #ffffff 72%)',
                backgroundSize: '200% auto',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                animation: 'motion-title 6s linear infinite',
              }}
            >
              把数据说成一句话<br />图表就出来了
            </h1>
            <p className="mt-5 text-sm text-slate-300 leading-relaxed max-w-[32em]">
              上传 CSV，用自然语言描述分析需求，18 种图表自动选字段生成，附 Agent 决策记录与实时分析直播。
            </p>
            <div className="mt-8 flex items-center gap-2 text-[11px] text-slate-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ animation: 'live-blink 1.8s infinite' }} />
              AI Agent 引擎在线 · 支持 18 种图表 · 多模型接入
            </div>
          </div>

          <p className="text-xs text-slate-500 mt-6 relative z-10">登录后数据按账号隔离 · 演示模式免登录</p>
        </div>

        {/* 右：表单区（深色玻璃） */}
        <div className="flex items-center justify-center px-4 py-10 lg:py-0">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 p-8"
               style={{ background: 'linear-gradient(165deg, rgba(255,255,255,.07), rgba(255,255,255,.02))', backdropFilter: 'blur(16px)', boxShadow: '0 24px 60px -18px rgba(0,0,0,.55)' }}>
            <div className="text-center mb-6">
              <div className="w-11 h-11 mx-auto mb-3 rounded-xl lg:hidden flex items-center justify-center"
                   style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}>
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-xl font-bold tracking-tight text-white">{mode === 'login' ? '欢迎回来' : '创建账号'}</h1>
              <p className="text-xs text-slate-400 mt-1.5">{mode === 'login' ? '登录你的数据工作台' : '注册后即可开始分析数据'}</p>
            </div>

            {error && (
              <div className="mb-4 px-3 py-2.5 rounded-lg border border-red-400/30 text-xs text-red-300" style={{ background: 'rgba(220,38,38,.12)' }}>
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-3.5">
              <div>
                <label className={labelCls}>{mode === 'login' ? '用户名或邮箱' : '用户名'}</label>
                <input
                  className={inputCls}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={mode === 'login' ? '输入用户名或邮箱' : '输入用户名'}
                  required
                />
              </div>

              {mode === 'register' && (
                <>
                  <div>
                    <label className={labelCls}>邮箱</label>
                    <input
                      type="email"
                      className={inputCls}
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="用于接收注册验证码"
                      required
                    />
                  </div>
                  <div>
                    <label className={labelCls}>验证码</label>
                    <div className="flex gap-2">
                      <input
                        inputMode="numeric"
                        maxLength={6}
                        className={inputCls}
                        value={code}
                        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                        placeholder="6 位数字验证码"
                        required
                      />
                      <button
                        type="button"
                        disabled={sending || cooldown > 0}
                        onClick={handleSendCode}
                        className="shrink-0 px-3 py-2 rounded-lg border border-accent-soft/40 text-xs text-accent-soft hover:bg-accent-soft/10 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {cooldown > 0 ? `${cooldown}s` : sending ? '发送中' : '获取验证码'}
                      </button>
                    </div>
                  </div>
                </>
              )}

              <div>
                <label className={labelCls}>密码</label>
                <input
                  type="password"
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  className={inputCls}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 6 位"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-lg text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)', boxShadow: '0 10px 24px -10px rgba(15,76,129,.7)' }}
              >
                {loading ? '处理中…' : mode === 'login' ? '登录' : '注册'}
              </button>
            </form>

            <p className="text-center text-xs text-slate-400 mt-5">
              {mode === 'login' ? '还没有账号？' : '已有账号？'}
              <button className="text-accent-soft hover:text-white ml-1 transition-colors" onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}>
                {mode === 'login' ? '去注册' : '去登录'}
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
