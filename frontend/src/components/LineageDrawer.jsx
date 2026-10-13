// 阶段 六十 · 看板血缘关系视图的详情抽屉。
//
// 做了什么：点关系图上的节点后从右侧滑出面板，回答"这个节点是谁、被谁用着"。
// 三种节点三种内容：数据集（谁在用它）/ 报表（它的字段与结论）/ 字段（谁在复用它）。
// 为什么做成纯展示组件：所有文案都来自 props 里的 节点.明细（由 utils/看板血缘.js 算好），
//   抽屉自己不取数、不发请求——好处是每段文案都能被单测断言，数据口径只需要盯一个文件。
// 关闭为什么必须自带：LineageGraph 只在 dataType==='node' 时回传节点ID，
//   点画布空白不产生任何信号，父组件无法据此关闭；所以 X / Esc / 遮罩三条关闭路径都在抽屉内。
// 安全：文件名、标题、字段名都来自用户上传的数据，这里只用文本节点（React 默认转义），
//   不用 dangerouslySetInnerHTML，天然没有注入面，所以不需要 utils/图表主题.js 的 转义HTML。
// 长列表为什么折叠：一张宽表能有几十个字段，全渲染会把抽屉撑爆并让其它区块滚出视野。
//   换节点或关闭（父组件传 节点={null}）时把展开态清掉，避免重开同一节点还停在"展开全部"。
import { useEffect, useState } from 'react';
import { X, ExternalLink, Database, Table2, Hash, ArrowRight } from 'lucide-react';

const 图标 = { 数据集: Database, 报表: Table2, 字段: Hash };
const 副标题 = { 数据集: '数据来源', 报表: '分析报表', 字段: '复用字段' };
const 折叠条数 = 8;   // 超过这个条数就先折叠，给抽屉头部/概览留位置

/** 报表行：类型徽章 + 可点的标题（点标题跳完整报表）+ 外链图标 */
function 报表行({ 项, onOpenReport }) {
  return (
    <li className="flex items-center gap-2 py-1.5">
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 shrink-0">{项.图表类型 || '图表'}</span>
      <button
        type="button"
        onClick={() => onOpenReport?.(项.报表ID)}
        className="text-xs text-gray-700 truncate flex-1 text-left hover:text-accent transition-colors"
      >
        {项.标题 || '未命名报表'}
      </button>
      <ExternalLink className="w-3 h-3 text-gray-300 shrink-0" />
    </li>
  );
}

/**
 * 可折叠列表：空列表只给兜底文案（此时不渲染 <ul>，否则 <p> 会直接挂在 <ul> 下——非法嵌套），
 * 超长时先只渲染前 折叠条数 条，避免一张宽表把抽屉撑爆。
 */
function 折叠列表({ 项们, 空文案, 键, 折叠, 渲染, 列表类名 = 'divide-y divide-gray-50' }) {
  if (!项们.length) return <p className="text-[11px] text-gray-400">{空文案}</p>;
  const 全展开 = 折叠.展开(键);
  const 可见 = 全展开 ? 项们 : 项们.slice(0, 折叠条数);
  return (
    <>
      <ul className={列表类名}>{可见.map(渲染)}</ul>
      {项们.length > 折叠条数 && (
        <button
          type="button"
          onClick={() => 折叠.切换(键)}
          className="mt-1 text-[11px] text-accent hover:text-accent-deep transition-colors"
        >
          {全展开 ? '收起' : `展开全部 ${项们.length} 条`}
        </button>
      )}
    </>
  );
}

export default function LineageDrawer({ 节点, onClose, onSelectNode, onOpenReport }) {
  // 折叠态：一个抽屉只维护"当前展开哪个列表"这一个键（不给每列表各存一份 state，
  // 否则 hooks 数量会随 节点.类型 变化，违反 Hooks 规则；oxlint 的 rules-of-hooks 又只认
  // `use` 开头的自定义 hook 名，中文 hook 名会被判错，所以状态直接写在组件里）。
  const [展开键, set展开键] = useState('');
  const 折叠 = {
    展开: (键) => 展开键 === 键,
    切换: (键) => set展开键((当前) => (当前 === 键 ? '' : 键)),
  };

  // 换节点 / 关闭（节点变 undefined）时清掉展开态：面板是常驻挂载的，
  // 不清的话下次打开同一节点还停在"展开全部"
  useEffect(() => { set展开键(''); }, [节点?.节点ID]);

  // Esc 关闭：与 components/ShareDialog.jsx 同一套写法（阶段 52 P3 a11y）
  useEffect(() => {
    if (!节点) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [节点, onClose]);

  if (!节点) return null;

  const Icon = 图标[节点.类型] || Table2;
  const 明细 = 节点.明细 || {};      // 明细可能整体缺失（历史节点/手造数据），一律降级
  const 本看板报表 = 明细.本看板报表 || [];
  const 其他报表 = 明细.其他报表 || [];
  const 字段 = 明细.字段 || [];
  const 复用报表 = 明细.报表 || [];
  const 复用数 = 节点.度 ?? 复用报表.length;   // 度就是"被几张报表引用"，缺字段时退回明细里的报表条数

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/20"
      data-testid="血缘抽屉遮罩"
      onClick={() => onClose?.()}
    >
      <aside
        role="dialog"
        aria-label={`节点详情：${节点.名称 || '节点'}`}
        onClick={(e) => e.stopPropagation()}
        className="w-[360px] max-w-[90vw] h-full bg-white shadow-[var(--shadow-card-lg)] flex flex-col"
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <Icon className="w-4 h-4 text-accent shrink-0" />
          <div className="min-w-0">
            <p className="text-[10px] text-gray-400">{副标题[节点.类型] || '节点'}</p>
            <h3 className="text-sm font-medium text-gray-800 truncate">{节点.名称 || '未命名节点'}</h3>
          </div>
          <button
            type="button"
            title="关闭"
            aria-label="关闭抽屉"
            onClick={() => onClose?.()}
            className="ml-auto p-1 rounded hover:bg-gray-100 text-gray-400"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4 space-y-4 text-xs">
          {/* ---- 数据集节点：这份数据有多大、被谁用着、还有谁在用（跨看板反链） ---- */}
          {节点.类型 === '数据集' && (
            <>
              <div className="flex gap-1.5 flex-wrap">
                {明细.行数 != null && <span className="px-2 py-1 rounded-md bg-accent-soft text-accent">{明细.行数} 行</span>}
                {明细.列数 != null && <span className="px-2 py-1 rounded-md bg-gray-100 text-gray-500">{明细.列数} 列</span>}
                {/* listDatasets 不返回 来源数据集ID（后端_核心/存储/sqlite_repo.py:335），拿不到就不渲染徽章 */}
                {明细.来源数据集ID && <span className="px-2 py-1 rounded-md bg-amber-50 text-amber-700">源自清洗/合并</span>}
              </div>

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">本看板引用（{本看板报表.length}）</p>
                <折叠列表
                  项们={本看板报表}
                  空文案="本看板还没有报表引用这份数据"
                  键="本看板报表"
                  折叠={折叠}
                  渲染={(r) => <报表行 key={r.报表ID} 项={r} onOpenReport={onOpenReport} />}
                />
              </section>

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">
                  同数据集的其他报表（{其他报表.length}）
                  <span className="text-gray-400">未加入本看板</span>
                </p>
                <折叠列表
                  项们={其他报表}
                  空文案="没有其他报表复用这份数据"
                  键="其他报表"
                  折叠={折叠}
                  渲染={(r) => <报表行 key={r.报表ID} 项={r} onOpenReport={onOpenReport} />}
                />
              </section>
            </>
          )}

          {/* ---- 报表节点：它长什么样、结论说了啥、由哪份数据来、用到哪些字段 ---- */}
          {节点.类型 === '报表' && (
            <>
              <div className="flex gap-1.5 flex-wrap">
                <span className="px-2 py-1 rounded-md bg-accent-soft text-accent">{明细.图表类型 || '图表'}</span>
                {明细.创建时间 && <span className="px-2 py-1 rounded-md bg-gray-100 text-gray-500">{明细.创建时间}</span>}
              </div>

              {明细.结论 && (
                <p className="text-xs text-gray-600 leading-relaxed bg-gray-50 rounded-lg p-2.5">{明细.结论}</p>
              )}

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">数据来源</p>
                {明细.数据集ID ? (
                  <button
                    type="button"
                    onClick={() => onSelectNode?.(`ds:${明细.数据集ID}`)}
                    className="flex items-center gap-1.5 text-xs text-accent hover:text-accent-deep transition-colors"
                  >
                    <Database className="w-3.5 h-3.5 shrink-0" /> {明细.数据集名 || '未知数据集'}
                  </button>
                ) : (
                  <p className="text-xs text-gray-400">{明细.数据集名 || '未知数据集'}</p>
                )}
              </section>

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">用到的字段（{字段.length}）</p>
                <折叠列表
                  项们={字段}
                  空文案="这张报表没有解析出字段"
                  键="字段"
                  折叠={折叠}
                  列表类名="space-y-1"
                  渲染={(f) => (
                    <li key={f.字段名} className="flex items-center gap-1.5">
                      <span className="text-xs text-gray-700 truncate">{f.字段名}</span>
                      {(f.角色 || []).map((r) => (
                        <span key={r} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 shrink-0">{r}</span>
                      ))}
                    </li>
                  )}
                />
              </section>

              {节点.报表ID && (
                <button
                  type="button"
                  onClick={() => onOpenReport?.(节点.报表ID)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent text-white text-xs hover:bg-accent-deep transition-all"
                >
                  查看完整报表 <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </>
          )}

          {/* ---- 字段节点：这个字段被几张报表复用 ---- */}
          {节点.类型 === '字段' && (
            <>
              <p className="text-xs text-gray-600">
                被 <b className="text-amber-600">{复用数}</b> 张报表复用
                <span className="text-gray-400">（≥2 张即视为高价值字段）</span>
              </p>

              <div className="flex gap-1.5 flex-wrap">
                {(明细.角色 || []).map((r) => (
                  <span key={r} className="px-2 py-1 rounded-md bg-gray-100 text-gray-500">{r}</span>
                ))}
              </div>

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">所属数据集</p>
                {节点.数据集ID ? (
                  <button
                    type="button"
                    onClick={() => onSelectNode?.(`ds:${节点.数据集ID}`)}
                    className="flex items-center gap-1.5 text-xs text-accent hover:text-accent-deep transition-colors"
                  >
                    <Database className="w-3.5 h-3.5 shrink-0" /> {明细.数据集名 || '未知数据集'}
                  </button>
                ) : (
                  <p className="text-xs text-gray-400">{明细.数据集名 || '未知数据集'}</p>
                )}
              </section>

              <section>
                <p className="text-[11px] font-medium text-gray-500 mb-1">复用它的报表（{复用报表.length}）</p>
                <折叠列表
                  项们={复用报表}
                  空文案="没有报表复用这个字段"
                  键="复用报表"
                  折叠={折叠}
                  渲染={(r) => <报表行 key={r.报表ID} 项={r} onOpenReport={onOpenReport} />}
                />
              </section>
            </>
          )}

          {/* 未知类型：至少把节点名摆出来，不留一个纯空白抽屉 */}
          {!图标[节点.类型] && (
            <p className="text-[11px] text-gray-400">该节点暂无更多详情</p>
          )}
        </div>
      </aside>
    </div>
  );
}