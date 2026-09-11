/**
 * App.jsx 路由与权限测试
 *
 * 覆盖三件容易悄悄写错、又只有人能发现的事：
 * 1. 未登录必须被挡到 /login（前端不做真鉴权，但绝不能暴露页面骨架）；
 * 2. 管理员 tab 只对 admin 出现 —— 越权入口靠后端兜底，前端不该先递刀子；
 * 3. 登录态来自 localStorage，脏数据（坏 JSON）不能让整个应用白屏。
 */
import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

// 页面组件在测试里用轻量替身：这里验证的是路由与权限，不是各页内部实现
vi.mock('../pages/Login', () => ({
  default: ({ onLogin }) => (
    <div data-testid="login-page">
      <button onClick={() => onLogin({ id: 1, name: '刘丹', role: 'admin' })}>假登录</button>
    </div>
  ),
}))
vi.mock('../pages/Dashboard', () => ({
  default: ({ onLogout }) => (
    <div>
      看板内容
      <button onClick={onLogout}>退出</button>
    </div>
  ),
}))
vi.mock('../pages/Budget', () => ({ default: () => <div>预算内容</div> }))
vi.mock('../pages/Params', () => ({ default: () => <div>设置内容</div> }))
vi.mock('../pages/Admin', () => ({ default: () => <div>管理内容</div> }))

import App from '../App'

function setUser(user, token = 'tok') {
  localStorage.setItem('token', token)
  localStorage.setItem('user', JSON.stringify(user))
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
})

describe('登录门禁', () => {
  it('无登录态时停在登录页', async () => {
    render(<App />)
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByText('看板内容')).not.toBeInTheDocument()
  })

  it('有登录态时直接进看板，不再显示登录页', async () => {
    setUser({ id: 1, name: '刘丹', role: 'admin' })
    render(<App />)
    expect(await screen.findByText('看板内容')).toBeInTheDocument()
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  it('localStorage 里的 user 是坏 JSON 时按未登录处理，不抛异常', async () => {
    localStorage.setItem('user', '{不是合法 JSON')
    render(<App />)
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
  })
})

describe('底部导航与角色', () => {
  it('admin 能看到「管理」tab', async () => {
    setUser({ id: 1, name: '刘丹', role: 'admin' })
    render(<App />)
    expect(await screen.findByRole('link', { name: '管理' })).toBeInTheDocument()
  })

  it('普通编辑者看不到「管理」tab', async () => {
    setUser({ id: 2, name: '张三', role: 'editor' })
    render(<App />)
    await screen.findByText('看板内容')
    expect(screen.queryByRole('link', { name: '管理' })).not.toBeInTheDocument()
  })

  it('三类用户都能看到预算/看板/设置三个基础 tab', async () => {
    setUser({ id: 2, name: '只读', role: 'viewer' })
    render(<App />)
    await screen.findByText('看板内容')
    for (const name of ['预算', '看板', '设置']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
  })
})

describe('路由', () => {
  it('editor 访问 /admin 会被重定向回看板（不渲染管理页）', async () => {
    setUser({ id: 2, name: '张三', role: 'editor' })
    window.history.pushState({}, '', '/admin')
    render(<App />)
    expect(await screen.findByText('看板内容')).toBeInTheDocument()
    expect(screen.queryByText('管理内容')).not.toBeInTheDocument()
  })

  it('admin 访问 /admin 正常渲染管理页', async () => {
    setUser({ id: 1, name: '刘丹', role: 'admin' })
    window.history.pushState({}, '', '/admin')
    render(<App />)
    expect(await screen.findByText('管理内容')).toBeInTheDocument()
  })

  it('未知路径回落到看板', async () => {
    setUser({ id: 1, name: '刘丹', role: 'admin' })
    window.history.pushState({}, '', '/不存在的页面')
    render(<App />)
    expect(await screen.findByText('看板内容')).toBeInTheDocument()
  })
})

describe('退出登录', () => {
  it('点击退出后清空本地凭据并回到登录页', async () => {
    setUser({ id: 1, name: '刘丹', role: 'admin' })
    render(<App />)
    await screen.findByText('看板内容')
    expect(localStorage.getItem('token')).toBe('tok')

    fireEvent.click(screen.getByRole('button', { name: '退出' }))

    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
})
