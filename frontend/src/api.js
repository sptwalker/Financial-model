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

export function fmt(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
