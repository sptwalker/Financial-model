import React, { useEffect, useMemo, useRef, useState } from 'react'
import { fmt, getGrid, getVersions, gridPeriods, listScenarios, previewRecalc, recalc } from '../api'
import { BUDGET_COST_GROUPS, BUDGET_SALES_QTY, BUDGET_SALES_PARAMS } from '../rows'

const r6 = (n) => Math.round(n * 1e6) / 1e6

// 期间分组：月=逐月；季=按年+季度；年=按年。用于年/季粒度的批量填充（展开为月度值）
function periodGroups(periods, gran) {
  if (gran === 'month') return periods.map((p) => ({ label: p.slice(2), months: [p] }))
  const byKey = {}
  const order = []
  for (const p of periods) {
    const [y, m] = p.split('-')
    const key = gran === 'year' ? y : `${y}Q${Math.ceil(Number(m) / 3)}`
    if (!byKey[key]) { byKey[key] = []; order.push(key) }
    byKey[key].push(p)
  }
  return order.map((k) => ({ label: k.length === 4 ? `${k.slice(2)}年` : k.slice(2), months: byKey[k] }))
}

export default function Budget() {
  const [scenarios, setScenarios] = useState([])
  const [scenarioId, setScenarioId] = useState(null)
  const [versionNo, setVersionNo] = useState(null)
  const [baseGrid, setBaseGrid] = useState(null)
  const [salesParams, setSalesParams] = useState({}) // {price_online,...} 当前值（可编辑）
  const [baseParams, setBaseParams] = useState({})   // 加载时的基线，用于判断是否改动
  const [edits, setEdits] = useState({})              // {row: {period: str}} 输入覆盖（已展开为月度）
  const [preview, setPreview] = useState(null)        // previewRecalc 回显的网格
  const [gran, setGran] = useState('month')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const fetchSeq = useRef(0)
  const timer = useRef(null)

  const load = async (id) => {
    const seq = ++fetchSeq.current
    try {
      const [g, { versions, params }] = await Promise.all([getGrid(id), getVersions(id)])
      if (seq !== fetchSeq.current) return
      setBaseGrid(g)
      setVersionNo(versions[0]?.version_no ?? null)
      const sp = {}
      for (const f of BUDGET_SALES_PARAMS) if (params?.[f.key] != null) sp[f.key] = params[f.key]
      setSalesParams(sp)
      setBaseParams(sp)
      setEdits({})
      setPreview(null)
    } catch (e) {
      if (seq === fetchSeq.current) setMsg(String(e.response?.data?.detail || e.message))
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        const active = scs.find((s) => s.name === '中性') || scs.find((s) => s.is_active) || scs[0]
        if (active) { setScenarioId(active.id); load(active.id) }
      } catch (e) {
        setMsg(String(e.response?.data?.detail || e.message))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const periods = useMemo(() => gridPeriods(baseGrid), [baseGrid])
  const groups = useMemo(() => periodGroups(periods, gran), [periods, gran])

  const inputsPayload = () => {
    const out = {}
    for (const row of Object.keys(edits)) {
      out[row] = {}
      for (const p of Object.keys(edits[row])) {
        const v = edits[row][p]
        out[row][p] = v === '' || v == null ? '0' : String(v)
      }
    }
    return out
  }
  const paramsPayload = () => {
    const changed = {}
    for (const f of BUDGET_SALES_PARAMS) {
      if (String(salesParams[f.key] ?? '') !== String(baseParams[f.key] ?? ''))
        changed[f.key] = salesParams[f.key]
    }
    return Object.keys(changed).length ? changed : undefined
  }
  const dirty = Object.keys(edits).length > 0 || paramsPayload() !== undefined

  // 边改边预览：编辑后防抖 400ms 调预览端点（不建版本）
  useEffect(() => {
    if (!scenarioId || !baseGrid) return
    if (!dirty) { setPreview(null); return }
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        const p = await previewRecalc(scenarioId, { params: paramsPayload(), inputs: inputsPayload() })
        setPreview(p)
      } catch (e) {
        setMsg('预览失败：' + String(e.response?.data?.detail || e.message))
      }
    }, 400)
    return () => clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edits, salesParams, scenarioId, baseGrid])

  // 输入框显示值：优先 edits，否则基线
  const effIn = (row, p) => {
    const e = edits[row]?.[p]
    if (e !== undefined) return e
    return baseGrid?.cells?.[row]?.[p]?.value ?? '0'
  }
  const groupVal = (row, months) =>
    months.length === 1 ? effIn(row, months[0])
      : r6(months.reduce((a, p) => a + Number(effIn(row, p) || 0), 0))
  const setGroup = (row, months, v) => {
    const each = months.length === 1 ? v : String(r6(Number(v || 0) / months.length))
    setEdits((prev) => {
      const next = { ...prev, [row]: { ...(prev[row] || {}) } }
      for (const p of months) next[row][p] = each
      return next
    })
  }

  const metrics = useMemo(() => {
    const cells = preview?.cells || baseGrid?.cells
    if (!cells || !periods.length) return null
    const sum = (k) => periods.reduce((a, p) => a + Number(cells[k]?.[p]?.value ?? 0), 0)
    const closings = periods.map((p) => Number(cells['cash.closing']?.[p]?.value ?? 0))
    return {
      cashClose: closings[closings.length - 1],
      cashMin: Math.min(...closings),
      sale: sum('sale.total.amount'),
      collect: sum('collect.total'),
      expense: sum('exp.total'),
      financing: sum('cash.financing'),
    }
  }, [preview, baseGrid, periods])

  const save = async () => {
    try {
      setBusy(true)
      setMsg('保存中…')
      const name = scenarios.find((s) => s.id === scenarioId)?.name || ''
      const r = await recalc(scenarioId, {
        params: paramsPayload(), inputs: inputsPayload(), comment: `预算调整 · ${name}`,
      })
      setMsg(`已保存新版本 v${r.version_no}（${r.cell_count} 单元格）`)
      await load(scenarioId)
    } catch (e) {
      setMsg('保存失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="app-header">
        <h1>预算设置</h1>
        <div className="scenario-bar">
          <select value={scenarioId ?? ''}
            onChange={(e) => { const id = Number(e.target.value); setScenarioId(id); load(id) }}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <span className="version-chip">当前 v{versionNo ?? '-'}</span>
          <select value={gran} onChange={(e) => setGran(e.target.value)}>
            <option value="month">按月</option>
            <option value="quarter">按季</option>
            <option value="year">按年</option>
          </select>
        </div>
      </header>

      {msg && <div className="recalc-msg">{msg}</div>}

      {!baseGrid ? (
        <div className="loading">加载中…</div>
      ) : (
        <>
          {metrics && (
            <section className="stats-grid budget-metrics">
              <Metric label="期末现金" value={fmt(metrics.cashClose, 0)} tone="gray" live={!!preview} />
              <Metric label="最低期末现金" value={fmt(metrics.cashMin, 0)}
                tone={metrics.cashMin < 0 ? 'red' : 'green'} live={!!preview} />
              <Metric label="累计销售" value={fmt(metrics.sale, 0)} tone="blue" live={!!preview} />
              <Metric label="累计回款" value={fmt(metrics.collect, 0)} tone="green" live={!!preview} />
              <Metric label="累计费用" value={fmt(metrics.expense, 0)} tone="orange" live={!!preview} />
              <Metric label="累计融资" value={fmt(metrics.financing, 0)} tone="gray" live={!!preview} />
            </section>
          )}

          <section className="card">
            <h2>销售设置</h2>
            <div className="param-list">
              {BUDGET_SALES_PARAMS.map((f) => (
                <label className="param-item" key={f.key}>
                  <span className="param-label">{f.label}</span>
                  <input type="number" step={f.step} value={salesParams[f.key] ?? ''}
                    onChange={(e) => setSalesParams((p) => ({ ...p, [f.key]: e.target.value }))} />
                </label>
              ))}
            </div>
            {BUDGET_SALES_QTY.map((row) => (
              <BudgetRow key={row.key} label={`${row.label}（${row.unit}）`} rowKey={row.key}
                groups={groups} groupVal={groupVal} setGroup={setGroup} />
            ))}
            <p className="hint">2028/2029 销量由年度目标驱动，逐月编辑对这两年可能被目标覆盖，请在中性方案确认年度目标。</p>
          </section>

          {BUDGET_COST_GROUPS.map((g) => (
            <section className="card" key={g.name}>
              <h2>成本预算 · {g.name}</h2>
              {g.rows.map((row) => (
                <BudgetRow key={row.key} label={row.label} rowKey={row.key}
                  groups={groups} groupVal={groupVal} setGroup={setGroup} />
              ))}
            </section>
          ))}

          <section className="card">
            <h2>投融资设置</h2>
            <p className="hint">到账融资款按月一次性注入现金，不做年度摊分。</p>
            <BudgetRow label="到账融资款" rowKey="cash.financing"
              groups={groups} groupVal={groupVal} setGroup={setGroup} />
          </section>

          <div className="action-row">
            <span className="hint">{dirty ? '已改动，指标为实时预览；点保存才落版本' : '未改动'}</span>
            <button className="btn primary" onClick={save} disabled={busy || !dirty}>
              {busy ? '保存中…' : '保存为新版本'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function Metric({ label, value, tone, live }) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}{live && <span className="live-dot" />}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">万元</div>
    </div>
  )
}

function BudgetRow({ label, rowKey, groups, groupVal, setGroup }) {
  return (
    <div className="budget-row">
      <div className="budget-row-label">{label}</div>
      <div className="budget-strip">
        {groups.map((grp) => (
          <label className="edit-cell" key={grp.label}>
            <span>{grp.label}</span>
            <input type="number" step="any" value={groupVal(rowKey, grp.months)}
              onChange={(e) => setGroup(rowKey, grp.months, e.target.value)} />
          </label>
        ))}
      </div>
    </div>
  )
}
