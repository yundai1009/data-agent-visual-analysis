/* =============================================================================
 * 文件：frontend/src/AppContext.jsx —— 全局状态（Context）层
 * 层级：应用根组件 <App> 下的公共 Provider，不属于任何页面（各个页面通过 useApp() 消费）
 * 功能：跨组件共享四类全局状态
 *   1. dataset   当前选中的数据集（数据管理页写入，分析/报表页读取）
 *   2. user      登录用户信息（初始从 localStorage 的 user_cache 恢复，见下方 setAuth）
 *   3. isAuthed  登录态标记（true 时 ProtectedRoute 才放行受保护页面）
 *   4. setAuth / logout  认证状态写入与清理的统一入口
 * 依赖：
 *   - localStorage：access_token / user_cache / dataset_cache / reports_cache
 *   - 自定义事件 'auth:expired'（由 api.js 的 handleAuthExpired 在全平台广播，本文件监听）
 * 被依赖：App.jsx 包裹全应用；Sidebar/Data/Analysis/Report/Account 等页面与组件 useApp()
 * ============================================================================= */
/* oxlint-disable react/only-export-components -- Context 惯例：Provider 组件 + useApp hook 同文件导出 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

const AppContext = createContext(null);

// 安全读取 localStorage 并解析 JSON：缓存损坏/不可用时静默返回 fallback，绝不抛错打断首屏渲染
function loadState(key, fallback) {
  try {
    const cached = localStorage.getItem(key);
    return cached ? JSON.parse(cached) : fallback;
  } catch { return fallback; } // JSON 损坏或隐私模式禁止访问时兜底
}

export function AppProvider({ children }) {
  // 数据集：初始从缓存恢复，实现「刷新页面后仍停留在上次数据集」的体验
  const [dataset, setDataset] = useState(() => loadState('dataset_cache', null));
  // 认证状态
  // 【关键行】用户信息初始直接读 localStorage 的 user_cache：刷新页面不丢登录态。
  // 为什么：token 与用户信息分两个 key 存储；若只存 token 不存 user，刷新后侧边栏
  //   用户名、管理员判断（user.role）都会丢失，等于半个未登录状态。
  // 删除后果：刷新后 user 变 null，侧边栏显示「未登录」，isAuthed 却仍为 true，
  //   界面出现「已登录但没名字」的割裂状态；admin 入口也消失。
  // 替代方案：初始调 GET /auth/me 拉用户信息（信息永远最新），但每次刷新多一次网络
  //   往返、接口挂了还拿不到；本地缓存 + 服务端 401 兜底（auth:expired）性价比更高。
  const [user, setUser] = useState(() => loadState('user_cache', null));
  // 【关键行】登录态标记的初始值 = 本地是否存在 access_token（而不是 user 是否存在）。
  // 为什么：token 才是访问受保护接口的凭证，user 只是展示信息；以 token 为准判断
  //   登录态，token 过期后即使 user_cache 还在也会被 401 机制踢出。
  // 删除后果：刷新后 isAuthed 恒为 false，受保护页面全部重定向登录页，永远无法再访问。
  // 替代方案：用 !!user 判断（少读一次 localStorage），但会遇到上面用户信息与 token
  //   不一致的边界，可靠性不如直接读 token。
  const [isAuthed, setIsAuthed] = useState(() => {
    // B18 修复：Safari 隐私模式/localStorage 禁用时 getItem 抛 SecurityError，需 try 包裹
    try { return !!localStorage.getItem('access_token'); } catch { return false; }
  });

  // F-S3 辅助：记录当前内存态 user_id，用于 setAuth 判断"换账号"（user_id 变化）。
  // 初始从恢复的 user 同步，mount 后随 user 变动更新。
  const userIdRef = useRef(user?.user_id ?? null);

  // 挂载时一次性清理旧版前端报表缓存（阶段 12 收尾：报表历史一律以服务端为准，
  // 避免旧版本残留的本地列表与新接口返回的数据混在一起）
  useEffect(() => {
    localStorage.removeItem('reports_cache');
  }, []);

  // F-S3 辅助：随 user 变动（登出等）同步 userIdRef，保证换账号判定准确。
  useEffect(() => {
    userIdRef.current = user?.user_id ?? null;
  }, [user]);

  // 401 全局登出：token 失效/残留时（由 api.js 的 handleAuthExpired 广播）
  // 同步清空内存态 → ProtectedRoute 检测 isAuthed=false 自动重定向登录页
  useEffect(() => {
    // 【关键行】监听全局事件 auth:expired，一旦触发就把三个内存态全部清空。
    // 为什么：任何接口返回 401 都说明 token 已不可用，但请求是散落在各页面发起的，
    //   不可能让每个页面各自处理登出；用自定义事件做「全局广播」一次收口。
    // 删除后果：401 后 token 被清除但 isAuthed 仍为 true，用户卡在受保护页面反复
    //   请求、反复报错，不会自动回登录页。
    // 替代方案：request 层直接驱动 Context（循环依赖 api.js ↔ AppContext），
    //   或每个页面 catch 401 后各自跳转（逻辑分散、易漏）；事件广播解耦最干净。
    const onAuthExpired = () => {
      setUser(null);
      setIsAuthed(false);
      setDataset(null); // 与 api.js 清除 dataset_cache 保持一致，避免旧数据集残留展示
    };
    window.addEventListener('auth:expired', onAuthExpired);
    // 组件卸载时移除监听，避免重复挂载造成的内存泄漏与重复触发
    return () => window.removeEventListener('auth:expired', onAuthExpired);
  }, []);

  // 设置认证状态（登录/注册/改名/改密成功后统一调用）：
  // 入参 token = 新 access_token；userInfo = 最新用户对象（可只传 username 变化的部分字段）
  // 业务定位：全平台唯一“写登录态”入口，保证 token / 用户信息 / 界面三处永远一致
  const setAuth = useCallback((token, userInfo) => {
    try {
      // 【关键行】第一处同步：token 写入 localStorage —— 持久化，刷新不丢。
      // 为什么：请求层每次从 localStorage 取 token（api.js getAuthHeaders），
      //   不写这里下一次请求就还在用旧 token，改名/改密后立刻被 401。
      // 删除后果：刷新后 isAuthed 变 false 被踢回登录页；或请求带旧 token 反复 401。
      // 替代方案：把 token 放 React state（不存在持久化问题之外还多一处状态源，
      //   请求层取不到要跨层传递）；localStorage 是请求层与状态层共享的最简介质。
      if (token) localStorage.setItem('access_token', token);
      // 第二处同步：用户信息写入 user_cache —— 刷新后能恢复用户名/角色。
      if (userInfo) localStorage.setItem('user_cache', JSON.stringify(userInfo));
    } catch { /* localStorage 不可用时忽略，仅本次会话有效 */ }
    // 第三处同步：更新内存态 user —— 界面立即反映新用户名（不刷新页面也生效）。
    if (userInfo) {
      // F-S3 修复：换账号（user_id 变化）时必须清 dataset_cache/reports_cache 与
      //   内存 dataset，否则 A 账号的数据会串到 B 账号界面（跨账号数据泄露）。
      //   改名/改密仍是同一 user_id，不清缓存，不影响当前会话的数据集选择。
      const prevUserId = userIdRef.current;
      if (prevUserId && prevUserId !== userInfo.user_id) {
        try {
          localStorage.removeItem('dataset_cache');
          localStorage.removeItem('reports_cache');
        } catch { /* ignore */ }
        setDataset(null);
      }
      userIdRef.current = userInfo.user_id;
      setUser(userInfo);
    }
    // 同步登录态标记：token 非空即为已登录，ProtectedRoute 据此放行。
    setIsAuthed(!!token);
  }, []);

  // 登出：手动退出/注销账号时调用，三处本地缓存 + 三处内存态全部清空
  const logout = useCallback(() => {
    try {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user_cache');
      // 【关键行】B5 修复：登出必须连数据集缓存一起清。
      // 为什么：dataset_cache 按账号维度缓存，若不清理，A 账号上传的数据会在
      //   B 账号登录后原样出现在界面上，造成跨账号数据泄露。
      // 删除后果：换账号登录看到上一个账号留下的数据集，用户直接投诉数据串号。
      // 替代方案：每次读 dataset 都带账号前缀再校验归属（改动面大、易漏）；
      //   登出清缓存这一个动作就能根除串号问题，代价最小。
      localStorage.removeItem('dataset_cache');
    } catch { /* ignore */ }
    setUser(null);
    setIsAuthed(false);
    setDataset(null);
  }, []);

  // dataset 变化时自动持久化：State 需要知道“数据集被谁选中了”，刷新后凭缓存恢复
  useEffect(() => {
    if (dataset) localStorage.setItem('dataset_cache', JSON.stringify(dataset));
  }, [dataset]);

  return (
    <AppContext.Provider value={{
      dataset, setDataset,
      user, isAuthed, setAuth, logout,
    }}>
      {children}
    </AppContext.Provider>
  );
}

// 消费全局状态的 hook：任何组件调用 const { user, logout, ... } = useApp() 即可读取/写入
// 业务定位：替代 props 层层透传，所有页面与 Sidebar 等公共组件都走这一个入口
export function useApp() {
  return useContext(AppContext);
}
