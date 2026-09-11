import React, { useState, useEffect } from 'react'
import { feishuAuthorizeUrl, devLogin } from '../api'

/** 解析 URL fragment（#a=1&b=2）为 URLSearchParams；无 fragment 返回空 */
function hashParams() {
  const h = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash
  return new URLSearchParams(h)
}

export default function Login({ onLogin }) {
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  // 飞书回调落地：/login#access_token=...&user=... → 存储后清 fragment 进入系统。
  // token 放 fragment 而非 query：fragment 不随请求发往服务端，
  // 因此不进代理日志 / Referer / 服务端历史（后端 auth.py 对应改动）。
  useEffect(() => {
    const query = new URLSearchParams(location.search)
    const hash = hashParams()
    const error = query.get('error') || hash.get('error')
    if (error) {
      setErr(error)
      window.history.replaceState({}, '', '/login')
      return
    }
    const token = hash.get('access_token') || query.get('access_token')
    if (!token) return
    try {
      const user = JSON.parse(hash.get('user') || query.get('user'))
      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(user))
      window.history.replaceState({}, '', '/login')
      onLogin(user)
    } catch (e) {
      setErr('登录信息解析失败，请重试')
    }
  }, [onLogin])

  const enter = async () => {
    try {
      setLoading(true)
      setErr(null)
      const user = await devLogin()
      onLogin(user)
    } catch {
      // 生产环境 dev-login 不可用 → 引导飞书登录
      try {
        const url = await feishuAuthorizeUrl()
        location.href = url
      } catch (e2) {
        setErr(String(e2.response?.data?.detail || e2.message))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>创想悦动 · 现金流预测</h1>
        <p className="login-sub">销售 / 回款 / 采购 / 费用 / 现金 一体化测算看板</p>
        <button className="btn primary login-btn" onClick={enter} disabled={loading}>
          {loading ? '登录中…' : '进入系统'}
        </button>
        {err && <div className="error-banner">{err}</div>}
      </div>
    </div>
  )
}
