import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1', timeout: 20000 })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export async function devLogin() {
  const { data } = await api.post('/auth/dev-login')
  localStorage.setItem('token', data.access_token)
  localStorage.setItem('user', JSON.stringify(data.user))
  return data.user
}

export async function feishuAuthorizeUrl() {
  const { data } = await api.get('/auth/feishu/authorize')
  return data.authorize_url
}

export async function listScenarios() {
  const { data } = await api.get('/scenarios')
  return data
}

export async function getGrid(scenarioId, versionNo) {
  const { data } = await api.get(
    `/scenarios/${scenarioId}/grid${versionNo ? `?version_no=${versionNo}` : ''}`
  )
  return data
}

// 网格是行主序 {row_key: {period: {...}}}，月份是内层 key 的并集（部分行稀疏，如年度目标只有 12 月）
export function gridPeriods(grid) {
  if (!grid?.cells) return []
  const set = new Set()
  for (const row of Object.values(grid.cells)) for (const p in row) set.add(p)
  return [...set].sort()
}

export async function getVersions(scenarioId) {
  const { data } = await api.get(`/scenarios/${scenarioId}/versions`)
  return data
}

export async function putCells(scenarioId, cells) {
  const { data } = await api.put(`/scenarios/${scenarioId}/cells`, { cells })
  return data
}

export async function recalc(scenarioId, payload = {}) {
  const { data } = await api.post(`/scenarios/${scenarioId}/recalc`, payload)
  return data
}

// 非持久化预览：{params?, inputs?} → {scenario_id, cells}（不建版本，预算页边改边预览用）
export async function previewRecalc(scenarioId, payload = {}) {
  const { data } = await api.post(`/scenarios/${scenarioId}/recalc/preview`, payload)
  return data
}

export async function releaseVersion(scenarioId, versionNo) {
  const { data } = await api.post(`/scenarios/${scenarioId}/versions/${versionNo}/release`)
  return data
}

export async function unreleaseVersion(scenarioId, versionNo) {
  const { data } = await api.post(`/scenarios/${scenarioId}/versions/${versionNo}/unrelease`)
  return data
}

// ---------- 预测（阶段 3） ----------

export async function listActuals() {
  const { data } = await api.get('/forecast/actuals')
  return data
}

export async function upsertActuals(actuals) {
  const { data } = await api.post('/forecast/actuals', { actuals })
  return data
}

export async function importActuals(file) {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await api.post('/forecast/actuals/import', fd)
  return data
}

// 前端导入重建基础数据：现金流测算.xls + 财务报表.xlsx
export async function importRebuild(files) {
  const fd = new FormData()
  fd.append('file_main_xls', files.main)
  fd.append('file_report_xlsx', files.report)
  const { data } = await api.post('/imports/rebuild', fd)
  return data
}

export async function runForecast(payload) {
  const { data } = await api.post('/forecast/run', payload)
  return data
}

export async function applyForecast(payload) {
  const { data } = await api.post('/forecast/apply', payload)
  return data
}

export async function listForecastRuns(scenarioId) {
  const { data } = await api.get(`/forecast/runs?scenario_id=${scenarioId}`)
  return data
}

// ===== 管理员：用户管理 + 操作日志 =====
export async function listUsers() {
  const { data } = await api.get('/users')
  return data
}

export async function updateUserRole(userId, role) {
  const { data } = await api.patch(`/users/${userId}/role`, { role })
  return data
}

export async function updateUserStatus(userId, status) {
  const { data } = await api.patch(`/users/${userId}/status`, { status })
  return data
}

export async function listLogs({ limit = 50, offset = 0, userId, action } = {}) {
  const p = new URLSearchParams({ limit, offset })
  if (userId != null) p.set('user_id', userId)
  if (action) p.set('action', action)
  const { data } = await api.get(`/users/logs?${p.toString()}`)
  return data
}

export function fmt(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
