import React, { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Forecast from './pages/Forecast'
import Params from './pages/Params'

function loadUser() {
  try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null }
}

export default function App() {
  const [user, setUser] = useState(loadUser)

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setUser(null)
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login"
          element={user ? <Navigate to="/" replace /> : <Login onLogin={setUser} />} />
        <Route path="/*"
          element={user ? <Shell user={user} onLogout={logout} /> : <Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

// 已登录布局：内容路由 + 底部 tab（移动优先）。切 tab 会重挂载 Dashboard → 自动拉最新版本
function Shell({ user, onLogout }) {
  return (
    <div className="shell">
      <div className="shell-body">
        <Routes>
          <Route path="/" element={<Dashboard user={user} onLogout={onLogout} />} />
          <Route path="/forecast" element={<Forecast user={user} />} />
          <Route path="/params" element={<Params />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <nav className="tab-bar">
        <NavLink to="/" end>看板</NavLink>
        <NavLink to="/forecast">预测</NavLink>
        <NavLink to="/params">参数</NavLink>
      </nav>
    </div>
  )
}
