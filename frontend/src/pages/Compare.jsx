import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import {
  fmt, getGrid, getScenarioScale, getVersions, gridPeriods, listScenarios, previewRecalc,
} from '../api'
import {
  DEFAULT_OPTIMISTIC, DEFAULT_PESSIMISTIC, FACTOR_MAX, FACTOR_MIN,
  clampFactor, factorPct, scaleOverride, scenarioKind,
} from '../scenario'
import { buildOverride, buildExpenseInputs } from '../whatif'
import { FACTORS, cellValue, colorDomain, pctLabel } from '../matrix'

// 并发池：限流跑完全部任务（矩阵 49 次预览，避免一次性打满后端）
// ponytail: 前端并发 6；网格更细/更慢时改后端一次算完整个矩阵
async function runPool(tasks, limit) {
  let i = 0
  const worker = async () => { while (i < tasks.length) { const idx = i++; await tasks[idx]() } }
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker))
}

// 情景对比页（阶段5 · P1-5）：同一存档点（version_no 横跨三情景）下，把
// 中性/乐观/悲观并排比对。以中性为基线，非基线列显示 Δ 与高亮，一眼看清方案分歧。
// 乐观/悲观销量系数可当场调节（默认 ±20%）——调节即按相对系数重算预览，不写库。

// 并排展示的关键指标：sum=全期合计，last=期末值
const METRICS = [
  { key: 'sale.total.amount', label: '累计销售额', agg: 'sum' },
  { key: 'collect.total', label: '累计回款', agg: 'sum' },
  { key: 'exp.total', label: '累计费用', agg: 'sum' },
  { key: 'purchase.total', label: '累计采购', agg: 'sum' },
  { key: 'cash.closing', label: '期末现金', agg: 'last' },
  { key: 'cash.gap', label: '最大资金缺口', agg: 'minlast' },
]
const SCN_COLOR = { 中性: '#4f8cff', 乐观: '#00b578', 悲观: '#f54e5e' }
// 中性→乐观→悲观 的稳定列序（seed/预算保存产出的三情景）
export const scnRank = (name) => (name.includes('中性') ? 0 : name.includes('乐观') ? 1 : name.includes('悲观') ? 2 : 3)

export function aggregate(grid, periods, key, agg) {
  if (!grid) return null
  const at = (p) => Number(grid.cells[key]?.[p]?.value ?? 0)
  if (agg === 'sum') return periods.reduce((a, p) => a + at(p), 0)
  if (agg === 'last') return at(periods[periods.length - 1])
  if (agg === 'minlast') return periods.reduce((m, p) => Math.min(m, at(p)), 0)  // 现金缺口取全期最深
  return null
}

export default function Compare() {
  const [scenarios, setScenarios] = useState([])
  const [versions, setVersions] = useState([])
  const [versionNo, setVersionNo] = useState(null)
  const [grids, setGrids] = useState({})     // {scenarioId: grid | null}
  const [factors, setFactors] = useState({})  // {scenarioId: 当前实际销量系数}
  const [optPct, setOptPct] = useState(factorPct(DEFAULT_OPTIMISTIC))
  const [pesPct, setPesPct] = useState(factorPct(DEFAULT_PESSIMISTIC))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const seq = useRef(0)                        // 预览请求序号，丢弃过期响应

  // ===== 现金流矩阵（销量 × 研发） =====
  const [mtxBase, setMtxBase] = useState(null)  // {params, grid} 基线情景快照，供系数叠加
  const [mtx, setMtx] = useState(null)          // 二维数组 [qtyIdx][rdIdx] = closing[] | null
  const [mtxBusy, setMtxBusy] = useState(0)     // 已完成格数（0=未跑）
  const [mtxMode, setMtxMode] = useState('min') // 'min' 全期最低 | 'month' 指定月
  const [mtxMonth, setMtxMonth] = useState(0)   // month 模式下的月份下标
  const [minCash] = useState(() => {
    const v = Number(localStorage.getItem('fm_min_cash'))
    return Number.isFinite(v) ? v : 0
  })

  useEffect(() => {
    (async () => {
      try {
        const scs = (await listScenarios()).slice().sort((a, b) => scnRank(a.name) - scnRank(b.name))
        setScenarios(scs)
        const base = scs.find((s) => s.is_active) || scs[0]
        if (!base) { setError('还没有任何情景'); setLoading(false); return }
        const { versions: vs } = await getVersions(base.id)
        setVersions(vs)
        setVersionNo(vs[0]?.version_no ?? null)
        // 各情景当前实际销量系数（相对中性）：调系数时据此算相对值，避免叠乘
        const pairs = await Promise.all(scs.map((s) =>
          getScenarioScale(s.id, base.id)
            .then((d) => [s.id, Number(d.factor)])
            .catch(() => [s.id, 1])
        ))
        setFactors(Object.fromEntries(pairs))
      } catch (e) {
        setError(String(e.response?.data?.detail || e.message)); setLoading(false)
      }
    })()
  }, [])

  // 各情景「本次要用的系数」：中性恒 1，乐观/悲观取滑杆值
  const factorByScn = useMemo(() => {
    const out = {}
    for (const s of scenarios) {
      const kind = scenarioKind(s.name)
      if (kind === 'optimistic') out[s.id] = clampFactor(optPct)
      else if (kind === 'pessimistic') out[s.id] = clampFactor(pesPct)
    }
    return out
  }, [scenarios, optPct, pesPct])

  // 存档点网格：系数未改动 → 直接用存档值；改动的情景 → 按相对系数重算预览
  // seq 守卫：连续输入时后发的预览可能先返回，否则旧结果会覆盖新结果
  useEffect(() => {
    if (versionNo === null || !scenarios.length) return
    let stale = false
    const mySeq = ++seq.current
    setLoading(true)
    Promise.all(scenarios.map((s) => {
      const target = factorByScn[s.id]
      const override = target == null ? null : scaleOverride(factors[s.id], target)
      if (!override) {
        return getGrid(s.id, versionNo).then((g) => [s.id, g]).catch(() => [s.id, null])
      }
      return previewRecalc(s.id, { params: override })
        .then((g) => [s.id, g]).catch(() => [s.id, null])
    })).then((pairs) => {
      if (stale || mySeq !== seq.current) return
      setGrids(Object.fromEntries(pairs))
      setLoading(false)
    })
    return () => { stale = true }
  }, [versionNo, scenarios, factorByScn, factors])

  const backToDefault = () => {
    setOptPct(factorPct(DEFAULT_OPTIMISTIC))
    setPesPct(factorPct(DEFAULT_PESSIMISTIC))
  }
  const coeffDirty = Math.abs(clampFactor(optPct) - DEFAULT_OPTIMISTIC) > 1e-9 ||
    Math.abs(clampFactor(pesPct) - DEFAULT_PESSIMISTIC) > 1e-9

  // 期间轴取任一已加载情景（三情景同期）
  const periods = useMemo(() => {
    const g = Object.values(grids).find(Boolean)
    return gridPeriods(g)
  }, [grids])

  const baseId = scenarios[0]?.id

  // 矩阵基线：拉基线情景的快照参数 + 基线网格（研发费用系数需按网格 exp.* 行缩放）
  useEffect(() => {
    if (!baseId) return
    let stale = false
    ;(async () => {
      try {
        const { params } = await getVersions(baseId)
        const grid = await previewRecalc(baseId, {})
        if (!stale) { setMtxBase({ params: params || {}, grid }); setMtx(null); setMtxBusy(0) }
      } catch { /* 矩阵是可选功能，基线拉取失败则不显示，不打断主对比 */ }
    })()
    return () => { stale = true }
  }, [baseId])

  const mtxPeriods = useMemo(() => gridPeriods(mtxBase?.grid), [mtxBase])

  // 跑矩阵：qty × rd 笛卡尔积各重算一次，取 cash.closing 全期序列。并发限流 + seq 守卫。
  const runMatrix = async () => {
    if (!mtxBase) return
    const mySeq = ++seq.current
    const grid = Array.from({ length: FACTORS.length }, () => Array(FACTORS.length).fill(null))
    setMtx(null); setMtxBusy(0); setError(null)
    let done = 0
    const tasks = []
    for (let qi = 0; qi < FACTORS.length; qi++) {
      for (let ri = 0; ri < FACTORS.length; ri++) {
        tasks.push(async () => {
          const override = buildOverride(mtxBase.params, { qtyFactor: FACTORS[qi] })
          const inputs = buildExpenseInputs(mtxBase.grid, { rdFactor: FACTORS[ri] })
          try {
            const g = await previewRecalc(baseId, inputs ? { params: override, inputs } : { params: override })
            grid[qi][ri] = mtxPeriods.map((p) => Number(g.cells['cash.closing']?.[p]?.value ?? 0))
          } catch { grid[qi][ri] = null }
          if (mySeq === seq.current) setMtxBusy(++done)
        })
      }
    }
    await runPool(tasks, 6)
    if (mySeq === seq.current) setMtx(grid)
  }

  // 矩阵热力图 option：x=研发系数、y=销量系数，色=按模式取的期末现金；水位居中红↔绿
  const mtxOption = useMemo(() => {
    if (!mtx) return {}
    const data = []
    const vals = []
    for (let qi = 0; qi < FACTORS.length; qi++) {
      for (let ri = 0; ri < FACTORS.length; ri++) {
        const v = cellValue(mtx[qi][ri], mtxMode, mtxMonth)
        if (v != null) vals.push(v)
        data.push([ri, qi, v == null ? '-' : Math.round(v)])
      }
    }
    const dom = colorDomain(vals, minCash)
    const labels = FACTORS.map(pctLabel)
    return {
      tooltip: {
        formatter: (p) => {
          const [ri, qi, v] = p.data
          return `销量 ${labels[qi]} · 研发 ${labels[ri]}<br/>${mtxMode === 'min' ? '全期最低' : mtxPeriods[mtxMonth]?.slice(2)}期末现金：<b>${v === '-' ? '—' : fmt(v, 0)}</b> 万`
        },
      },
      grid: { left: 56, right: 14, top: 10, bottom: 48, containLabel: true },
      xAxis: { type: 'category', data: labels, name: '研发成本', nameLocation: 'middle', nameGap: 30,
        nameTextStyle: { fontSize: 10, color: '#999' }, axisLabel: { fontSize: 9 } },
      yAxis: { type: 'category', data: labels, name: '销量', nameGap: 8,
        nameTextStyle: { fontSize: 10, color: '#999' }, axisLabel: { fontSize: 9 } },
      visualMap: {
        min: dom.min, max: dom.max, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
        itemHeight: 80, textStyle: { fontSize: 9 },
        inRange: { color: ['#e5484d', '#f6bd16', '#00b578'] },  // 红(破水位)→黄(水位)→绿(安全)
      },
      series: [{
        type: 'heatmap', data,
        label: { show: true, fontSize: 8, formatter: (p) => (p.data[2] === '-' ? '' : fmt(p.data[2], 0)) },
      }],
    }
  }, [mtx, mtxMode, mtxMonth, mtxPeriods, minCash])

  // 期末现金轨迹：三情景各一条线
  const cashOption = useMemo(() => {
    if (!periods.length) return {}
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 0) },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 48, right: 10, top: 12, bottom: 34, containLabel: true },
      xAxis: { type: 'category', data: periods.map((p) => `${p.slice(2, 4)}/${p.slice(5)}`),
        axisLabel: { fontSize: 9, interval: 5 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eee' } } },
      series: scenarios.map((s) => ({
        name: s.name, type: 'line', symbol: 'none', lineStyle: { width: 1.8 },
        color: SCN_COLOR[Object.keys(SCN_COLOR).find((k) => s.name.includes(k))] || '#8c8c8c',
        data: periods.map((p) => Number(grids[s.id]?.cells['cash.closing']?.[p]?.value ?? 0)),
      })),
    }
  }, [scenarios, grids, periods])

  const anyGrid = Object.values(grids).some(Boolean)

  return (
    <div className="page">
      <header className="app-header">
        <div>
          <h1>情景对比</h1>
          <div className="scenario-bar">
            <select value={versionNo ?? ''} onChange={(e) => setVersionNo(Number(e.target.value))}>
              {versions.map((v) => (
                <option key={v.version_no} value={v.version_no}>v{v.version_no} · {v.comment}</option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      <p className="hint" style={{ padding: '0 14px' }}>
        以「{scenarios[0]?.name || '中性'}」为基线，乐观/悲观列显示 Δ（相对基线，红升绿降）。
        系数调节为实时预览，不写库。
      </p>

      {loading && !anyGrid ? (
        <div className="loading">加载中…</div>
      ) : anyGrid ? (
        <>
          <section className="card">
            <div className="budget-sec-head">
              <h2>情景销量系数</h2>
              <button className="link-btn" onClick={backToDefault} disabled={!coeffDirty}>
                恢复默认（±20%）
              </button>
            </div>
            <div className="coef-grid">
              <label className="coef-item">
                <span className="coef-label" style={{ color: SCN_COLOR['乐观'] }}>乐观</span>
                <input type="number" step="1" value={optPct}
                  min={(FACTOR_MIN - 1) * 100} max={(FACTOR_MAX - 1) * 100}
                  onChange={(e) => setOptPct(e.target.value === '' ? '' : Number(e.target.value))}
                  onBlur={() => setOptPct(optPct === '' ? 0 : optPct)} />
                <span className="coef-unit">%</span>
              </label>
              <label className="coef-item">
                <span className="coef-label" style={{ color: SCN_COLOR['悲观'] }}>悲观</span>
                <input type="number" step="1" value={pesPct}
                  min={(FACTOR_MIN - 1) * 100} max={(FACTOR_MAX - 1) * 100}
                  onChange={(e) => setPesPct(e.target.value === '' ? '' : Number(e.target.value))}
                  onBlur={() => setPesPct(pesPct === '' ? 0 : pesPct)} />
                <span className="coef-unit">%</span>
              </label>
            </div>
            <p className="hint">
              销量整体缩放，如乐观 +30% 即未来期销量 ×1.3；范围 {(FACTOR_MIN - 1) * 100}% ~ +{(FACTOR_MAX - 1) * 100}%。
            </p>
          </section>

          <section className="card">
            <h2>关键指标并排（万元）</h2>
            <div className="table-wrap">
              <table className="data-table data-table--wide">
                <thead>
                  <tr>
                    <th>指标</th>
                    {scenarios.map((s) => {
                      const f = factorByScn[s.id]
                      return (
                        <th key={s.id}>
                          {s.name}
                          {f != null && (
                            <span className="th-sub">销量 ×{f.toFixed(2)}</span>
                          )}
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map((m) => {
                    const baseVal = aggregate(grids[baseId], periods, m.key, m.agg)
                    return (
                      <tr key={m.key}>
                        <td className="row-name">{m.label}</td>
                        {scenarios.map((s) => {
                          const v = aggregate(grids[s.id], periods, m.key, m.agg)
                          if (v == null) return <td key={s.id}>—</td>
                          const isBase = s.id === baseId
                          const d = baseVal == null ? 0 : v - baseVal
                          const changed = Math.abs(d) >= 0.5
                          return (
                            <td key={s.id} className={!isBase && changed ? 'cell-changed' : ''}>
                              {fmt(v, 0)}
                              {!isBase && changed && (
                                <span className={`cell-delta ${d > 0 ? 'up' : 'down'}`}>
                                  {d > 0 ? '+' : ''}{fmt(d, 0)}
                                </span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>期末现金轨迹</h2>
            <Chart option={cashOption} height={300} />
          </section>

          <section className="card">
            <div className="budget-sec-head">
              <h2>现金流矩阵（销量 × 研发）</h2>
              <button className="link-btn" onClick={runMatrix} disabled={!mtxBase || (mtxBusy > 0 && mtxBusy < 49)}>
                {mtxBusy > 0 && mtxBusy < 49 ? `测算中 ${mtxBusy}/49` : mtx ? '重新测算' : '开始测算'}
              </button>
            </div>
            <p className="hint">
              销量、研发成本各 ±30%（10% 一档）交错成 49 格，色 = 期末现金（红破 {fmt(minCash, 0)} 万水位 → 绿安全）。以「{scenarios[0]?.name || '中性'}」为基线，实时预览不写库。
            </p>
            {mtx ? (
              <>
                <div className="coef-grid" style={{ marginBottom: 8 }}>
                  <label className="coef-item">
                    <span className="coef-label">视角</span>
                    <select value={mtxMode} onChange={(e) => setMtxMode(e.target.value)}>
                      <option value="min">全期最低</option>
                      <option value="month">指定月</option>
                    </select>
                  </label>
                  {mtxMode === 'month' && (
                    <label className="coef-item" style={{ flex: 1 }}>
                      <span className="coef-label">{mtxPeriods[mtxMonth]?.slice(2) || ''}</span>
                      <input type="range" min={0} max={mtxPeriods.length - 1} step={1} value={mtxMonth}
                        onChange={(e) => setMtxMonth(Number(e.target.value))} style={{ flex: 1 }} />
                    </label>
                  )}
                </div>
                <Chart option={mtxOption} height={340} notMerge />
              </>
            ) : (
              <p className="hint" style={{ textAlign: 'center', padding: '20px 0' }}>
                {mtxBusy > 0 ? `测算中 ${mtxBusy}/49…` : '点「开始测算」跑 49 格组合（约需数秒）'}
              </p>
            )}
          </section>
        </>
      ) : (
        <div className="loading">该存档点无可对比数据</div>
      )}
    </div>
  )
}
