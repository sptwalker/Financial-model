import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import ThreeScenarioCard from '../components/ThreeScenarioCard'
import { fmt, getGrid, getVersions, gridPeriods, listScenarios, putCells, recalc,
  releaseVersion, unreleaseVersion } from '../api'
import { ROW_GROUPS, rowInfo, CASH_COLORS } from '../rows'

// 图表共用的 42 个月坐标轴标签：'26/07' 紧凑格式
function axisLabels(periods) {
  return periods.map((p) => `${p.slice(2, 4)}/${p.slice(5)}`)
}

function seriesOf(periods, cells, key, color) {
  const rows = cells[key] || {}
  return {
    name: rowInfo(key)?.label || key,
    type: 'bar',
    stack: 'sales',
    color,
    data: periods.map((p) => Number(rows[p]?.value ?? 0)),
  }
}

export default function Dashboard({ user, onLogout }) {
  const [scenarios, setScenarios] = useState([])
  const [scenarioId, setScenarioId] = useState(null)
  const [versions, setVersions] = useState([])
  const [versionNo, setVersionNo] = useState(null)
  const [grid, setGrid] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [recalcMsg, setRecalcMsg] = useState(null)
  const [showTable, setShowTable] = useState(false)
  const [selected, setSelected] = useState(null)
  const fetchSeq = useRef(0)

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        const active = scs.find((s) => s.is_active) || scs[0]
        if (!active) {
          setError('还没有任何情景，请先在后端执行种子导入')
          setLoading(false)
          return
        }
        setScenarioId(active.id)
        const { versions: vs } = await getVersions(active.id)
        setVersions(vs)
        if (vs.length) setVersionNo(vs[0].version_no)
      } catch (e) {
        setError(String(e.response?.data?.detail || e.message))
        setLoading(false)
      }
    })()
  }, [])

  useEffect(() => {
    if (!scenarioId || versionNo === null) return
    let stale = false
    setLoading(true)
    setError(null)
    getGrid(scenarioId, versionNo)
      .then((g) => !stale && setGrid(g))
      .catch((e) => !stale && setError(String(e.response?.data?.detail || e.message)))
      .finally(() => !stale && setLoading(false))
    return () => { stale = true }
  }, [scenarioId, versionNo])

  const periods = useMemo(
    () => gridPeriods(grid),
    [grid]
  )

  const stats = useMemo(() => {
    if (!grid) return null
    const sum = (key) => periods.reduce(
      (a, p) => a + Number(grid.cells[key]?.[p]?.value ?? 0), 0)
    const last = (key) => Number(grid.cells[key]?.[periods[periods.length - 1]]?.value ?? 0)
    return {
      sale: sum('sale.total.amount'),
      collect: sum('collect.total'),
      expense: sum('exp.total'),
      purchase: sum('purchase.total'),
      cashClose: last('cash.closing'),
      cashOpen: Number(grid.cells['cash.opening']?.[periods[0]]?.value ?? 0),
    }
  }, [grid, periods])

  const salesOption = useMemo(() => {
    if (!grid) return {}
    const keys = ['sale.online.amount', 'sale.offline.amount',
      'sale.accessory.amount', 'sale.subscription.amount']
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 2) },
      legend: { bottom: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10 } },
      grid: { left: 44, right: 8, top: 12, bottom: 34, containLabel: true },
      xAxis: {
        type: 'category', data: axisLabels(periods),
        axisLabel: { fontSize: 9, interval: 5 },
      },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eee' } } },
      series: keys.map((k) => seriesOf(periods, grid.cells, k, CASH_COLORS[k])),
    }
  }, [grid, periods])

  const cashOption = useMemo(() => {
    if (!grid) return {}
    const labels = axisLabels(periods)
    const line = (key, color, dash = false) => ({
      name: rowInfo(key)?.label || key,
      type: 'line', color, symbol: 'none',
      lineStyle: dash ? { width: 1.5, type: 'dashed' } : { width: 1.5 },
      data: periods.map((p) => Number(grid.cells[key]?.[p]?.value ?? 0)),
    })
    // 融资款注入点：在现金流水图上标竖线 + 金额
    const finRow = grid.cells['cash.financing'] || {}
    const finMarks = periods
      .map((p, i) => ({ p, i, v: Number(finRow[p]?.value ?? 0) }))
      .filter((m) => m.v > 0)
      .map((m) => ({
        xAxis: labels[m.i],
        label: { formatter: `融资 ${fmt(m.v, 0)}万`, fontSize: 9, color: '#9254de', position: 'insideEndTop' },
      }))
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 2) },
      legend: { bottom: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10 } },
      grid: { left: 44, right: 8, top: 12, bottom: 34, containLabel: true },
      xAxis: {
        type: 'category', data: labels,
        axisLabel: { fontSize: 9, interval: 5 },
      },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eee' } } },
      series: [
        line('cash.incoming', '#4f8cff'),
        line('cash.expense', '#f54e5e'),
        line('cash.gap', '#f6bd16', true),
        {
          ...line('cash.closing', '#00b578'),
          markLine: finMarks.length ? {
            symbol: 'none', silent: true,
            lineStyle: { color: '#9254de', type: 'dashed', width: 1.5 },
            data: finMarks,
          } : undefined,
        },
      ],
    }
  }, [grid, periods])

  async function doRecalc() {
    try {
      setRecalcMsg('计算中…')
      const r = await recalc(scenarioId, { comment: `看板重算（v${versionNo}）` })
      setRecalcMsg(`已完成，新版本 v${r.version_no}`)
      const { versions: vs } = await getVersions(scenarioId)
      setVersions(vs)
      setVersionNo(r.version_no)
    } catch (e) {
      setRecalcMsg('重算失败：' + String(e.response?.data?.detail || e.message))
    }
  }

  async function toggleRelease(release) {
    try {
      setRecalcMsg(release ? '发布中…' : '撤销中…')
      const fn = release ? releaseVersion : unreleaseVersion
      await fn(scenarioId, versionNo)
      const { versions: vs } = await getVersions(scenarioId)
      setVersions(vs)
      setRecalcMsg(release ? `已发布 v${versionNo}` : `已撤销发布 v${versionNo}`)
    } catch (e) {
      setRecalcMsg('操作失败：' + String(e.response?.data?.detail || e.message))
    }
  }

  const selectScenario = async (id) => {
    const seq = ++fetchSeq.current
    setScenarioId(id)
    try {
      const { versions: vs } = await getVersions(id)
      if (seq !== fetchSeq.current) return // 过期响应丢弃，避免覆盖新情景
      setVersions(vs)
      setVersionNo(vs.length ? vs[0].version_no : null)
    } catch (e) {
      if (seq === fetchSeq.current) setError(String(e.response?.data?.detail || e.message))
    }
  }

  const isLatest = versionNo != null && versions.length > 0 && versionNo === versions[0].version_no
  const isAdmin = user?.role === 'admin'
  const currentVersion = versions.find((v) => v.version_no === versionNo)
  const isReleased = !!currentVersion?.released_at
  const releasedVersion = versions.find((v) => v.released_at)

  return (
    <div className="page">
      <header className="app-header">
        <div>
          <h1>现金流预测</h1>
          <div className="scenario-bar">
            <select value={scenarioId ?? ''} onChange={(e) => selectScenario(Number(e.target.value))}>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}{s.is_active ? '（默认）' : ''}
                </option>
              ))}
            </select>
            <select value={versionNo ?? ''} onChange={(e) => setVersionNo(Number(e.target.value))}>
              {(versions || []).map((v) => (
                <option key={v.version_no} value={v.version_no}>
                  v{v.version_no} · {v.comment}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="user-box">
          <span className="avatar">{user?.name?.[0] || '?'}</span>
          <button className="link-btn" onClick={onLogout}>退出</button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {recalcMsg && <div className="recalc-msg">{recalcMsg}</div>}

      <div className="release-bar">
        <span className="release-info">
          {releasedVersion
            ? <>当前发布版本：<b>v{releasedVersion.version_no}</b>{isReleased ? '（正在查看）' : ''}</>
            : '尚未发布任何版本'}
          {isReleased && <span className="release-badge">已发布</span>}
        </span>
        {isAdmin && (
          isReleased
            ? <button className="link-btn" onClick={() => toggleRelease(false)}>撤销发布</button>
            : <button className="link-btn" onClick={() => toggleRelease(true)}
                disabled={versionNo == null}>发布此版本 v{versionNo}</button>
        )}
      </div>

      {loading && !grid ? (
        <div className="loading">加载中…</div>
      ) : grid && stats ? (
        <>
          <section className="stats-grid">
            <Stat label="累计销售额" value={fmt(stats.sale, 0)} sub="万元" tone="blue" />
            <Stat label="累计回款" value={fmt(stats.collect, 0)} sub="万元" tone="green" />
            <Stat label="累计费用" value={fmt(stats.expense, 0)} sub="万元" tone="orange" />
            <Stat label="累计采购" value={fmt(stats.purchase, 0)} sub="万元" tone="red" />
            <Stat label="期初现金" value={fmt(stats.cashOpen, 0)} sub="万元" tone="gray" />
            <Stat label="期末现金" value={fmt(stats.cashClose, 0)} sub="万元" tone="gray" />
          </section>

          <section className="card">
            <h2>现金流水</h2>
            <Chart option={cashOption} height={300} />
          </section>

          <section className="card">
            <h2>销售额构成</h2>
            <Chart option={salesOption} height={280} />
          </section>

          <ThreeScenarioCard scenarioId={scenarioId} />

          <section className="card">
            <h2>全部指标</h2>
            <p className="hint">
              2028 为年度目标（显示为全年合计在 12 月）；蓝色行可点击编辑。
            </p>
            <div className="row-summary">
              {ROW_GROUPS.map((g) => (
                <div className="row-group" key={g.name}>
                  <div className="row-group-title">{g.name}</div>
                  {g.rows.map((r) => {
                    const last = grid.cells[r.key]?.[periods[periods.length - 1]]
                    return (
                      <div className="row-line" key={r.key}
                        onClick={() => r.editable && isLatest && setSelected(r.key)}>
                        <span className="row-label">{r.label}</span>
                        <span className="row-val">
                          {fmt(last?.value)} {r.unit === '万台' ? '万台' : '万'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
            <button className="btn" onClick={() => setShowTable(true)}>查看全部月份数据</button>
          </section>

            {!isLatest && (
              <p className="hint">当前查看的是历史版本，编辑与重算已锁定；请切换到最新版本（下拉框最上方）后操作。</p>
            )}
            <button className="btn primary recalc-btn" onClick={doRecalc}
              disabled={recalcMsg === '计算中…' || !isLatest}>
              用当前参数重算
            </button>
        </>
      ) : null}

      <footer className="app-footer">
        <span>v{versionNo ?? '-'}</span>
        <span>{periods.length ? `${periods[0]} ~ ${periods[periods.length - 1]}` : ''}</span>
      </footer>

      {selected && grid && (
        <RowEditor rowKey={selected} periods={periods} grid={grid}
          onClose={() => setSelected(null)} scenarioId={scenarioId} isLatest={isLatest} />
      )}
      {showTable && (
        <FullTable periods={periods} grid={grid} onClose={() => setShowTable(false)} />
      )}
    </div>
  )
}

function Stat({ label, value, sub, tone }) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  )
}

function RowEditor({ rowKey, periods, grid, scenarioId, isLatest, onClose }) {
  const info = rowInfo(rowKey)
  const [values, setValues] = useState(() => {
    const out = {}
    for (const p of periods) out[p] = grid.cells[rowKey]?.[p]?.value ?? ''
    return out
  })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const save = async () => {
    try {
      setSaving(true)
      const cleared = periods.some((p) => values[p] === '' || values[p] === null || values[p] === undefined)
      const cells = {}
      for (const p of periods) {
        if (!info.editable) continue
        if (values[p] !== '' && values[p] !== null && values[p] !== undefined) {
          cells[rowKey] = cells[rowKey] || {}
          cells[rowKey][p] = String(values[p])
        }
      }
      await putCells(scenarioId, cells)
      setMsg(cleared
        ? '已保存；空白格按“保持原值”处理，如需清零请输入 0'
        : '已保存，点“重算”生效')
    } catch (e) {
      setMsg('保存失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>{info?.label}（{info?.group}）</strong>
          <button className="link-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="modal-body">
          {info?.editable ? (
            <>
              <div className="hint">输入行：修改后保存 → 在总览点“用当前参数重算”生成新版本。</div>
              <div className="edit-grid">
                {periods.map((p) => (
                  <label className="edit-cell" key={p}>
                    <span>{p.slice(2)}</span>
                    <input type="number" step="any" value={values[p] ?? ''}
                      onChange={(e) => setValues({ ...values, [p]: e.target.value })} />
                  </label>
                ))}
              </div>
              {!isLatest && <div className="hint">当前为历史版本，只读。</div>}
              <button className="btn primary" onClick={save} disabled={saving || !isLatest}>
                {saving ? '保存中…' : '保存'}
              </button>
              {msg && <div className="recalc-msg">{msg}</div>}
            </>
          ) : (
            <div className="hint">该行为引擎计算结果，只读（如需修改请调整上游输入或参数）。</div>
          )}
        </div>
      </div>
    </div>
  )
}

function FullTable({ periods, grid, onClose }) {
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>全部指标 · 全部月份（万元）</strong>
          <button className="link-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>指标</th>
                {periods.map((p) => <th key={p}>{p.slice(2)}</th>)}
              </tr>
            </thead>
            <tbody>
              {ROW_GROUPS.flatMap((g) => g.rows).map((r) => (
                <tr key={r.key}>
                  <td className="row-name">{r.label}</td>
                  {periods.map((p) => (
                    <td key={p}>{fmt(grid.cells[r.key]?.[p]?.value, 2)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
