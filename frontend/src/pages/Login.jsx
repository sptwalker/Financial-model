import React, { useState } from 'react'
import { feishuAuthorizeUrl, devLogin } from '../api'

export default function Login({ onLogin }) {
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

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
