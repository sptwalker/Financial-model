import React, { useEffect, useState } from 'react'
import { listUsers, updateUserRole, updateUserStatus, listLogs } from '../api'

const ROLE_LABEL = { admin: '管理员', editor: '编辑', viewer: '查看' }
const STATUS_LABEL = { pending: '待审批', active: '已启用', disabled: '已禁用' }
const PAGE = 50

function fmtTime(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function Admin({ user }) {
  const [users, setUsers] = useState([])
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  // 日志分页
  const [logs, setLogs] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)

  const loadUsers = async () => {
    try { setUsers(await listUsers()) }
    catch (e) { setMsg(String(e.response?.data?.detail || e.message)) }
  }

  const loadLogs = async (off = 0) => {
    try {
      const { items, total: t } = await listLogs({ limit: PAGE, offset: off })
      setLogs(items); setTotal(t); setOffset(off)
    } catch (e) { setMsg(String(e.response?.data?.detail || e.message)) }
  }

  useEffect(() => { loadUsers(); loadLogs(0) }, [])

  const changeRole = async (u, role) => {
    if (role === u.role) return
    try {
      setBusy(true); setMsg(null)
      await updateUserRole(u.id, role)
      setMsg(`已将 ${u.name} 设为${ROLE_LABEL[role]}`)
      await loadUsers()
    } catch (e) { setMsg(String(e.response?.data?.detail || e.message)) }
    finally { setBusy(false) }
  }

  const changeStatus = async (u, status, verb) => {
    try {
      setBusy(true); setMsg(null)
      await updateUserStatus(u.id, status)
      setMsg(`已${verb} ${u.name}`)
      await loadUsers()
    } catch (e) { setMsg(String(e.response?.data?.detail || e.message)) }
    finally { setBusy(false) }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE))
  const curPage = Math.floor(offset / PAGE) + 1

  return (
    <div className="page">
      <header className="app-header">
        <div><h1>管理</h1></div>
      </header>

      {msg && <div className="recalc-msg">{msg}</div>}

      <section className="card">
        <h2>用户管理</h2>
        <p className="hint">新用户首次登录为「待审批」，需在此放行后方可进入系统；可随时调整角色或屏蔽。</p>
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr><th>姓名</th><th>部门</th><th>角色</th><th>状态</th><th>最后登录</th><th>操作</th></tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const self = u.id === user?.id
                return (
                  <tr key={u.id}>
                    <td>{u.name}{self && <em className="self-tag">（我）</em>}</td>
                    <td className="muted">{u.department || '—'}</td>
                    <td>
                      <select value={u.role} disabled={self || busy}
                        onChange={(e) => changeRole(u, e.target.value)}>
                        <option value="viewer">查看</option>
                        <option value="editor">编辑</option>
                        <option value="admin">管理员</option>
                      </select>
                    </td>
                    <td><span className={`badge badge-${u.status}`}>{STATUS_LABEL[u.status] || u.status}</span></td>
                    <td className="muted">{fmtTime(u.last_login_at)}</td>
                    <td className="admin-actions">
                      {u.status === 'pending' && !self && (
                        <>
                          <button className="btn-sm ok" disabled={busy}
                            onClick={() => changeStatus(u, 'active', '放行')}>通过</button>
                          <button className="btn-sm danger" disabled={busy}
                            onClick={() => changeStatus(u, 'disabled', '拒绝')}>拒绝</button>
                        </>
                      )}
                      {u.status === 'active' && !self && (
                        <button className="btn-sm danger" disabled={busy}
                          onClick={() => changeStatus(u, 'disabled', '屏蔽')}>屏蔽</button>
                      )}
                      {u.status === 'disabled' && !self && (
                        <button className="btn-sm ok" disabled={busy}
                          onClick={() => changeStatus(u, 'active', '恢复')}>恢复</button>
                      )}
                      {self && <span className="muted">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2>操作日志</h2>
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr><th>时间</th><th>用户</th><th>动作</th><th>描述</th><th>IP</th></tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="muted nowrap">{fmtTime(l.created_at)}</td>
                  <td>{l.user_name || (l.user_id != null ? `#${l.user_id}` : '—')}</td>
                  <td><code className="action-tag">{l.action}</code></td>
                  <td>{l.description || '—'}</td>
                  <td className="muted">{l.ip || '—'}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr><td colSpan={5} className="muted" style={{ textAlign: 'center', padding: '20px' }}>暂无日志</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <button className="btn-sm" disabled={offset <= 0} onClick={() => loadLogs(offset - PAGE)}>上一页</button>
          <span className="muted">第 {curPage} / {pages} 页 · 共 {total} 条</span>
          <button className="btn-sm" disabled={offset + PAGE >= total} onClick={() => loadLogs(offset + PAGE)}>下一页</button>
        </div>
      </section>
    </div>
  )
}
