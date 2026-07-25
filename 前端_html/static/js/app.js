import { uploadDataset, fetchDataset, generateReport } from './api.js'

const fileInput = document.getElementById('file-input')
const uploadBtn = document.getElementById('upload-btn')
const applyRecommendationBtn = document.getElementById('apply-recommendation-btn')
const generateBtn = document.getElementById('generate-btn')
const refreshBtn = document.getElementById('refresh-btn')
const datasetSummary = document.getElementById('dataset-summary')
const fieldAdvice = document.getElementById('field-advice')
const qualityWarnings = document.getElementById('quality-warnings')
const datasetPreview = document.getElementById('dataset-preview')
const analysisInput = document.getElementById('analysis-input')
const xAxis = document.getElementById('x-axis')
const yAxis = document.getElementById('y-axis')
const groupField = document.getElementById('group-field')
const aggMethod = document.getElementById('agg-method')
const templateButtons = document.getElementById('template-buttons')
const chartCards = document.getElementById('chart-cards')
const resultMeta = document.getElementById('result-meta')
const recommendationBox = document.getElementById('recommendation-box')
const riskBox = document.getElementById('risk-box')
const agentTrace = document.getElementById('agent-trace')
const exportHtmlBtn = document.getElementById('export-html-btn')
const exportJsonBtn = document.getElementById('export-json-btn')
const chartBox = document.getElementById('chart-box')
const tabButtons = Array.from(document.querySelectorAll('.tab-btn'))
const tabTable = document.getElementById('tab-table')
const tabConclusion = document.getElementById('tab-conclusion')
const tabRaw = document.getElementById('tab-raw')
const configHint = document.getElementById('config-hint')
const validationHint = document.getElementById('validation-hint')

const chartOptions = [
  ['自动推荐', '系统智能判断最适合的图表'],
  ['柱状图', '分类对比'],
  ['折线图', '趋势变化'],
  ['饼图', '占比分析'],
  ['散点图', '相关性观察'],
  ['直方图', '数值分布'],
  ['热力图', '交叉分布'],
  ['堆积柱状图', '分组构成'],
  ['面积图', '累计趋势'],
  ['雷达图', '多指标对比'],
  ['表格', '明细查看'],
]
const controlledTemplates = [
  '按【字段】统计数量',
  '按【字段】统计占比',
  '按【时间字段】查看【指标】趋势',
  '查看【字段A】和【字段B】的交叉分布',
  '查看【数值字段】的分布情况',
  '比较【字段】下【指标】差异',
  '按【字段】和【分组字段】生成堆积图',
  '按【时间字段】查看【指标】面积图',
  '按【字段】比较多个指标雷达图',
]
const aggOptions = ['求和', '平均值', '计数', '最大值', '最小值']
const countMetric = '记录数'
const shareIntentKeywords = ['占比', '比例', '分布', '构成']
const fieldIntentKeywords = ['工作经验', '经验', '地区', '国家', '城市', '地点', '岗位', '职位', '分类', '类型', '行业', '部门', '公司']

let currentDatasetId = null
let currentProfile = null
let currentReport = null
let currentChartType = '自动推荐'
let chartInstance = null

function renderTable(rows, mountPoint) {
  if (!rows || !rows.length) {
    mountPoint.innerHTML = '<div class="empty">暂无数据</div>'
    return
  }
  const headers = Object.keys(rows[0])
  const thead = `<tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
  const tbody = rows.map((row) => `<tr>${headers.map((h) => `<td>${escapeHtml(String(row[h] ?? ''))}</td>`).join('')}</tr>`).join('')
  mountPoint.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`
}

function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderList(items, emptyText = '暂无') {
  if (!items || !items.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
}

function getAdvice(role) {
  return (currentProfile?.字段建议 || []).find((item) => item.角色 === role)
}

function hasShareIntent() {
  const text = analysisInput.value || ''
  return shareIntentKeywords.some((keyword) => text.includes(keyword))
}

function findIntentField() {
  const fields = currentProfile?.字段列表 || []
  const categorical = currentProfile?.分类字段 || []
  for (const keyword of fieldIntentKeywords) {
    const hit = [...fields, ...categorical].find((field) => field.includes(keyword))
    if (hit) return hit
  }
  return categorical[0] || fields[0] || ''
}

function setMultiSelectValue(selectEl, values) {
  const valueSet = new Set(values.filter(Boolean))
  Array.from(selectEl.options).forEach((option) => {
    option.selected = valueSet.has(option.value)
  })
}

function applyRecommendedConfig() {
  if (!currentProfile) return
  const text = analysisInput.value || ''
  const templateFields = Array.from(text.matchAll(/【([^】]+)】/g)).map((match) => match[1])
  const firstField = templateFields[0]
  const secondField = templateFields[1]

  if (text.includes('交叉分布') || text.includes('热力图') || text.includes('矩阵')) {
    if (firstField) xAxis.value = firstField
    if (secondField) groupField.value = secondField
    setMultiSelectValue(yAxis, [countMetric])
    aggMethod.value = '计数'
    currentChartType = '热力图'
  } else if (text.includes('直方图') || text.includes('分布情况') || text.includes('数值分布')) {
    if (firstField) xAxis.value = firstField
    setMultiSelectValue(yAxis, [firstField || countMetric])
    aggMethod.value = '计数'
    currentChartType = '直方图'
  } else if (hasShareIntent()) {
    const intentField = firstField || findIntentField()
    if (intentField) xAxis.value = intentField
    setMultiSelectValue(yAxis, [countMetric])
    groupField.value = '无'
    aggMethod.value = '计数'
    currentChartType = '饼图'
  } else if (text.includes('堆积')) {
    if (firstField) xAxis.value = firstField
    if (secondField) groupField.value = secondField
    setMultiSelectValue(yAxis, [templateFields[2] || countMetric])
    aggMethod.value = templateFields[2] ? '求和' : '计数'
    currentChartType = '堆积柱状图'
  } else if (text.includes('面积图')) {
    if (firstField) xAxis.value = firstField
    setMultiSelectValue(yAxis, [secondField || countMetric])
    aggMethod.value = secondField ? '求和' : '计数'
    currentChartType = '面积图'
  } else if (text.includes('雷达')) {
    if (firstField) xAxis.value = firstField
    setMultiSelectValue(yAxis, currentProfile.数值字段?.slice(0, 5) || [])
    aggMethod.value = '平均值'
    currentChartType = '雷达图'
  } else if (text.includes('趋势') || text.includes('变化')) {
    if (firstField) xAxis.value = firstField
    setMultiSelectValue(yAxis, [secondField || countMetric])
    aggMethod.value = secondField ? '求和' : '计数'
    currentChartType = '折线图'
  } else if (text.includes('统计') && text.includes('数量')) {
    if (firstField) xAxis.value = firstField
    setMultiSelectValue(yAxis, [countMetric])
    aggMethod.value = '计数'
    currentChartType = '柱状图'
  } else {
    const xAdvice = getAdvice('X轴')
    const yAdvice = getAdvice('Y轴')
    const groupAdvice = getAdvice('分组')
    if (xAdvice?.字段) xAxis.value = xAdvice.字段
    if (yAdvice?.字段) setMultiSelectValue(yAxis, [yAdvice.字段])
    if (groupAdvice?.字段 && Array.from(groupField.options).some((option) => option.value === groupAdvice.字段)) {
      groupField.value = groupAdvice.字段
    }
    aggMethod.value = '求和'
    currentChartType = currentProfile.日期字段?.includes(xAxis.value) ? '折线图' : '自动推荐'
  }
  renderChartCards()
  validateConfig()
}

function validateConfig() {
  if (!currentDatasetId) {
    validationHint.className = 'validation-hint empty'
    validationHint.textContent = '上传文件后开始校验配置'
    return false
  }
  const selectedY = getSelectedValues(yAxis)
  const messages = []
  if (currentChartType !== '表格' && !xAxis.value) messages.push('缺少 X 轴字段')
  if (!['表格', '饼图'].includes(currentChartType) && !selectedY.length) messages.push('缺少 Y 轴指标字段')
  if (currentChartType === '散点图' && selectedY.length < 2) messages.push('散点图建议选择至少两个数值字段')
  if (currentChartType === '饼图' && selectedY.length > 1) messages.push('饼图只会使用第一个 Y 轴字段')
  if (hasShareIntent() && currentChartType !== '饼图') messages.push('占比/分布类需求建议使用饼图')
  if (hasShareIntent() && selectedY[0] !== countMetric) messages.push('占比/分布类需求建议使用记录数计数，避免对 ID 求和')
  validationHint.className = `validation-hint ${messages.length ? 'warning' : 'ok'}`
  validationHint.textContent = messages.length ? messages.join('；') : '当前配置可以生成报表'
  return messages.length === 0
}

function renderAgentTrace(report) {
  const trace = report['Agent Trace'] || report.Agent_Trace || []
  agentTrace.innerHTML = trace.length
    ? trace.map((step, index) => `
      <div class="trace-step">
        <span class="trace-index">${index + 1}</span>
        <div>
          <strong>${escapeHtml(step.步骤 || '')}</strong>
          <em>${escapeHtml(step.状态 || '')}</em>
          <p>${escapeHtml(step.说明 || '')}</p>
        </div>
      </div>
    `).join('')
    : '<div class="empty">暂无 Agent Trace</div>'
}

function downloadText(filename, content, type = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function renderDatasetSummary(profile, fileName = '') {
  const lines = [
    fileName ? `<div><strong>文件名</strong>：${escapeHtml(fileName)}</div>` : '',
    `<div><strong>行数</strong>：${profile.行数}</div>`,
    `<div><strong>列数</strong>：${profile.列数}</div>`,
    `<div><strong>缺失值</strong>：${profile.总缺失值}</div>`,
    `<div><strong>数值字段</strong>：${profile.数值字段?.join('、') || '无'}</div>`,
    `<div><strong>日期字段</strong>：${profile.日期字段?.join('、') || '无'}</div>`,
    `<div><strong>分类字段</strong>：${profile.分类字段?.join('、') || '无'}</div>`,
    `<div><strong>文本字段</strong>：${profile.文本字段?.join('、') || '无'}</div>`,
  ]
  datasetSummary.innerHTML = lines.join('')

  const advice = profile.字段建议 || []
  fieldAdvice.innerHTML = advice.length
    ? advice.map((item) => `
      <div class="advice-card">
        <strong>${escapeHtml(item.角色 || '建议')}</strong>
        <span>${escapeHtml(item.字段 || '')}</span>
        <p>${escapeHtml(item.理由 || '')}</p>
      </div>
    `).join('')
    : '<div class="empty">暂无字段建议</div>'

  const quality = profile.数据质量 || {}
  qualityWarnings.innerHTML = `
    <div><strong>数据质量</strong>：${escapeHtml(quality.等级 || '未知')}</div>
    ${renderList(quality.提示 || [], '未发现明显数据质量风险')}
  `
}

function populateSelect(selectEl, items, includeEmpty = false) {
  const opts = []
  if (includeEmpty) opts.push('<option value="">无</option>')
  opts.push(...items.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`))
  selectEl.innerHTML = opts.join('')
}

function populateMultiSelect(selectEl, items) {
  const uniqueItems = Array.from(new Set([countMetric, ...items]))
  selectEl.innerHTML = uniqueItems.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('')
}

function renderChartCards() {
  chartCards.innerHTML = chartOptions.map(([name, hint]) => `
    <div class="chart-card ${name === currentChartType ? 'active' : ''}" data-value="${name}">
      <strong>${name}</strong>
      <span>${hint}</span>
    </div>
  `).join('')
  chartCards.querySelectorAll('.chart-card').forEach((card) => {
    card.addEventListener('click', () => {
      currentChartType = card.dataset.value
      renderChartCards()
      validateConfig()
    })
  })
}

function pickTemplateField(kind) {
  if (!currentProfile) return kind
  if (kind.includes('时间')) return currentProfile.日期字段?.[0] || currentProfile.分类字段?.[0] || currentProfile.字段列表?.[0] || kind
  if (kind.includes('指标') || kind.includes('数值')) return currentProfile.数值字段?.[0] || countMetric
  if (kind.includes('字段B') || kind.includes('分组')) return currentProfile.分类字段?.[1] || currentProfile.分类字段?.[0] || currentProfile.字段列表?.[1] || kind
  return currentProfile.分类字段?.[0] || currentProfile.字段列表?.[0] || kind
}

function materializeTemplate(template) {
  return template
    .replace('【时间字段】', `【${pickTemplateField('时间字段')}】`)
    .replace('【数值字段】', `【${pickTemplateField('数值字段')}】`)
    .replace('【字段A】', `【${pickTemplateField('字段')}】`)
    .replace('【字段B】', `【${pickTemplateField('字段B')}】`)
    .replace('【分组字段】', `【${pickTemplateField('分组字段')}】`)
    .replace('【指标】', `【${pickTemplateField('指标')}】`)
    .replace('【字段】', `【${pickTemplateField('字段')}】`)
}

function renderTemplates() {
  if (!templateButtons) return
  templateButtons.innerHTML = controlledTemplates.map((template) => {
    const text = materializeTemplate(template)
    return `<button type="button" class="template-btn" data-template="${escapeHtml(text)}">${escapeHtml(text)}</button>`
  }).join('')
  templateButtons.querySelectorAll('.template-btn').forEach((button) => {
    button.addEventListener('click', () => {
      analysisInput.value = button.dataset.template
      applyRecommendedConfig()
      validateConfig()
    })
  })
}

function updateConfigFromProfile(profile) {
  const fields = profile.字段列表 || []
  populateSelect(xAxis, fields, true)
  populateMultiSelect(yAxis, profile.数值字段 || [])
  populateSelect(groupField, ['无', ...fields], false)
  populateSelect(aggMethod, aggOptions, false)
  xAxis.value = profile.日期字段?.[0] || profile.分类字段?.[0] || fields[0] || ''
  if (profile.数值字段?.length) {
    Array.from(yAxis.options).forEach((option) => {
      option.selected = profile.数值字段.includes(option.value)
    })
  }
  groupField.value = '无'
  aggMethod.value = '求和'
  validateConfig()
}

function getSelectedValues(selectEl) {
  return Array.from(selectEl.selectedOptions).map((option) => option.value).filter(Boolean)
}

function renderChart(report) {
  if (!window.echarts) return
  const dom = chartBox
  chartInstance = chartInstance || window.echarts.init(dom)
  const rows = report.报表数据 || []
  const xKey = report.图表配置?.X轴 || Object.keys(rows[0] || {})[0]
  const yKeys = report.图表配置?.Y轴 || []
  const xData = rows.map((row) => row[xKey])
  const chartType = report.图表配置?.类型 || 'bar'
  const series = yKeys.length
    ? yKeys.map((key) => ({ name: key, type: chartType === 'scatter' ? 'scatter' : chartType === 'pie' ? 'pie' : chartType === 'line' ? 'line' : 'bar', data: rows.map((row) => row[key]) }))
    : [{ name: '数据', type: 'bar', data: rows.map((row) => row[xKey]) }]

  const option = {
    title: { text: report.标题 || '报表结果' },
    tooltip: { trigger: chartType === 'pie' ? 'item' : 'axis' },
    legend: { top: 24 },
    xAxis: chartType === 'pie' || chartType === 'radar' ? undefined : { type: 'category', data: xData },
    yAxis: chartType === 'pie' || chartType === 'radar' ? undefined : { type: 'value' },
    series,
  }

  if (chartType === 'pie' && rows.length) {
    option.series = [{
      type: 'pie',
      radius: '62%',
      data: rows.map((row) => ({ name: row[xKey], value: row[yKeys[0]] })),
    }]
  } else if (chartType === 'histogram') {
    option.xAxis = { type: 'category', data: xData, axisLabel: { rotate: 25 } }
    option.yAxis = { type: 'value' }
    option.series = [{ name: '记录数', type: 'bar', data: rows.map((row) => row[yKeys[0]] ?? row.记录数 ?? 0) }]
  } else if (chartType === 'heatmap') {
    const yKey = report.图表配置?.颜色 || Object.keys(rows[0] || {}).find((key) => key !== xKey && key !== yKeys[0])
    const valueKey = yKeys[0] || '记录数'
    const xs = Array.from(new Set(rows.map((row) => row[xKey])))
    const ys = Array.from(new Set(rows.map((row) => row[yKey])))
    option.tooltip = { position: 'top' }
    option.xAxis = { type: 'category', data: xs }
    option.yAxis = { type: 'category', data: ys }
    option.visualMap = { min: 0, max: Math.max(...rows.map((row) => Number(row[valueKey] || 0)), 1), calculable: true, orient: 'horizontal', left: 'center', bottom: 8 }
    option.series = [{ type: 'heatmap', data: rows.map((row) => [xs.indexOf(row[xKey]), ys.indexOf(row[yKey]), row[valueKey] || 0]) }]
  } else if (chartType === 'stacked_bar') {
    const groupKey = report.图表配置?.颜色
    const valueKey = yKeys[0] || '记录数'
    const groups = Array.from(new Set(rows.map((row) => row[groupKey] || '默认')))
    option.series = groups.map((group) => ({
      name: group,
      type: 'bar',
      stack: 'total',
      data: xData.map((x) => rows.find((row) => row[xKey] === x && (row[groupKey] || '默认') === group)?.[valueKey] || 0),
    }))
  } else if (chartType === 'area') {
    option.series = yKeys.map((key) => ({ name: key, type: 'line', areaStyle: {}, data: rows.map((row) => row[key]) }))
  } else if (chartType === 'radar') {
    const indicators = yKeys.map((key) => ({ name: key, max: Math.max(...rows.map((row) => Number(row[key] || 0)), 1) }))
    option.radar = { indicator: indicators }
    option.series = [{ type: 'radar', data: rows.slice(0, 8).map((row) => ({ name: row[xKey], value: yKeys.map((key) => row[key] || 0) })) }]
  }

  chartInstance.setOption(option, true)
}

function setActiveTab(tabName) {
  tabButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === tabName))
  tabTable.classList.toggle('hidden', tabName !== 'table')
  tabConclusion.classList.toggle('hidden', tabName !== 'conclusion')
  tabRaw.classList.toggle('hidden', tabName !== 'raw')
}

tabButtons.forEach((button) => button.addEventListener('click', () => setActiveTab(button.dataset.tab)))

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files?.[0]
  if (!file) {
    alert('请先选择 CSV 或 Excel 文件')
    return
  }
  uploadBtn.disabled = true
  uploadBtn.textContent = '上传中...'
  try {
    const dataset = await uploadDataset(file)
    currentDatasetId = dataset.数据集ID
    currentProfile = dataset.数据画像
    renderDatasetSummary(currentProfile, dataset.文件名)
    updateConfigFromProfile(currentProfile)
    renderChartCards()
    renderTemplates()
    applyRecommendedConfig()
    configHint.textContent = `数据集 ${dataset.数据集ID} 已就绪，已应用推荐字段，可直接生成报表。`
    const preview = await fetchDataset(dataset.数据集ID)
    renderTable(preview.预览数据, datasetPreview)
  } catch (error) {
    alert(error.message || String(error))
  } finally {
    uploadBtn.disabled = false
    uploadBtn.textContent = '上传并解析'
  }
})

generateBtn.addEventListener('click', async () => {
  if (!currentDatasetId) {
    alert('请先上传文件')
    return
  }
  const payload = {
    数据集ID: currentDatasetId,
    分析需求: analysisInput.value || '',
    图表类型: currentChartType,
    x轴: xAxis.value || null,
    y轴: getSelectedValues(yAxis),
    分组字段: groupField.value === '无' ? null : groupField.value,
    聚合方式: aggMethod.value,
  }
  generateBtn.disabled = true
  generateBtn.textContent = '生成中...'
  try {
    currentReport = await generateReport(payload)
    const 意图来源 = currentReport.意图来源 || '无'
    const 意图徽章颜色 = 意图来源 === 'LLM' ? '#2563eb' : (意图来源 === '规则' ? '#16a34a' : '#94a3b8')
    resultMeta.innerHTML = `
      <div><strong>报表ID</strong>：${escapeHtml(currentReport.报表ID)}</div>
      <div><strong>图表类型</strong>：${escapeHtml(currentReport.图表类型)}</div>
      <div><strong>标题</strong>：${escapeHtml(currentReport.标题)}</div>
      <div><strong>意图来源</strong>：<span class="intent-badge" style="display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;color:#fff;background:${意图徽章颜色};">${escapeHtml(意图来源)}</span>
        <span style="margin-left:8px;color:#64748b;font-size:12px;">${意图来源 === 'LLM' ? '由 LLM Function Calling 生成' : 意图来源 === '规则' ? '关键词兑底命中' : '未触发意图识别'}</span>
      </div>
    `
    const recommendation = currentReport.推荐说明 || {}
    recommendationBox.innerHTML = `
      <h3>推荐依据</h3>
      ${renderList(recommendation.理由 || [], '暂无推荐依据')}
      <div class="recommend-fields">
        <span>X轴：${escapeHtml(recommendation.推荐字段?.X轴 || '无')}</span>
        <span>Y轴：${escapeHtml((recommendation.推荐字段?.Y轴 || []).join('、') || '无')}</span>
        <span>分组：${escapeHtml(recommendation.推荐字段?.分组字段 || '无')}</span>
        <span>聚合：${escapeHtml(recommendation.推荐字段?.聚合方式 || '无')}</span>
      </div>
    `
    riskBox.innerHTML = `
      <h3>注意事项</h3>
      ${renderList(currentReport.风险提示 || currentReport.数据画像?.数据质量?.提示 || [], '未发现明显风险')}
    `
    renderAgentTrace(currentReport)
    exportHtmlBtn.disabled = !currentReport.导出数据?.HTML
    exportJsonBtn.disabled = false
    renderChart(currentReport)
    renderTable(currentReport.报表数据 || [], tabTable)
    tabConclusion.innerHTML = `<div class="summary">${escapeHtml(currentReport.结论).replaceAll('\n', '<br/>')}</div>`
    tabRaw.innerHTML = `<pre class="summary">${escapeHtml(JSON.stringify(currentReport, null, 2))}</pre>`
    setActiveTab('conclusion')
  } catch (error) {
    alert(error.message || String(error))
  } finally {
    generateBtn.disabled = false
    generateBtn.textContent = '生成报表'
  }
})

refreshBtn.addEventListener('click', () => generateBtn.click())
applyRecommendationBtn.addEventListener('click', applyRecommendedConfig)
exportHtmlBtn.addEventListener('click', () => {
  if (!currentReport?.导出数据?.HTML) return
  downloadText(currentReport.导出数据.推荐文件名 || 'analysis-report.html', currentReport.导出数据.HTML, 'text/html;charset=utf-8')
})
exportJsonBtn.addEventListener('click', () => {
  if (!currentReport) return
  downloadText('analysis-report.json', JSON.stringify(currentReport, null, 2), 'application/json;charset=utf-8')
})
;[analysisInput, xAxis, yAxis, groupField, aggMethod].forEach((el) => {
  el.addEventListener('change', validateConfig)
  el.addEventListener('input', validateConfig)
})
analysisInput.addEventListener('input', () => {
  if (currentProfile && hasShareIntent()) applyRecommendedConfig()
})

renderChartCards()
renderTemplates()
aggMethod.innerHTML = aggOptions.map((item) => `<option value="${item}">${item}</option>`).join('')
setActiveTab('table')
validateConfig()
