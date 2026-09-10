import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Chart from '../components/Chart'
import { fmt, getGrid, getVersions, gridPeriods, listScenarios, previewRecalc, recalc } from '../api'
import { BUDGET_COST_GROUPS, BUDGET_SALES_QTY, BUDGET_SALES_PARAMS } from '../rows'

const r2 = (n) => Math.round(n * 100) / 100                // 统一最多两位小数
export const TRIAL_KEY = 'budget_trial'                    // 试算暂存：看板据此预览未保存的当前页数值
const DRAFT_KEY = 'budget_draft'                           // 预算页编辑草稿：切页/试算往返不丢失输入

function loadDraft() {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null') }
  catch { return null }
}

// 默认版本名 = 日期+时间+版本号（用户可改）
function defaultName(ver) {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())} v${ver}`
}
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
  const [saveName, setSaveName] = useState('') // 版本名称（默认 日期+时间+版本号，可改）
  const fetchSeq = useRef(0)
  const timer = useRef(null)
  const navigate = useNavigate()

  const load = async (id) => {
    const seq = ++fetchSeq.current
    try {
      const [g, { versions, params }] = await Promise.all([getGrid(id), getVersions(id)])
      if (seq !== fetchSeq.current) return
      setBaseGrid(g)
      const vno = versions[0]?.version_no ?? null
      setVersionNo(vno)
      const sp = {}
      for (const f of BUDGET_SALES_PARAMS) if (params?.[f.key] != null) sp[f.key] = params[f.key]
      setBaseParams(sp)
      // 恢复草稿：切页/试算往返保留当前输入；无草稿则回落基线
      const draft = loadDraft()
      setSalesParams(draft?.salesParams ?? sp)
      setEdits(draft?.edits ?? {})
      setFactor(draft?.factor ?? 1)
      setSaveName(draft?.saveName ?? defaultName((vno ?? 0) + 1))
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
    return months.length === 1 ? effIn(row, months[0]) : r2(sum)
  }
  const setGroup = (row, months, v) => {
    const total = Number(v || 0)
    const n = months.length
    // 均摊时余数归最后一月，保证求和=输入值（12 个月不整除也无小数漂移）
    const per = n > 1 ? r2(total / n) : total
    setEdits((prev) => {
      const next = { ...prev, [row]: { ...(prev[row] || {}) } }
      months.forEach((p, i) => {
        next[row][p] = String(i === n - 1 ? r2(total - per * (n - 1)) : per)
      })
      return next
    })
  }

  const paramsPayload = (fac = 1) => {
    const changed = {}
    for (const f of BUDGET_SALES_PARAMS) {
      if (String(salesParams[f.key] ?? '') !== String(baseParams[f.key] ?? ''))
        changed[f.key] = salesParams[f.key]
    }
    // 情景销量系数走引擎 qty_scale（对最终销量整体缩放），不改 qty 输入行
    if (fac !== 1) changed.qty_scale = fac
    return Object.keys(changed).length ? changed : undefined
  }
  // 输入覆盖：仅中性编辑增量；情景差异由 params.qty_scale 表达，不覆写 qty 行
  const inputsPayload = () => {
    const out = {}
    for (const row of Object.keys(edits)) {
      out[row] = {}
      for (const p of Object.keys(edits[row])) {
        const v = edits[row][p]
        out[row][p] = v === '' || v == null ? '0' : String(v)
      }
    }
    return Object.keys(out).length ? out : undefined
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
        const p = await previewRecalc(neutralId, { params: paramsPayload(factor), inputs: inputsPayload() })
        setPreview(p)
      } catch (e) {
        setMsg('预览失败：' + String(e.response?.data?.detail || e.message))
      }
    }, 400)
    return () => clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edits, salesParams, factor, neutralId, baseGrid])

  // 持久化编辑草稿（切页/试算往返不丢失）；加载完成后才写，避免初始空态覆盖草稿
  useEffect(() => {
    if (!baseGrid) return
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ edits, salesParams, factor, saveName }))
  }, [edits, salesParams, factor, saveName, baseGrid])

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
      const name = saveName.trim() || defaultName((versionNo ?? 0) + 1)
      const byName = (n) => scenarios.find((s) => s.name === n)
      let last = null
      for (const s of SCENARIOS) {
        const sc = byName(s.name)
        if (!sc) continue
        const r = await recalc(sc.id, {
          params: paramsPayload(s.factor), inputs: inputsPayload(), comment: `${name} · ${s.name}`,
        })
        if (s.factor === 1) last = r
      }
      localStorage.removeItem(TRIAL_KEY)   // 已落版本，清除试算暂存
      localStorage.removeItem(DRAFT_KEY)   // 已落版本，清除编辑草稿
      setMsg(`已保存「${name}」：中性 v${last?.version_no}（乐观/悲观按 ±20% 同步）`)
      await load(neutralId)
    } catch (e) {
      setMsg('保存失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setBusy(false)
    }
  }

  // 试算：按当前页数值为三情景各建预览载荷，暂存后跳看板（不落版本）
  const trial = () => {
    const byName = (n) => scenarios.find((s) => s.name === n)
    const scen = {}
    for (const s of SCENARIOS) {
      const sc = byName(s.name)
      if (sc) scen[sc.id] = { params: paramsPayload(s.factor), inputs: inputsPayload() }
    }
    localStorage.setItem(TRIAL_KEY, JSON.stringify({ scenarios: scen }))
    navigate('/')
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
                    <NumInput value={salesParams[f.key] ?? ''}
                      onCommit={(v) => setSalesParams((p) => ({ ...p, [f.key]: v }))} />
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
          <FinancingSection periods={periods} effIn={effIn} setEdits={setEdits} baseGrid={baseGrid} />

          <div className="action-row">
            <span className="hint">{dirty ? '已改动，指标为实时预览；试算看看板，保存才落版本' : factor !== 1 ? '当前为方案预览' : '未改动'}</span>
            <input className="save-name" type="text" value={saveName} placeholder="版本名称"
              onChange={(e) => setSaveName(e.target.value)} />
            <button className="btn" onClick={trial} disabled={busy}>试算</button>
            <button className="btn primary" onClick={save} disabled={busy || !dirty}>
              {busy ? '保存中…' : '保存'}
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

// 只留数字与一个小数点（金额输入清洗；负号无意义故不允许）
function cleanNum(s) {
  s = String(s).replace(/[^\d.]/g, '')
  const i = s.indexOf('.')
  return i < 0 ? s : s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, '')
}

// 金额输入框：编辑时回显所敲字符（本地 text），失焦同步回派生值；
// type=text + inputMode=decimal —— 移动端弹数字键盘，且不会吞掉中间态 "1."
function NumInput({ value, placeholder = '0', onCommit }) {
  const norm = value === '' || value == null || Number(value) === 0 ? '' : String(value)
  const [text, setText] = useState(norm)
  const [editing, setEditing] = useState(false)
  useEffect(() => { if (!editing) setText(norm) }, [norm, editing])
  return (
    <input type="text" inputMode="decimal" placeholder={placeholder}
      value={editing ? text : norm}
      onFocus={() => setEditing(true)}
      onBlur={() => setEditing(false)}
      onChange={(e) => { const v = cleanNum(e.target.value); setText(v); onCommit(v) }} />
  )
}

// 投融资：按年录入，每年指定一个到账月份（默认 12 月），一次性注入不摊分
function FinancingSection({ periods, effIn, setEdits, baseGrid }) {
  const years = useMemo(() => {
    const m = {}
    for (const p of periods) {
      const [y, mo] = p.split('-')
      ;(m[y] = m[y] || []).push(mo)
    }
    return Object.entries(m).map(([y, months]) => ({ y, months }))
  }, [periods])

  const [monthByYear, setMonthByYear] = useState({})

  const yearAmount = (y, months) =>
    months.reduce((a, mo) => a + Number(effIn(FINANCING, `${y}-${mo}`) || 0), 0)

  // 写入某年：所选月=整额，其余月清零（不摊分，往返无损）
  const setFin = (y, months, month, amount) => {
    const total = String(Math.round(Number(amount || 0)))
    setEdits((prev) => {
      const next = { ...prev, [FINANCING]: { ...(prev[FINANCING] || {}) } }
      for (const mo of months) next[FINANCING][`${y}-${mo}`] = mo === month ? total : '0'
      return next
    })
  }

  // 各年到账月份统一默认 12 月；不落在 12 月的历史数据（摊分或其它月）收敛到 12 月并标为已改动
  useEffect(() => {
    if (!baseGrid) return
    const init = {}
    const toDec = []
    for (const { y, months } of years) {
      init[y] = '12'
      const nz = months.filter((mo) => Number(effIn(FINANCING, `${y}-${mo}`) || 0) !== 0)
      const amt = yearAmount(y, months)
      if (amt !== 0 && !(nz.length === 1 && nz[0] === '12')) toDec.push({ y, months, amt })
    }
    setMonthByYear(init)
    for (const { y, months, amt } of toDec) setFin(y, months, '12', amt)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years, baseGrid])

  const option = useMemo(() => ({
    tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 0) },
    grid: { left: 40, right: 8, top: 10, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: years.map((g) => `${g.y.slice(2)}年`), axisLabel: { fontSize: 9 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f6' } } },
    series: [{
      name: '到账融资款', type: 'bar', itemStyle: { color: '#9254de' },
      data: years.map((g) => Math.round(yearAmount(g.y, g.months))),
    }],
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [years, baseGrid, monthByYear, effIn])

  return (
    <section className="card budget-sec budget-sec--fin">
      <div className="budget-sec-head"><h2>投融资（万元）</h2></div>
      <div className="fin-year-row">
        {years.map(({ y, months }) => (
          <div className="fin-year" key={y}>
            <span className="fin-year-label">{y}年</span>
            <NumInput value={Math.round(yearAmount(y, months)) || ''} placeholder="金额"
              onCommit={(v) => setFin(y, months, monthByYear[y] || '12', v)} />
            <select value={monthByYear[y] || '12'}
              onChange={(e) => {
                setMonthByYear((m) => ({ ...m, [y]: e.target.value }))
                setFin(y, months, e.target.value, yearAmount(y, months))
              }}>
              {months.map((mo) => <option key={mo} value={mo}>{Number(mo)}月</option>)}
            </select>
          </div>
        ))}
      </div>
      <div className="budget-chart"><Chart option={option} height={160} /></div>
      <p className="hint" style={{ marginTop: 8, marginBottom: 0 }}>
        每年融资款在指定月份一次性注入现金（默认 12 月），不做年度摊分。
      </p>
    </section>
  )
}

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
                <NumInput value={groupVal(r.key, g.months)}
                  onCommit={(v) => setGroup(r.key, g.months, v)} />
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
