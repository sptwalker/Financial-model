import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import { fmt, getGrid, getVersions, gridPeriods, listScenarios, previewRecalc,
  releaseVersion, unreleaseVersion } from '../api'
import { ROW_GROUPS, BUDGET_COST_GROUPS, rowInfo, CASH_COLORS } from '../rows'
import { cellDelta } from '../diff'
import { detectAlerts, summarizeAlerts } from '../alerts'
import { TRIAL_KEY } from './Budget'

const r2 = (n) => Math.round(n * 100) / 100
const MIN_CASH_KEY = 'fm_min_cash'   // 最低现金安全水位阈值（万元），本地持久化

// 成本构成四大类（研发/营销/运营管理来自预算页分组，追加采购付款）
const PURCHASE_GROUP = { name: '采购', rows: [
  { key: 'purchase.main', label: '整机采购付款' },
  { key: 'purchase.accessory', label: '配件采购付款' },
] }
const COST_GROUPS = [...BUDGET_COST_GROUPS, PURCHASE_GROUP]
const CAT_COLORS = ['#4a72a8', '#a97f38', '#3f8f6e', '#b0685b']  // 降饱和加深，白字清晰
// 桑基收入/成本节点键
const SALE_NODES = [
  ['线上销售', 'sale.online.amount'], ['线下销售', 'sale.offline.amount'],
  ['配件收入', 'sale.accessory.amount'], ['订阅收入', 'sale.subscription.amount'],
]
const NODE_COLOR = {
  线上销售: '#4f8cff', 线下销售: '#5ad8a6', 配件收入: '#f6bd16', 订阅收入: '#9254de',
  总收入: '#1f2d3d', 研发: '#4f8cff', 营销: '#f6bd16', 运营管理: '#00b578', 采购: '#e86452',
  经营结余: '#13c2a3', 资金缺口: '#f54e5e',
}

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
  const [cmpVersionNo, setCmpVersionNo] = useState(null)  // 复盘对比版本（null=不对比）
  const [cmpGrid, setCmpGrid] = useState(null)
  const [grid, setGrid] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [recalcMsg, setRecalcMsg] = useState(null)
  const [showTable, setShowTable] = useState(false)
  const [year, setYear] = useState(null)       // 成本构成/桑基图当前年份（null=默认首年）
  const [trial, setTrial] = useState(false)   // 当前网格是否为预算页「试算」预览（未保存）
  const [nonce, setNonce] = useState(0)        // 清除试算后强制重载
  const [minCash, setMinCash] = useState(() => {
    const v = Number(localStorage.getItem(MIN_CASH_KEY))
    return Number.isFinite(v) ? v : 0
  })
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
    let tp = null
    try {
      const t = JSON.parse(localStorage.getItem(TRIAL_KEY) || 'null')
      tp = t?.scenarios?.[scenarioId] || null
    } catch { tp = null }
    const req = tp
      ? previewRecalc(scenarioId, tp).then((r) => ({ scenario_id: scenarioId, version_no: versionNo, cells: r.cells }))
      : getGrid(scenarioId, versionNo)
    req
      .then((g) => { if (!stale) { setGrid(g); setTrial(!!tp) } })
      .catch((e) => !stale && setError(String(e.response?.data?.detail || e.message)))
      .finally(() => !stale && setLoading(false))
    return () => { stale = true }
  }, [scenarioId, versionNo, nonce])

  // 复盘对比版本的网格（只读快照，不受试算影响）
  useEffect(() => {
    if (!scenarioId || cmpVersionNo === null || cmpVersionNo === versionNo) {
      setCmpGrid(null)
      return
    }
    let stale = false
    getGrid(scenarioId, cmpVersionNo)
      .then((g) => { if (!stale) setCmpGrid(g) })
      .catch(() => !stale && setCmpGrid(null))
    return () => { stale = true }
  }, [scenarioId, cmpVersionNo, versionNo])

  const clearTrial = () => { localStorage.removeItem(TRIAL_KEY); setNonce((n) => n + 1) }

  const periods = useMemo(
    () => gridPeriods(grid),
    [grid]
  )

  const stats = useMemo(() => {
    if (!grid) return null
    const statsOf = (g) => {
      const sum = (key) => periods.reduce(
        (a, p) => a + Number(g.cells[key]?.[p]?.value ?? 0), 0)
      const last = (key) => Number(g.cells[key]?.[periods[periods.length - 1]]?.value ?? 0)
      return {
        sale: sum('sale.total.amount'),
        collect: sum('collect.total'),
        expense: sum('exp.total'),
        purchase: sum('purchase.total'),
        cashClose: last('cash.closing'),
        cashOpen: Number(g.cells['cash.opening']?.[periods[0]]?.value ?? 0),
      }
    }
    const cur = statsOf(grid)
    return cmpGrid ? { ...cur, cmp: statsOf(cmpGrid) } : cur
  }, [grid, cmpGrid, periods])

  // 现金流预警：资金缺口月 + 现金水位低于阈值月
  const alerts = useMemo(() => detectAlerts(grid, periods, minCash), [grid, periods, minCash])
  const alertSum = useMemo(() => summarizeAlerts(alerts), [alerts])
  const setThreshold = (v) => {
    const n = Number(v)
    const safe = Number.isFinite(n) ? n : 0
    setMinCash(safe)
    localStorage.setItem(MIN_CASH_KEY, String(safe))
  }

  const salesOption = useMemo(() => {
    if (!grid) return {}
    const keys = ['sale.online.amount', 'sale.offline.amount',
      'sale.accessory.amount', 'sale.subscription.amount', 'sale.valueadd.amount']
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

  // 成本构成/桑基图：年份列表与当前年
  const years = useMemo(() => [...new Set(periods.map((p) => p.slice(0, 4)))], [periods])
  const activeYear = year || years[0]
  // 某行在指定年的合计（useCallback：作为下方 treemap/sankey 的 useMemo 依赖，避免每次都失效）
  const ysum = useCallback((key, y) => periods.reduce(
    (a, p) => (p.slice(0, 4) === y ? a + Number(grid?.cells[key]?.[p]?.value ?? 0) : a), 0),
    [grid, periods])

  // 矩形树状图：四大类 → 明细行，按当前年合计
  const treemapOption = useMemo(() => {
    if (!grid || !activeYear) return {}
    const data = COST_GROUPS.map((cat, i) => ({
      name: cat.name,
      itemStyle: { color: CAT_COLORS[i % CAT_COLORS.length] },
      children: cat.rows
        .map((r) => ({ name: r.label, value: r2(ysum(r.key, activeYear)) }))
        .filter((c) => c.value > 0),
    })).filter((c) => c.children.length)
    return {
      tooltip: { formatter: (info) => `${info.name}：${fmt(info.value, 0)} 万元` },
      series: [{
        type: 'treemap', roam: false, nodeClick: false, width: '100%', height: '100%',
        top: 4, bottom: 4, left: 4, right: 4,
        breadcrumb: { show: false },
        label: { fontSize: 11, color: '#fff', textBorderColor: 'rgba(0,0,0,0.4)', textBorderWidth: 2,
          formatter: (i) => `${i.name}\n${fmt(i.value, 0)}` },
        upperLabel: { show: true, height: 18, fontSize: 11, color: '#fff' },
        levels: [
          { itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 } },
          { itemStyle: { borderColor: '#fff', borderWidth: 1, gapWidth: 1 }, colorSaturation: [0.2, 0.4] },
        ],
        data,
      }],
    }
  }, [grid, activeYear, ysum])

  // 桑基图（权责制）：四类销售额 → 总收入 → 研发/营销/运营管理/采购 + 经营结余
  const sankeyOption = useMemo(() => {
    if (!grid || !activeYear) return {}
    const total = SALE_NODES.reduce((a, [, k]) => a + ysum(k, activeYear), 0)
    const catVal = (cat) => cat.rows.reduce((a, r) => a + ysum(r.key, activeYear), 0)
    const cats = COST_GROUPS.map((c) => [c.name, catVal(c)])
    const balance = total - cats.reduce((a, [, v]) => a + v, 0)
    const links = []
    SALE_NODES.forEach(([n, k]) => { const v = ysum(k, activeYear); if (v > 0) links.push({ source: n, target: '总收入', value: r2(v) }) })
    cats.forEach(([n, v]) => { if (v > 0) links.push({ source: '总收入', target: n, value: r2(v) }) })
    if (balance > 0) links.push({ source: '总收入', target: '经营结余', value: r2(balance) })
    else if (balance < 0) links.push({ source: '资金缺口', target: '总收入', value: r2(-balance) })
    const names = [...new Set(links.flatMap((l) => [l.source, l.target]))]
    const nodes = names.map((n) => ({ name: n, itemStyle: { color: NODE_COLOR[n] || '#8c8c8c' } }))
    return {
      tooltip: { trigger: 'item', formatter: (info) => (info.dataType === 'edge'
        ? `${info.data.source} → ${info.data.target}：${fmt(info.data.value, 0)} 万`
        : `${info.name}`) },
      series: [{
        type: 'sankey', top: 10, bottom: 10, left: 8, right: 90,
        emphasis: { focus: 'adjacency' },
        nodeWidth: 14, nodeGap: 10,
        label: { fontSize: 11 },
        lineStyle: { color: 'gradient', opacity: 0.45 },
        data: nodes, links,
      }],
    }
  }, [grid, activeYear, ysum])

  async function toggleRelease(on) {
    try {
      setRecalcMsg(on ? '开启保护…' : '取消保护…')
      const fn = on ? releaseVersion : unreleaseVersion
      await fn(scenarioId, versionNo)
      const { versions: vs } = await getVersions(scenarioId)
      setVersions(vs)
      setRecalcMsg(on ? `已开启删除保护 v${versionNo}` : `已取消删除保护 v${versionNo}`)
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

  const isAdmin = user?.role === 'admin'
  const currentVersion = versions.find((v) => v.version_no === versionNo)
  const isReleased = !!currentVersion?.released_at

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
            <select className="cmp-select" title="选一个历史版本做复盘对比"
              value={cmpVersionNo ?? ''}
              onChange={(e) => setCmpVersionNo(e.target.value === '' ? null : Number(e.target.value))}>
              <option value="">不对比</option>
              {(versions || []).filter((v) => v.version_no !== versionNo).map((v) => (
                <option key={v.version_no} value={v.version_no}>对比 v{v.version_no} · {v.comment}</option>
              ))}
            </select>
            <label className="lock-toggle" title="勾选后此版本存档受删除保护，需取消勾选才能删除">
              <input type="checkbox" checked={isReleased}
                disabled={!isAdmin || versionNo == null}
                onChange={(e) => toggleRelease(e.target.checked)} />
              <span>{isReleased ? '🔒 ' : ''}删除保护</span>
            </label>
          </div>
        </div>
        <div className="user-box">
          <span className="avatar">{user?.name?.[0] || '?'}</span>
          <button className="link-btn" onClick={onLogout}>退出</button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {trial && (
        <div className="recalc-msg">
          试算预览（未保存，来自预算页当前数值）
          <button className="link-btn" onClick={clearTrial} style={{ marginLeft: 8 }}>清除试算，查看已保存版本</button>
        </div>
      )}
      {recalcMsg && <div className="recalc-msg">{recalcMsg}</div>}
      {cmpGrid && (
        <div className="recalc-msg">
          复盘对比中：v{versionNo} vs v{cmpVersionNo}（卡片与明细表显示 Δ = 本版 − 对比版，红升绿降）
          <button className="link-btn" onClick={() => setCmpVersionNo(null)} style={{ marginLeft: 8 }}>取消对比</button>
        </div>
      )}

      {loading && !grid ? (
        <div className="loading">加载中…</div>
      ) : grid && stats ? (
        <>
          <section className="stats-grid">
            <Stat label="累计销售额" value={fmt(stats.sale, 0)} sub="万元" tone="blue" delta={stats.cmp && stats.sale - stats.cmp.sale} />
            <Stat label="累计回款" value={fmt(stats.collect, 0)} sub="万元" tone="green" delta={stats.cmp && stats.collect - stats.cmp.collect} />
            <Stat label="累计费用" value={fmt(stats.expense, 0)} sub="万元" tone="orange" delta={stats.cmp && stats.expense - stats.cmp.expense} />
            <Stat label="累计采购" value={fmt(stats.purchase, 0)} sub="万元" tone="red" delta={stats.cmp && stats.purchase - stats.cmp.purchase} />
            <Stat label="期初现金" value={fmt(stats.cashOpen, 0)} sub="万元" tone="gray" delta={stats.cmp && stats.cashOpen - stats.cmp.cashOpen} />
            <Stat label="期末现金" value={fmt(stats.cashClose, 0)} sub="万元" tone="gray" delta={stats.cmp && stats.cashClose - stats.cmp.cashClose} />
          </section>

          <section className={`card alert-card ${alertSum.total ? 'has-alert' : 'ok'}`}>
            <div className="budget-sec-head">
              <h2>{alertSum.total ? '⚠️ 现金流预警' : '✅ 现金流健康'}</h2>
              <label className="alert-thresh" title="期末现金低于此水位即预警">
                最低现金水位
                <input type="number" step="10" value={minCash}
                  onChange={(e) => setThreshold(e.target.value)} />
                <span>万元</span>
              </label>
            </div>
            {alertSum.total ? (
              <>
                {alertSum.gap && (
                  <p className="alert-line gap">
                    资金缺口 <b>{alertSum.gap.count}</b> 个月，最早 {alertSum.gap.first.slice(2)}，
                    最深 {fmt(alertSum.gap.worst.value, 0)} 万（{alertSum.gap.worst.period.slice(2)}）
                  </p>
                )}
                {alertSum.lowcash && (
                  <p className="alert-line lowcash">
                    现金低于 {fmt(minCash, 0)} 万 <b>{alertSum.lowcash.count}</b> 个月，最早 {alertSum.lowcash.first.slice(2)}，
                    最低 {fmt(alertSum.lowcash.worst.value, 0)} 万（{alertSum.lowcash.worst.period.slice(2)}）
                  </p>
                )}
                <div className="alert-chips">
                  {alerts.map((a, i) => (
                    <span key={i} className={`alert-chip ${a.type}`}
                      title={a.type === 'gap' ? '资金缺口' : '现金低于水位'}>
                      {a.period.slice(2)} {a.type === 'gap' ? '缺口' : '低现金'} {fmt(a.value, 0)}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="hint">全期无资金缺口，期末现金均不低于 {fmt(minCash, 0)} 万元安全水位。</p>
            )}
          </section>

          <section className="card">
            <h2>现金流水</h2>
            <Chart option={cashOption} height={300} />
          </section>

          <section className="card">
            <h2>销售额构成</h2>
            <Chart option={salesOption} height={280} />
          </section>

          <section className="card">
            <div className="budget-sec-head">
              <h2>成本构成</h2>
              <div className="gran-toggle">
                {years.map((y) => (
                  <button key={y} className={activeYear === y ? 'on' : ''} onClick={() => setYear(y)}>{y.slice(2)}年</button>
                ))}
              </div>
            </div>
            <p className="hint">按 {activeYear} 年合计；矩形树状图为成本构成（研发/营销/运营管理/采购），桑基图为收入→支出流向（权责制）。</p>
            <h3 className="sub-h">成本构成（万元）</h3>
            <Chart option={treemapOption} height={300} notMerge />
            <h3 className="sub-h">收入支出流向（万元）</h3>
            <Chart option={sankeyOption} height={340} notMerge />
          </section>

            <button className="btn primary recalc-btn" onClick={() => setShowTable(true)}>
              查看全部月份数据
            </button>
        </>
      ) : null}

      <footer className="app-footer">
        <span>v{versionNo ?? '-'}</span>
        <span>{periods.length ? `${periods[0]} ~ ${periods[periods.length - 1]}` : ''}</span>
      </footer>

      {showTable && (
        <FullTable periods={periods} grid={grid} cmpGrid={cmpGrid}
          versionNo={versionNo} cmpVersionNo={cmpVersionNo} onClose={() => setShowTable(false)} />
      )}
    </div>
  )
}

function Stat({ label, value, sub, tone, delta }) {
  // delta：与对比版本之差（本版−对比版）。费用/采购升为红、其余按数值方向着色仅表示增减
  const show = typeof delta === 'number' && Math.abs(delta) >= 0.5
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{sub}</div>
      {show && (
        <div className={`stat-delta ${delta > 0 ? 'up' : 'down'}`}>
          {delta > 0 ? '▲' : '▼'} {fmt(Math.abs(delta), 0)}
        </div>
      )}
    </div>
  )
}

function FullTable({ periods, grid, cmpGrid, versionNo, cmpVersionNo, onClose }) {
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>全部指标 · 全部月份（万元）{cmpGrid ? ` · 复盘 v${versionNo} vs v${cmpVersionNo}` : ''}</strong>
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
                  {periods.map((p) => {
                    if (!cmpGrid) return <td key={p}>{fmt(grid.cells[r.key]?.[p]?.value, 2)}</td>
                    const d = cellDelta(grid, cmpGrid, r.key, p)
                    return (
                      <td key={p} className={d.changed ? 'cell-changed' : ''}
                        title={d.changed ? `本版 ${fmt(d.a, 2)} · 对比 ${fmt(d.b, 2)}` : ''}>
                        {fmt(d.a, 2)}
                        {d.changed && <span className={`cell-delta ${d.delta > 0 ? 'up' : 'down'}`}>
                          {d.delta > 0 ? '+' : ''}{fmt(d.delta, 2)}
                        </span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
