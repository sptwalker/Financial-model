import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import { fmt, getGrid, getVersions, gridPeriods, listScenarios, previewRecalc, recalc } from '../api'
import { BUDGET_COST_GROUPS, BUDGET_SALES_QTY, BUDGET_SALES_PARAMS } from '../rows'

const r2 = (n) => Math.round(n * 100) / 100                // 统一最多两位小数
const QTY_KEYS = new Set(BUDGET_SALES_QTY.map((r) => r.key))
const FINANCING = 'cash.financing'                         // 融资款：整数、一次性注入不摊分
const CHART_PALETTE = ['#4f8cff', '#5ad8a6', '#f6bd16', '#9254de', '#ff9f7f', '#5b8ff9', '#e86452']

// 方案 = 中性基准 × 销量系数（乐观 +20% / 悲观 -20%），成本/融资不随方案变
const SCENARIOS = [
  { name: '中性', factor: 1 },
  { name: '乐观', factor: 1.2 },
  { name: '悲观', factor: 0.8 },
]

// 期间分组：月=逐月；季=按年+季度；年=按年。年/季粒度批量填充时均摊为月度值
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

// 各分区成本行分组
const RD = BUDGET_COST_GROUPS[0].rows
const MKT = BUDGET_COST_GROUPS[1].rows
const ADMIN = BUDGET_COST_GROUPS[2].rows

export default function Budget() {
  const [scenarios, setScenarios] = useState([])      // DB 情景（含 id，用于保存）
  const [factor, setFactor] = useState(1)             // 当前方案销量系数
  const [neutralId, setNeutralId] = useState(null)    // 中性情景 id（编辑/预览基准）
  const [versionNo, setVersionNo] = useState(null)
  const [baseGrid, setBaseGrid] = useState(null)
  const [salesParams, setSalesParams] = useState({})
  const [baseParams, setBaseParams] = useState({})
  const [edits, setEdits] = useState({})              // {row: {period: str}} 中性基准输入覆盖（月度）
  const [preview, setPreview] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)   // 首次情景拉取是否完成（区分「加载中」与「空库」）
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
        const neutral = scs.find((s) => s.name === '中性') || scs[0]
        if (neutral) { setNeutralId(neutral.id); load(neutral.id) }
      } catch (e) {
        setMsg(String(e.response?.data?.detail || e.message))
      } finally {
        setReady(true)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const periods = useMemo(() => gridPeriods(baseGrid), [baseGrid])

  // 输入框显示值：优先 edits，否则中性基线
  const effIn = (row, p) => {
    const e = edits[row]?.[p]
    if (e !== undefined) return e
    return baseGrid?.cells?.[row]?.[p]?.value ?? '0'
  }
  const groupVal = (row, months) => {
    const sum = months.reduce((a, p) => a + Number(effIn(row, p) || 0), 0)
    if (row === FINANCING) return Math.round(sum)                 // 融资款：整数
    return months.length === 1 ? effIn(row, months[0]) : r2(sum)
  }
  const setGroup = (row, months, v) => {
    // 融资款：整数，且年/季整额一次性注入该组首月（不摊分，往返无损）
    if (row === FINANCING) {
      const total = String(Math.round(Number(v || 0)))
      setEdits((prev) => {
        const next = { ...prev, [row]: { ...(prev[row] || {}) } }
        months.forEach((p, i) => { next[row][p] = i === 0 ? total : '0' })
        return next
      })
      return
    }
    const each = months.length === 1 ? String(r2(Number(v || 0))) : String(r2(Number(v || 0) / months.length))
    setEdits((prev) => {
      const next = { ...prev, [row]: { ...(prev[row] || {}) } }
      for (const p of months) next[row][p] = each
      return next
    })
  }

  const paramsPayload = () => {
    const changed = {}
    for (const f of BUDGET_SALES_PARAMS) {
      if (String(salesParams[f.key] ?? '') !== String(baseParams[f.key] ?? ''))
        changed[f.key] = salesParams[f.key]
    }
    return Object.keys(changed).length ? changed : undefined
  }
  // 构造某方案的输入覆盖：中性用编辑增量；乐观/悲观再把销量整体乘系数
  const inputsPayload = (fac) => {
    const out = {}
    for (const row of Object.keys(edits)) {
      out[row] = {}
      for (const p of Object.keys(edits[row])) {
        const v = edits[row][p]
        out[row][p] = v === '' || v == null ? '0' : String(v)
      }
    }
    if (fac !== 1) {
      for (const q of QTY_KEYS) {
        out[q] = {}
        for (const p of periods) out[q][p] = String(r2(Number(effIn(q, p) || 0) * fac))
      }
    }
    return out
  }

  const dirty = Object.keys(edits).length > 0 || paramsPayload() !== undefined
  const needPreview = dirty || factor !== 1

  // 边改边预览 / 切换方案：防抖 400ms 调预览端点（不建版本）
  useEffect(() => {
    if (!neutralId || !baseGrid) return
    if (!needPreview) { setPreview(null); return }
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        const p = await previewRecalc(neutralId, { params: paramsPayload(), inputs: inputsPayload(factor) })
        setPreview(p)
      } catch (e) {
        setMsg('预览失败：' + String(e.response?.data?.detail || e.message))
      }
    }, 400)
    return () => clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edits, salesParams, factor, neutralId, baseGrid])

  const metrics = useMemo(() => {
    const cells = preview?.cells || baseGrid?.cells
    if (!cells || !periods.length) return null
    const sum = (k) => periods.reduce((a, p) => a + Number(cells[k]?.[p]?.value ?? 0), 0)
    const sumRows = (rows) => rows.reduce((a, r) => a + sum(r.key), 0)
    return {
      qty: sum('qty.total'),
      sale: sum('sale.total.amount'),
      rd: sumRows(RD),
      mkt: sumRows(MKT),
      admin: sumRows(ADMIN),
      financing: sum('cash.financing'),
    }
  }, [preview, baseGrid, periods])

  const save = async () => {
    try {
      setBusy(true)
      setMsg('保存中…')
      const params = paramsPayload()
      const byName = (n) => scenarios.find((s) => s.name === n)
      let last = null
      for (const s of SCENARIOS) {
        const sc = byName(s.name)
        if (!sc) continue
        const r = await recalc(sc.id, {
          params, inputs: inputsPayload(s.factor), comment: `预算调整 · ${s.name}`,
        })
        if (s.factor === 1) last = r
      }
      setMsg(`已保存：中性 v${last?.version_no}（乐观/悲观按 ±20% 同步）`)
      await load(neutralId)
    } catch (e) {
      setMsg('保存失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="app-header">
        <div>
          <h1>预算设置</h1>
          <div className="budget-scenarios">
            {SCENARIOS.map((s) => (
              <button key={s.name} className={factor === s.factor ? 'on' : ''}
                onClick={() => setFactor(s.factor)}>
                {s.name}{s.factor !== 1 ? `（销量${s.factor > 1 ? '+' : '-'}20%）` : ''}
              </button>
            ))}
          </div>
        </div>
        <span className="version-chip">中性 v{versionNo ?? '-'}</span>
      </header>

      {msg && <div className="recalc-msg">{msg}</div>}

      {!baseGrid ? (
        ready && scenarios.length === 0
          ? <div className="empty-hint">暂无基础数据，请前往<b>「设置」</b>页导入表格重建后再使用。</div>
          : <div className="loading">加载中…</div>
      ) : (
        <>
          {metrics && (
            <section className="stats-grid budget-metrics">
              <Metric label="预期总销售量" unit="万台" value={fmt(metrics.qty, 1)} tone="blue" live={!!preview} />
              <Metric label="预期总销售额" unit="万元" value={fmt(metrics.sale, 0)} tone="blue" live={!!preview} />
              <Metric label="研发总预算" unit="万元" value={fmt(metrics.rd, 0)} tone="purple" live={!!preview} />
              <Metric label="营销总预算" unit="万元" value={fmt(metrics.mkt, 0)} tone="orange" live={!!preview} />
              <Metric label="管理总预算" unit="万元" value={fmt(metrics.admin, 0)} tone="green" live={!!preview} />
              <Metric label="总融资额" unit="万元" value={fmt(metrics.financing, 0)} tone="gray" live={!!preview} />
            </section>
          )}

          <Section title="销售设置（万台 / 万元）" tone="sales" rows={BUDGET_SALES_QTY}
            periods={periods} effIn={effIn} groupVal={groupVal} setGroup={setGroup}
            edits={edits} factor={factor}
            top={(
              <div className="budget-params">
                {BUDGET_SALES_PARAMS.map((f) => (
                  <label className="param-item" key={f.key}>
                    <span className="param-label">{f.label}</span>
                    <input type="number" step={f.step} value={salesParams[f.key] ?? ''}
                      onChange={(e) => setSalesParams((p) => ({ ...p, [f.key]: e.target.value }))} />
                  </label>
                ))}
              </div>
            )}
            note="2028 销量由年度目标驱动，逐月编辑可能被目标覆盖；乐观/悲观按销量整体 ±20%。" />

          <Section title="研发预算（万元）" tone="rd" rows={RD}
            periods={periods} effIn={effIn} groupVal={groupVal} setGroup={setGroup} edits={edits} />
          <Section title="营销预算（万元）" tone="mkt" rows={MKT}
            periods={periods} effIn={effIn} groupVal={groupVal} setGroup={setGroup} edits={edits} />
          <Section title="管理预算（万元）" tone="admin" rows={ADMIN}
            periods={periods} effIn={effIn} groupVal={groupVal} setGroup={setGroup} edits={edits} />
          <Section title="投融资（万元）" tone="fin" rows={[{ key: 'cash.financing', label: '到账融资款' }]}
            periods={periods} effIn={effIn} groupVal={groupVal} setGroup={setGroup} edits={edits}
            note="到账融资款按月一次性注入现金，不做年度摊分。" />

          <div className="action-row">
            <span className="hint">{dirty ? '已改动，指标为实时预览；点保存才落版本' : factor !== 1 ? '当前为方案预览' : '未改动'}</span>
            <button className="btn primary" onClick={save} disabled={busy || !dirty}>
              {busy ? '保存中…' : '保存为新版本'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function Metric({ label, value, unit, tone, live }) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}{live && <span className="live-dot" />}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{unit}</div>
    </div>
  )
}

// 一个预算分区：自带年/季/月粒度切换、逐行编辑、实时柱状图
function Section({ title, tone, rows, periods, effIn, groupVal, setGroup, edits, factor = 1, top, note }) {
  const [gran, setGran] = useState('year')
  const groups = useMemo(() => periodGroups(periods, gran), [periods, gran])
  const isQtySec = rows.some((r) => QTY_KEYS.has(r.key))

  const option = useMemo(() => {
    const scaled = (key, months) => {
      const f = QTY_KEYS.has(key) ? factor : 1
      return r2(f * months.reduce((a, p) => a + Number(effIn(key, p) || 0), 0))
    }
    const multi = rows.length > 1
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 2) },
      legend: multi ? { bottom: 0, icon: 'roundRect', itemWidth: 9, itemHeight: 9, textStyle: { fontSize: 10 } } : undefined,
      grid: { left: 40, right: 8, top: 10, bottom: multi ? 30 : 8, containLabel: true },
      xAxis: { type: 'category', data: groups.map((g) => g.label), axisLabel: { fontSize: 9 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f6' } } },
      series: rows.map((r, i) => ({
        name: r.label, type: 'bar', stack: 's',
        itemStyle: { color: CHART_PALETTE[i % CHART_PALETTE.length] },
        data: groups.map((g) => scaled(r.key, g.months)),
      })),
    }
    // 图形随编辑(edits)/粒度/方案实时刷新
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, groups, edits, factor])

  return (
    <section className={`card budget-sec budget-sec--${tone}`}>
      <div className="budget-sec-head">
        <h2>{title}</h2>
        <div className="gran-toggle">
          {[['month', '月'], ['quarter', '季'], ['year', '年']].map(([k, l]) => (
            <button key={k} className={gran === k ? 'on' : ''} onClick={() => setGran(k)}>{l}</button>
          ))}
        </div>
      </div>
      {top}
      {rows.map((r) => (
        <div className="budget-row" key={r.key}>
          <div className="budget-row-label">{r.label}{r.unit ? `（${r.unit}）` : ''}</div>
          <div className={`budget-strip${groups.length <= 6 ? ' budget-strip--wide' : ''}`}>
            {groups.map((g) => (
              <label className="edit-cell" key={g.label}>
                <span>{g.label}</span>
                <input type="number" step={r.key === FINANCING ? '1' : '0.01'} value={groupVal(r.key, g.months)}
                  onChange={(e) => setGroup(r.key, g.months, e.target.value)} />
              </label>
            ))}
          </div>
        </div>
      ))}
      <div className="budget-chart"><Chart option={option} height={isQtySec ? 150 : 160} /></div>
      {note && <p className="hint" style={{ marginTop: 8, marginBottom: 0 }}>{note}</p>}
    </section>
  )
}
