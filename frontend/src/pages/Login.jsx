// 登录页（面试讲解）
//
// 做了什么：三种模式的账号入口——登录 / 注册 / 忘记密码（邮箱验证码
//   重置），含前端校验（邮箱正则、6 位验证码）、60 秒发码倒计时、
//   成功登录后写入全局认证态并跳转数据页。
// 为什么这样设计：
//   - 模式用 useState('login' | 'register' | 'reset') 切换，复用同一
//     套表单与样式，注册/重置才展示邮箱与验证码输入；
//   - 验证码倒计时用 useEffect + setTimeout 每秒递减（存 ref 以便
//     清理），防止组件卸载后定时器继续跑；
//   - 校验放在前端只为即时反馈，真正的安全校验（密码策略、验证码
//     校验、限流）都在后端 auth 接口，前端不信任自己。
// 删除它会怎样：用户无法登录，平台不可用。
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3 } from 'lucide-react';
import { login, register, sendCode, sendResetCode, resetPassword } from '../api';
import { useApp } from '../AppContext';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function Login() {
  const navigate = useNavigate();
  const { setAuth } = useApp();
  const [mode, setMode] = useState('login'); // login | register | reset
  const [info, setInfo] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [cooldown, setCooldown] = useState(0); // 获取验证码倒计时（秒）
  const cooldownRef = useRef(null);

  // 预测数据采集：挂载时探测设备类型与渠道参数并缓存（注册请求自动上报）。
  // 为什么：注册埋点需要 来源渠道/设备类型，但注册页不收集这些输入——设备
  //   从 UA 推断、渠道从 URL 参数（channel / utm_source）带，只探测一次。
  useEffect(() => {
    try {
      if (!localStorage.getItem('tracking_device')) {
        const ua = navigator.userAgent;
        const device = /Android/i.test(ua) ? '安卓' : (/iPhone|iPad/i.test(ua) ? '苹果' : '网页');
        localStorage.setItem('tracking_device', device);
      }
      const params = new URLSearchParams(window.location.search);
      const ch = params.get('channel') || params.get('utm_source');
      if (ch && !localStorage.getItem('tracking_channel')) {
        localStorage.setItem('tracking_channel', ch);
      }
    } catch { /* ignore */ }
  }, []);

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
      await (mode === 'reset' ? sendResetCode(target) : sendCode(target));
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
      } else if (mode === 'reset') {
        // 密码重置：成功后回到登录模式提示用新密码登录
        setInfo('');
        await resetPassword(email.trim(), code.trim(), password);
        setPassword('');
        setCode('');
        setMode('login');
        setInfo('密码已重置，请用新密码登录');
        setLoading(false);
        return;
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

  const inputCls = "w-full border border-white/15 rounded-xl px-3.5 py-2.5 text-sm bg-white/[0.07] text-white placeholder:text-slate-400/70 focus:outline-none focus:border-white/40 focus:bg-white/[0.11] transition-all";
  const labelCls = "text-xs text-white/60 block mb-1.5";

  return (
    <div className="min-h-dvh relative overflow-hidden">
      {/* 背景：地球夜景——底层静态图（降级），上层视频（播放时完全覆盖，加载失败自然回落） */}
      <img className="absolute inset-0 w-full h-full object-cover" src="/login-bg.jpg" alt=""
           style={{ filter: 'brightness(1.18) contrast(1.04) saturate(1.05)' }} />
      <video className="absolute inset-0 w-full h-full object-cover" src="/bg/serene-hero.mp4"
             poster="/bg/serene-hero-poster.png" autoPlay muted loop playsInline preload="auto" />
      <div className="absolute inset-0"
           style={{
             background:
               'linear-gradient(90deg, rgba(4,10,22,.5) 0%, rgba(4,10,22,.3) 45%, rgba(4,10,22,.12) 100%), ' +
               'linear-gradient(180deg, rgba(4,10,22,.18) 0%, rgba(4,10,22,0) 45%, rgba(4,10,22,.38) 100%)',
           }} />
      {/* 底部轻微氛围光 */}
      <div className="absolute inset-x-0 bottom-0 h-64 pointer-events-none" style={{ background: 'linear-gradient(180deg, transparent, rgba(15,76,129,.25))' }} />

      <div className="relative min-h-dvh max-w-[1400px] mx-auto flex items-stretch">
        {/* 左：品牌大标题 + 副文案（Celestial 风格） */}
        <div className="hidden lg:flex flex-1 flex-col justify-center px-12 pr-16">
          <div className="flex items-center gap-3 mb-14">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center text-white shadow-lg"
                 style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)', boxShadow: '0 8px 24px -6px rgba(15,76,129,.6)' }}>
              <BarChart3 className="w-6 h-6 text-white" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">数据助手</p>
              <p className="text-xs text-white/50">自助分析平台</p>
            </div>
          </div>

          <h1 className="text-[3.4rem] leading-[1.08] font-bold tracking-tight text-white max-w-[12em]"
              style={{ textShadow: '0 4px 24px rgba(0,0,0,.5)' }}>
            把数据说成一句话<br /><span className="text-transparent bg-clip-text" style={{ backgroundImage: 'linear-gradient(92deg, #cfe6f8, #8fc3ee)' }}>图表就出来了</span>
          </h1>
          <p className="mt-6 text-[15px] text-white/85 leading-relaxed max-w-[30em]" style={{ textShadow: '0 2px 12px rgba(0,0,0,.5)' }}>
            上传 CSV，用自然语言描述分析需求，AI 自动选字段生成 18 种图表，附 Agent 决策记录与实时分析直播。
          </p>

          <div className="mt-10 flex items-center gap-2 text-xs text-white/60">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ animation: 'live-blink 1.8s infinite' }} />
            AI Agent 引擎在线 · 支持 18 种图表 · 多模型接入
          </div>
        </div>

        {/* 右：登录卡片（玻璃） */}
        <div className="flex items-center justify-center px-4 py-10 lg:px-12 w-full lg:w-[400px] lg:shrink-0">
          <div className="w-full max-w-sm rounded-2xl p-8"
               style={{ background: 'rgba(10,18,34,.55)', border: '1px solid rgba(255,255,255,.12)', backdropFilter: 'blur(18px)', boxShadow: '0 24px 60px -18px rgba(0,0,0,.6)' }}>
            <div className="text-center mb-6">
              <div className="w-11 h-11 mx-auto mb-3 rounded-xl flex items-center justify-center lg:hidden"
                   style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)' }}>
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-xl font-bold tracking-tight text-white">{mode === 'login' ? '欢迎回来' : mode === 'reset' ? '重置密码' : '创建账号'}</h1>
              <p className="text-xs text-white/50 mt-1.5">{mode === 'login' ? '登录你的数据工作台' : mode === 'reset' ? '通过邮箱验证码重置登录密码' : '注册后即可开始分析数据'}</p>
            </div>

            {info && (
              <div className="mb-4 px-3 py-2.5 rounded-lg border border-emerald-400/30 text-xs text-emerald-300" style={{ background: 'rgba(16,185,129,.12)' }}>
                {info}
              </div>
            )}

            {error && (
              <div className="mb-4 px-3 py-2.5 rounded-lg border border-red-400/30 text-xs text-red-300" style={{ background: 'rgba(220,38,38,.12)' }}>
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-3.5">
              {mode !== 'reset' && (
              <div>
                <label className={labelCls}>{mode === 'login' ? '用户名或邮箱' : '用户名'}</label>
                <input className={inputCls} value={username} onChange={(e) => setUsername(e.target.value)}
                       placeholder={mode === 'login' ? '输入用户名或邮箱' : '输入用户名'} required />
              </div>
              )}

              {mode === 'reset' && (
                <div>
                  <label className={labelCls}>邮箱</label>
                  <input type="email" className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="注册时使用的邮箱" required />
                </div>
              )}

              {(mode === 'register' || mode === 'reset') && (
                <>
                  <div>
                    <label className={labelCls}>邮箱</label>
                    <input type="email" className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="用于接收注册验证码" required />
                  </div>
                  <div>
                    <label className={labelCls}>验证码</label>
                    <div className="flex gap-2">
                      <input inputMode="numeric" maxLength={6} className={inputCls} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} placeholder="6 位验证码" required />
                      <button type="button" disabled={sending || cooldown > 0} onClick={handleSendCode}
                        className="shrink-0 px-3 py-2 rounded-lg border border-white/20 text-xs text-white/70 hover:bg-white/10 transition-all disabled:opacity-40">
                        {cooldown > 0 ? `${cooldown}s` : sending ? '发送中' : '获取验证码'}
                      </button>
                    </div>
                  </div>
                </>
              )}

              <div>
                <label className={labelCls}>密码</label>
                <input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} className={inputCls} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" required />
              </div>

              {mode === 'login' && (
                <div className="text-right -mt-1">
                  <button type="button" className="text-xs text-blue-200/80 hover:text-white transition-colors" onClick={() => { setInfo(''); setMode('reset'); setError(''); }}>
                    忘记密码？
                  </button>
                </div>
              )}

              <button type="submit" disabled={loading}
                className="w-full py-2.5 rounded-lg text-sm font-semibold text-white hover:opacity-90 transition-all disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #2e7ab8, #0f4c81)', boxShadow: '0 10px 24px -10px rgba(15,76,129,.7)' }}>
                {loading ? '处理中…' : mode === 'login' ? '登录' : mode === 'reset' ? '重置密码' : '注册'}
              </button>
            </form>

            <p className="text-center text-xs text-white/50 mt-5">
              {mode === 'login' ? '还没有账号？' : '已有账号？'}
              <button className="text-blue-200 hover:text-white ml-1 transition-colors" onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}>
                {mode === 'login' ? '去注册' : '去登录'}
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}