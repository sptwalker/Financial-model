import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import { fmt, getVersions, gridPeriods, listScenarios, previewRecalc } from '../api'
import { buildOverride, buildExpenseInputs, impactOf } from '../whatif'

// what-if 推演页（阶段5 · P2-6）：三个滑杆（单价系数 / 销量系数 / 当月回款占比）实时
// 叠加到情景快照参数上做非持久化预览，与基线并排看期末现金/资金缺口的敏感性。

const PCT = (v) => `${Math.round(v * 100)}%`
// 收入/回款侧 + 成本侧，各三项，页面排成两行三列
const SLIDERS = [
  { key: 'priceFactor', label: '单价', min: 0.8, max: 1.2, step: 0.01, fmt: PCT },
  { key: 'qtyFactor', label: '销量', min: 0.8, max: 1.2, step: 0.01, fmt: PCT },
  { key: 'collectNow', label: '当月回款', min: 0, max: 1, step: 0.05, fmt: PCT },
  { key: 'costBuy', label: '采购成本', min: 0.8, max: 1.2, step: 0.01, fmt: PCT },
  { key: 'expFactor', label: '运营费用', min: 0.8, max: 1.2, step: 0.01, fmt: PCT },
  { key: 'rdFactor', label: '研发成本', min: 0.8, max: 1.2, step: 0.01, fmt: PCT },
]
const DEFAULTS = { priceFactor: 1, qtyFactor: 1, collectNow: 0.5, costBuy: 1, expFactor: 1, rdFactor: 1 }

export default function WhatIf() {
  const [scenarios, setScenarios] = useState([])
  const [scenarioId, setScenarioId] = useState(null)
  const [baseParams, setBaseParams] = useState(null)
  const [knobs, setKnobs] = useState(DEFAULTS)
  const [base, setBase] = useState(null)      // 基线网格（快照参数）
  const [wif, setWif] = useState(null)        // 推演网格（叠加增量）
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        const active = scs.find((s) => s.is_active) || scs[0]
        if (active) setScenarioId(active.id)
        else setError('还没有任何情景')
      } catch (e) { setError(String(e.response?.data?.detail || e.message)) }
    })()
  }, [])

  // 切情景：拉快照参数（供滑杆基线）+ 基线网格
  useEffect(() => {
    if (!scenarioId) return
    let stale = false
    setKnobs(DEFAULTS)
    ;(async () => {
      try {
        const { params } = await getVersions(scenarioId)
        if (stale) return
        setBaseParams(params || {})
        const b = await previewRecalc(scenarioId, {})
        if (!stale) setBase(b)
      } catch (e) { if (!stale) setError(String(e.response?.data?.detail || e.message)) }
    })()
    return () => { stale = true }
  }, [scenarioId])

  // 滑杆变动：去抖 300ms 后预览推演网格
  useEffect(() => {
    if (!scenarioId || !baseParams) return
    const baseCollect = Number(baseParams.collect_weight_online?.[0] ?? 0.5)
    const noChange = SLIDERS.every((s) =>
      s.key === 'collectNow' ? knobs.collectNow === baseCollect : knobs[s.key] === 1)
    if (noChange) { setWif(null); return }
    const mySeq = ++seq.current
    setBusy(true)
    const t = setTimeout(async () => {
      try {
        const override = buildOverride(baseParams, knobs)
        const inputs = buildExpenseInputs(base, { opexFactor: knobs.expFactor, rdFactor: knobs.rdFactor })
        const g = await previewRecalc(scenarioId, inputs ? { params: override, inputs } : { params: override })
        if (mySeq === seq.current) setWif(g)
      } catch (e) {
        if (mySeq === seq.current) setError(String(e.response?.data?.detail || e.message))
      } finally {
        if (mySeq === seq.current) setBusy(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [knobs, scenarioId, baseParams, base])

  const periods = useMemo(() => gridPeriods(base), [base])
  const baseImpact = useMemo(() => impactOf(base, periods), [base, periods])
  const wifImpact = useMemo(() => impactOf(wif || base, periods), [wif, base, periods])

  const cashOption = useMemo(() => {
    if (!periods.length) return {}
    const labels = periods.map((p) => `${p.slice(2, 4)}/${p.slice(5)}`)
    const valsOf = (g, key) => periods.map((p) => Number(g?.cells[key]?.[p]?.value ?? 0))
    const baseVals = valsOf(base, 'cash.closing')
    const mk = (data, name, color, solid = false) => ({
      name, type: 'line', symbol: 'none', color,
      lineStyle: { width: 1.8, type: solid ? 'solid' : 'dashed' }, data,
    })
    // 期末现金（基线灰实线）+ 资金缺口（基线黄实线）
    const series = [
      mk(baseVals, '基线', '#8c8c8c', true),
      mk(valsOf(base, 'cash.gap'), '基线缺口', '#f6bd16', true),
    ]
    if (wif) {
      const wifVals = valsOf(wif, 'cash.closing')
      const below = wifVals.map((v, i) => v < baseVals[i])
      // 蓝色完整推演线 + 红色仅覆盖低于基线的段（前后各扩一点，使穿越段落也转红）
      const redVals = wifVals.map((v, i) => (below[i] || below[i - 1] || below[i + 1]) ? v : null)
      series.push(mk(wifVals, '推演', '#4f8cff'))
      series.push({ ...mk(redVals, '推演·低于基线', '#e5484d'), z: 5 })
      series.push(mk(valsOf(wif, 'cash.gap'), '推演缺口', '#fa8c16'))
    }
    const legendData = series.map((s) => s.name).filter((n) => n !== '推演·低于基线')
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (ps) => {
          const rows = ps.filter((p) => p.seriesName !== '推演·低于基线')
          if (!rows.length) return ''
          return `${rows[0].axisValue}<br/>${rows.map((p) => `${p.marker}${p.seriesName}: ${fmt(p.value, 0)}`).join('<br/>')}`
        },
      },
      legend: { bottom: 0, textStyle: { fontSize: 11 }, data: legendData },
      grid: { left: 48, right: 10, top: 12, bottom: 34, containLabel: true },
      xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 9, interval: 5 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eee' } } },
      series,
    }
  }, [base, wif, periods])

  const rows = [
    { label: '销售收入', k: 'sales' },
    { label: '总成本', k: 'cost', higherWorse: true },   // 成本增加=红，减少=绿
    { label: '期末现金', k: 'cashClose' },
    { label: '最深资金缺口', k: 'maxGap' },
    { label: '累计回款', k: 'collect' },
  ]

  return (
    <div className="page">
      <header className="app-header">
        <div>
          <h1>敏感性推演</h1>
          <div className="scenario-bar">
            <select value={scenarioId ?? ''} onChange={(e) => setScenarioId(Number(e.target.value))}>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name}{s.is_active ? '（默认）' : ''}</option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      <p className="hint" style={{ padding: '0 14px' }}>
        滑杆实时预览（不写库）。单价/销量/成本为相对基线的系数（100%=不变），回款为线上当月回款占比。
      </p>

      <section className="card">
        <div className="budget-sec-head">
          <h2>假设条件</h2>
          <button className="link-btn" onClick={() => setKnobs(DEFAULTS)}>重置</button>
        </div>
        <div className="wif-grid">
          {SLIDERS.map((s) => (
            <div key={s.key} className="wif-slider">
              <div className="wif-slider-head">
                <span>{s.label}</span>
                <b>{s.fmt(knobs[s.key])}</b>
              </div>
              <input type="range" min={s.min} max={s.max} step={s.step} value={knobs[s.key]}
                onChange={(e) => setKnobs((k) => ({ ...k, [s.key]: Number(e.target.value) }))} />
            </div>
          ))}
        </div>
        {/* 常驻占位，避免 busy 切换时高度跳变导致页面闪动 */}
        <p className="hint wif-status">{busy ? '测算中…' : ' '}</p>
      </section>

      <section className="card">
        <h2>结果对比（万元）{wif ? '' : ' · 未改动'}</h2>
        <div className="table-wrap">
          <table className="data-table data-table--full">
            <thead><tr><th>指标</th><th>基线</th><th>推演</th><th>差值</th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const b = baseImpact?.[r.k]
                const w = wifImpact?.[r.k]
                const d = (b == null || w == null) ? 0 : w - b
                const changed = Math.abs(d) >= 0.5
                // 好=绿(down)/坏=红(up)；成本类升高为坏，故按 higherWorse 反转
                const good = r.higherWorse ? d < 0 : d > 0
                return (
                  <tr key={r.k}>
                    <td className="row-name">{r.label}</td>
                    <td>{b == null ? '—' : fmt(b, 0)}</td>
                    <td>{w == null ? '—' : fmt(w, 0)}</td>
                    <td className={changed ? 'cell-changed' : ''}>
                      {changed
                        ? <span className={`cell-delta ${good ? 'down' : 'up'}`}>{d > 0 ? '+' : ''}{fmt(d, 0)}</span>
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2>期末现金轨迹</h2>
        <Chart option={cashOption} height={300} notMerge />
      </section>
    </div>
  )
}
