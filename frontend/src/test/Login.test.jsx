/**
 * Login.jsx 测试
 *
 * 重点在于飞书回调的落地处理：token 走 URL fragment 而非 query（fragment 不发往
 * 服务端，因此不进代理日志/Referer）。这段逻辑只有人能看出来对错，所以逐条锁死：
 * 解析成功必须落盘并清 fragment、错误必须显示、fragment 解析失败不能白屏。
 */
import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const devLogin = vi.fn()
const feishuAuthorizeUrl = vi.fn()
vi.mock('../api', () => ({
  devLogin: (...a) => devLogin(...a),
  feishuAuthorizeUrl: (...a) => feishuAuthorizeUrl(...a),
}))

import Login from '../pages/Login'

const onLogin = vi.fn()

// jsdom 原始 Location：有的用例会临时替换 window.location，用它在每例前还原
const REAL_LOCATION = window.location

beforeEach(() => {
  devLogin.mockReset()
  feishuAuthorizeUrl.mockReset()
  onLogin.mockReset()
  Object.defineProperty(window, 'location', {
    configurable: true, writable: true, value: REAL_LOCATION,
  })
  window.history.replaceState({}, '', '/login')
})

function renderAt(url) {
  window.history.replaceState({}, '', url)
  return render(<Login onLogin={onLogin} />)
}

describe('飞书回调落地', () => {
  it('从 fragment 取 token 与 user，落盘后回调并清空 fragment', async () => {
    const user = { id: 7, name: '刘丹', role: 'admin' }
    renderAt(`/login#access_token=tok-abc&user=${encodeURIComponent(JSON.stringify(user))}`)

    await waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1))
    expect(onLogin.mock.calls[0][0]).toMatchObject({ id: 7, name: '刘丹' })
    expect(localStorage.getItem('token')).toBe('tok-abc')
    expect(JSON.parse(localStorage.getItem('user')).name).toBe('刘丹')
    // fragment 必须清掉：否则刷新会重复消费，且 token 留在地址栏/历史里
    expect(window.location.hash).toBe('')
  })

  it('fragment 里的 user 是坏 JSON 时提示解析失败，且不写入凭据', async () => {
    renderAt('/login#access_token=tok-abc&user=%7Bbad-json')

    expect(await screen.findByText('登录信息解析失败，请重试')).toBeInTheDocument()
    expect(onLogin).not.toHaveBeenCalled()
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('回调带 error 时显示错误并清空 URL', async () => {
    renderAt('/login?error=%E6%8E%88%E6%9D%83%E5%A4%B1%E8%B4%A5')

    expect(await screen.findByText('授权失败')).toBeInTheDocument()
    expect(onLogin).not.toHaveBeenCalled()
    expect(window.location.search).toBe('')
  })

  it('仅有 fragment、没有 token 时不触发登录', async () => {
    renderAt('/login#foo=bar')
    await waitFor(() => expect(onLogin).not.toHaveBeenCalled())
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('回到本用例时 location 仍是真实 Location（防止上游用例换桩后断言变空洞）', () => {
    window.history.replaceState({}, '', '/login#probe=1')
    expect(window.location).toBe(REAL_LOCATION)
    expect(window.location.hash).toBe('#probe=1')
    expect(window.location.search).toBe('')
  })
})

describe('进入系统按钮', () => {
  it('dev-login 成功时直接进入并落盘凭据', async () => {
    devLogin.mockResolvedValue({ id: 1, name: '开发者', role: 'admin' })
    renderAt('/login')

    fireEvent.click(screen.getByRole('button', { name: '进入系统' }))

    await waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1))
    expect(devLogin).toHaveBeenCalledTimes(1)
    // 走通了就不用再去问飞书授权地址
    expect(feishuAuthorizeUrl).not.toHaveBeenCalled()
  })

  it('dev-login 不可用（生产）时回退到飞书授权跳转', async () => {
    devLogin.mockRejectedValue(new Error('503'))
    feishuAuthorizeUrl.mockResolvedValue('https://open.feishu.cn/authorize?x=1')

    // 不能 delete window.location：那会把 jsdom 的 Location 换成普通对象，
    // 且污染后续用例（hash/search 全变 undefined，断言变成空洞通过）。
    // 改为拦 href 的赋值，捕获真实跳转。
    const realLocation = window.location
    const hrefSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      get: () => new Proxy(realLocation, {
        set: (t, prop, v) => { if (prop === 'href') hrefSpy(v); return true },
        get: (t, prop) => t[prop],
      }),
    })

    renderAt('/login')
    fireEvent.click(screen.getByRole('button', { name: '进入系统' }))

    await waitFor(() => expect(feishuAuthorizeUrl).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(hrefSpy).toHaveBeenCalledWith('https://open.feishu.cn/authorize?x=1'))
    expect(onLogin).not.toHaveBeenCalled()
  })

  it('两条路都失败时把后端 detail 显示出来', async () => {
    devLogin.mockRejectedValue(new Error('503'))
    feishuAuthorizeUrl.mockRejectedValue({ response: { data: { detail: '飞书未配置' } } })
    renderAt('/login')

    fireEvent.click(screen.getByRole('button', { name: '进入系统' }))

    expect(await screen.findByText('飞书未配置')).toBeInTheDocument()
  })
})
