import { useState } from 'react'

const API = 'http://127.0.0.1:8000'

export default function PageData() {
  const [uploadState, setUploadState] = useState('empty') // empty | uploading | success | error
  const [uploadFile, setUploadFile] = useState(null)
  const [dataset, setDataset] = useState(null)
  const [showMissing, setShowMissing] = useState(false)
  const [showFieldDetail, setShowFieldDetail] = useState(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('全部')

  const profile = dataset?.数据画像 || {}
  const fields = (profile.字段列表 || []).filter(f => {
    const matchSearch = !search || f.includes(search)
    const t = profile.字段类型?.[f] || ''
    const cat = profile.分类字段?.includes(f) ? '分类'
      : profile.日期字段?.includes(f) ? '日期'
      : profile.数值字段?.includes(f) ? '数值' : '文本'
    const matchType = typeFilter === '全部' || cat === typeFilter
    return matchSearch && matchType
  })

  const quality = profile.数据质量 || {}
  const missingPerField = profile.缺失值 || {}

  function getFieldType(field) {
    if (profile.日期字段?.includes(field)) return { label: '日期', cls: 'badge-date' }
    if (profile.分类字段?.includes(field)) return { label: '分类', cls: 'badge-cat' }
    if (profile.数值字段?.includes(field)) return { label: '数值', cls: 'badge-num' }
    return { label: '文本', cls: 'bg-gray-100 text-gray-500' }
  }

  // 模拟上传
  function handleUpload() {
    setUploadState('uploading')
    let p = 0
    const t = setInterval(() => {
      p += Math.floor(Math.random() * 12) + 6
      if (p >= 100) {
        p = 100
        clearInterval(t)
        setTimeout(() => {
          setUploadState('success')
          setUploadFile({ name: '销售数据.csv', rows: 2847 })
          setDataset({
            数据集ID: 'demo',
            数据画像: {
              行数: 2847, 列数: 12,
              字段列表: ['月份', '地区', '销售额', '订单数', '工作经验要求', '岗位类型', '招聘人数', '学历要求', '薪资范围', '公司规模', '行业领域', '发布时间'],
              字段类型: { '月份': 'datetime64', '地区': 'object', '销售额': 'int64', '订单数': 'int64', '工作经验要求': 'object', '岗位类型': 'object' },
              数值字段: ['销售额', '订单数', '招聘人数'],
              日期字段: ['月份', '发布时间'],
              分类字段: ['地区', '工作经验要求', '岗位类型', '学历要求', '公司规模', '行业领域'],
              缺失值: { '销售额': 4, '订单数': 2 },
              总缺失值: 6,
              数据质量: { 评级: 'A', 等级: '优秀', 缺失率: 0.02, 提示: ['存在 2 行完全重复记录'], 重复行数: 2, 缺失字段: ['销售额（0.14%）', '订单数（0.07%）'] },
              字段建议: [{ 字段: '月份', 角色: 'X轴', 理由: '日期字段适合观察趋势变化' }],
            },
          })
        }, 300)
      }
    }, 150)
  }

  function loadExample() {
    setUploadState('uploading')
    setTimeout(() => {
      setUploadState('success')
      setUploadFile({ name: '示例数据_销售数据.csv', rows: 30 })
      setDataset({
        数据集ID: 'example',
        数据画像: {
          行数: 30, 列数: 6,
          字段列表: ['月份', '地区', '销售额', '订单数', '工作经验要求', '岗位类型'],
          字段类型: { '月份': 'datetime64', '地区': 'object', '销售额': 'int64', '订单数': 'int64', '工作经验要求': 'object', '岗位类型': 'object' },
          数值字段: ['销售额', '订单数'],
          日期字段: ['月份'],
          分类字段: ['地区', '工作经验要求', '岗位类型'],
          缺失值: { '销售额': 0, '订单数': 0 },
          总缺失值: 0,
          数据质量: { 评级: 'A', 等级: '优秀', 缺失率: 0, 提示: [], 重复行数: 0, 缺失字段: [] },
          字段建议: [{ 字段: '月份', 角色: 'X轴', 理由: '日期字段适合观察趋势变化' }],
        },
      })
    }, 500)
  }

  function resetUpload() {
    setUploadState('empty')
    setUploadFile(null)
    setDataset(null)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* 页面头部 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-gray-600">数据管理</h1>
          <p className="text-xs text-gray-400 mt-1">支持 CSV / Excel 上传，自动识别字段类型与数据质量</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadExample}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 transition-all cursor-pointer flex items-center gap-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3" /></svg>
            导入示例数据
          </button>
          <span className="flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-2 py-1 rounded border border-emerald-200">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />系统正常
          </span>
        </div>
      </div>

      {/* 上传区 */}
      {uploadState === 'empty' && (
        <div className="upload-zone" onClick={handleUpload}>
          <svg className="w-10 h-10 mx-auto text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className="text-sm text-gray-500 mb-1">点击上传或拖拽文件到此处</p>
          <p className="text-xs text-gray-400">支持 .csv / .xlsx / .xls 格式，单文件不超过 50MB</p>
        </div>
      )}

      {uploadState === 'uploading' && (
        <div className="border border-dashed border-accent rounded-xl p-6 text-center bg-accent-light/30">
          <div className="flex items-center justify-center gap-2 mb-3">
            <svg className="w-5 h-5 text-accent animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
            <span className="text-sm text-gray-500">正在解析文件结构，请稍候...</span>
          </div>
          <div className="max-w-xs mx-auto h-1.5 rounded-full bg-gray-200 overflow-hidden">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: '60%' }} />
          </div>
        </div>
      )}

      {uploadState === 'success' && uploadFile && (
        <div className="upload-zone success">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
              <span className="text-sm text-gray-600">已加载数据集：{uploadFile.name}（{uploadFile.rows.toLocaleString()} 行）</span>
            </div>
            <div className="flex gap-2">
              <button onClick={resetUpload} className="text-xs px-2 py-1 rounded border border-gray-200 text-gray-400 hover:bg-gray-100 cursor-pointer">重新上传</button>
              <button className="text-xs px-2 py-1 text-accent hover:bg-accent-light/30 rounded cursor-pointer">查看详情</button>
            </div>
          </div>
        </div>
      )}

      {/* 数据概览 */}
      {dataset && (
        <>
          <div className="grid grid-cols-4 gap-3 mt-5">
            <div className="card p-3.5 flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5"><svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg><span className="text-xs text-gray-400">总行数</span></div>
              <p className="text-xl font-medium text-gray-600">{profile.行数?.toLocaleString()}</p>
              <p className="text-xs text-gray-400">数据量正常，可流畅分析</p>
            </div>

            <div className="card p-3.5 flex flex-col gap-1.5 cursor-pointer" onClick={() => alert(`字段分布：\n日期 ${(profile.日期字段||[]).length} 个\n分类 ${(profile.分类字段||[]).length} 个\n数值 ${(profile.数值字段||[]).length} 个`)}>
              <div className="flex items-center gap-1.5"><svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg><span className="text-xs text-gray-400">字段数</span></div>
              <p className="text-xl font-medium text-gray-600">{profile.列数}</p>
              <p className="text-xs text-gray-400">日期 {(profile.日期字段||[]).length} / 分类 {(profile.分类字段||[]).length} / 数值 {(profile.数值字段||[]).length}</p>
            </div>

            <div className="card p-3.5 flex flex-col gap-1.5 relative overflow-hidden">
              <div className="absolute -top-4 -right-4 w-14 h-14 bg-gradient-to-br from-emerald-100 to-transparent opacity-60 rounded-full" />
              <div className="flex items-center gap-1.5"><svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg><span className="text-xs text-gray-400">数据质量评级</span></div>
              <div className="flex items-baseline gap-1.5">
                <p className={`text-xl font-semibold ${quality.评级 === 'A' ? 'text-emerald-600' : quality.评级 === 'B' ? 'text-amber-600' : 'text-red-500'}`}>{quality.评级 || '-'}</p>
                <span className="text-xs text-gray-400 cursor-help" title="A级：缺失率&lt;5%&#10;B级：缺失率5%~20%&#10;C级：缺失率&gt;20%">ⓘ</span>
              </div>
              <p className="text-xs text-gray-400">缺失率 {quality.缺失率 ?? 0}% · {quality.等级 || '未知'}</p>
            </div>

            <div
              className="card p-3.5 flex flex-col gap-1.5 cursor-pointer relative"
              style={{ borderLeft: '3px solid #F77234' }}
              onClick={() => setShowMissing(true)}
            >
              <div className="flex items-center gap-1.5"><svg className="w-3.5 h-3.5 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" /></svg><span className="text-xs text-gray-400">缺失值数量</span></div>
              <p className="text-xl font-medium text-orange-500">{profile.总缺失值 ?? 0}</p>
              <p className="text-xs text-orange-500">共 {Object.values(missingPerField).filter(v => v > 0).length} 个字段存在缺失</p>
            </div>
          </div>

          {/* 字段列表 */}
          <div className="card mt-5 overflow-hidden">
            <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-600 shrink-0">字段列表</span>
              <input
                className="flex-1 max-w-[180px] text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-accent/50 transition-colors"
                placeholder="搜索字段名..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              <select
                className="text-xs px-2 py-1.5 rounded-lg border border-gray-200 bg-gray-50 outline-none"
                value={typeFilter}
                onChange={e => setTypeFilter(e.target.value)}
              >
                <option>全部</option><option>日期</option><option>分类</option><option>数值</option>
              </select>
              <span className="text-xs text-gray-400 shrink-0">共 {fields.length} 个字段</span>
            </div>
            <div>
              {fields.map(f => {
                const ft = getFieldType(f)
                return (
                  <div
                    key={f}
                    className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors group"
                    onClick={() => setShowFieldDetail(f)}
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className="text-sm text-gray-600 truncate">{f}</span>
                      <span className={`badge ${ft.cls}`}>{ft.label}</span>
                    </div>
                    <div className="text-xs text-gray-400 flex-1 hidden sm:block">
                      {ft.label === '日期' && '时间维度，适合趋势分析'}
                      {ft.label === '分类' && '适合分组对比与占比分析'}
                      {ft.label === '数值' && '核心指标，适合聚合统计'}
                      {ft.label === '文本' && '文本信息，适合标签展示'}
                    </div>
                    <div className="flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button className="text-xs text-accent hover:bg-accent-light/30 px-1.5 py-0.5 rounded cursor-pointer" onClick={e => { e.stopPropagation(); setShowFieldDetail(f) }}>预览</button>
                      <button className="text-xs text-accent hover:bg-accent-light/30 px-1.5 py-0.5 rounded cursor-pointer">加入分析</button>
                    </div>
                  </div>
                )
              })}
              {fields.length === 0 && <p className="text-center text-xs text-gray-400 py-6">无匹配字段</p>}
            </div>
          </div>

          {/* 快捷操作 */}
          <div className="grid grid-cols-3 gap-3 mt-5">
            <div className="card p-3.5 flex items-center gap-3 cursor-pointer hover:bg-gray-50">
              <div className="w-9 h-9 rounded-lg bg-accent-light/30 flex items-center justify-center text-base">📊</div>
              <div><p className="text-sm font-medium text-gray-600">基于此数据集新建分析</p><p className="text-xs text-gray-400 mt-0.5">自动带入当前数据集上下文</p></div>
            </div>
            <div className="card p-3.5 flex items-center gap-3 cursor-pointer hover:bg-gray-50">
              <div className="w-9 h-9 rounded-lg bg-orange-50 flex items-center justify-center text-base">🧹</div>
              <div><p className="text-sm font-medium text-gray-600">一键基础清洗</p><p className="text-xs text-gray-400 mt-0.5">去重 / 填充缺失 / 删除空行</p></div>
            </div>
            <div className="card p-3.5 flex items-center gap-3 cursor-pointer hover:bg-gray-50">
              <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center text-base">📋</div>
              <div><p className="text-sm font-medium text-gray-600">生成数据质量报告</p><p className="text-xs text-gray-400 mt-0.5">详细的数据完整性分析</p></div>
            </div>
          </div>
        </>
      )}

      {/* 缺失值弹窗 */}
      {showMissing && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={e => { if (e.target === e.currentTarget) setShowMissing(false) }}>
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-3 overflow-hidden" style={{ animation: 'fadeIn .2s ease' }}>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-600">缺失值详情</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none cursor-pointer" onClick={() => setShowMissing(false)}>✕</button>
            </div>
            <div className="p-5">
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-gray-400 border-b border-gray-100"><th className="text-left py-2 font-medium">字段名</th><th className="text-left py-2 font-medium">缺失数量</th><th className="text-left py-2 font-medium">缺失占比</th></tr></thead>
                <tbody>
                  {Object.entries(missingPerField).filter(([, v]) => v > 0).map(([field, count]) => (
                    <tr key={field}><td className="py-2 text-gray-600">{field}</td><td className="py-2">{count}</td><td className="py-2 text-orange-500">{((count / profile.行数) * 100).toFixed(2)}%</td></tr>
                  ))}
                </tbody>
              </table>
              <div className="flex gap-3 mt-4">
                <button className="text-xs px-4 py-2 rounded-lg bg-gray-600 text-white hover:bg-gray-700 cursor-pointer" onClick={() => setShowMissing(false)}>分析时自动忽略缺失行</button>
                <button className="text-xs px-4 py-2 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 cursor-pointer" onClick={() => setShowMissing(false)}>先进行数据清洗</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 字段详情弹窗 */}
      {showFieldDetail && (
        <div className="fixed inset-0 bg-black/20 z-50 flex items-center justify-center" onClick={e => { if (e.target === e.currentTarget) setShowFieldDetail(null) }}>
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-3 overflow-hidden" style={{ animation: 'fadeIn .2s ease' }}>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-600">字段详情：{showFieldDetail}</span>
              <button className="text-gray-400 hover:text-gray-600 text-lg leading-none cursor-pointer" onClick={() => setShowFieldDetail(null)}>✕</button>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">字段类型</p><p className="text-sm mt-1">{getFieldType(showFieldDetail).label}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">缺失值</p><p className="text-sm mt-1">{missingPerField[showFieldDetail] || 0}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">唯一值</p><p className="text-sm mt-1">{profile.行数 || '-'}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-400">数据类型</p><p className="text-sm mt-1 font-mono text-xs">{profile.字段类型?.[showFieldDetail] || '-'}</p></div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
