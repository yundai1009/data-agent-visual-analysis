const API_BASE_URL = window.__API_BASE_URL__ || 'http://127.0.0.1:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      Authorization: 'Bearer demo-token',
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `请求失败：${response.status}`)
  }
  return response
}

export async function uploadDataset(file) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await request('/datasets/upload', {
    method: 'POST',
    body: formData,
  })
  return response.json()
}

export async function fetchDataset(datasetId) {
  const response = await request(`/datasets/${encodeURIComponent(datasetId)}`)
  return response.json()
}

export async function generateReport(payload) {
  const response = await request('/reports/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return response.json()
}
