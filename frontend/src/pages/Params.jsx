import React, { useEffect, useMemo, useRef, useState } from 'react'
import { getGrid, gridPeriods, listScenarios, importRebuild, fmt } from '../api'
import { avgCost, priceAverages } from '../calc'

let _uid = 0
const uid = () => `r${++_uid}`
const yuan = (n) => (n == null ? '—' : `${fmt(n, 0)} 元`)

// 售价计算器输入持久化到 localStorage（仅本地、不写库）
const PRICE_KEY = 'params.priceCalc'
const loadPrice = (fallback) => {
  try {
    const saved = JSON.parse(localStorage.getItem(PRICE_KEY) || 'null')
    if (!(saved && saved.packages && saved.channels && saved.lines)) return fallback
    // 顶过存档已用 id，避免新增行 key 冲突
    for (const r of [...saved.packages, ...saved.channels, ...saved.lines]) {
      const n = Number(String(r.id).slice(1))
      if (n > _uid) _uid = n
    }
    return saved
  } catch { return fallback }
}

export default function Params({ user, onImport }) {
  const [scenarioId, setScenarioId] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [grid, setGrid] = useState(null)
  const [ready, setReady] = useState(false)
  const [importMsg, setImportMsg] = useState(null)
  const [importing, setImporting] = useState(false)
  const fetchSeq = useRef(0)
  const importFiles = useRef({ main: null, report: null })

  // 平均售价计算器（仅显示、不写库；输入持久化到 localStorage）
  const init = loadPrice({
    packages: [{ id: uid(), name: '旗舰版', price: '' }],
    channels: [{ id: uid(), name: '天猫', side: 'online', cost: '' }],
    lines: [],
  })
  const [packages, setPackages] = useState(init.packages)
  const [channels, setChannels] = useState(init.channels)
  const [lines, setLines] = useState(init.lines)

  useEffect(() => {
    try { localStorage.setItem(PRICE_KEY, JSON.stringify({ packages, channels, lines })) } catch { /* 忽略 */ }
  }, [packages, channels, lines])

  const loadGrid = async (id) => {
    const seq = ++fetchSeq.current
    try {
      const g = await getGrid(id)
      if (seq === fetchSeq.current) setGrid(g)
    } catch (e) {
      if (seq === fetchSeq.current) setImportMsg(String(e.response?.data?.detail || e.message))
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        const active = scs.find((s) => s.is_active) || scs[0]
        setScenarioId(active ? active.id : null)
      } catch (e) { setImportMsg(String(e.response?.data?.detail || e.message)) }
      finally { setReady(true) }
    })()
  }, [])

  useEffect(() => {
    if (scenarioId != null) loadGrid(scenarioId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId])

  const periods = useMemo(() => gridPeriods(grid), [grid])
  const cost = useMemo(() => avgCost(grid, periods), [grid, periods])
  const price = useMemo(() => priceAverages(packages, channels, lines), [packages, channels, lines])

  // 列表通用增删改：patch 合并到指定 id 的行
  const patch = (setter) => (id, key, val) =>
    setter((rows) => rows.map((r) => (r.id === id ? { ...r, [key]: val } : r)))
  const remove = (setter) => (id) => setter((rows) => rows.filter((r) => r.id !== id))
  const setPkg = patch(setPackages), setChan = patch(setChannels), setLine = patch(setLines)

  const setImportFile = (key) => (e) => {
    importFiles.current[key] = e.target.files?.[0] || null
    setImportMsg(null)
  }

  const doImport = async () => {
    const { main, report } = importFiles.current
    if (!main || !report) {
      setImportMsg('请先选择 主表.xls + 财务报表.xlsx 两个文件')
      return
    }
    if (!window.confirm('将清除并重建 中性/乐观/悲观 三个情景的基础数据（生成新 v1），确定继续？')) return
    try {
      setImporting(true)
      setImportMsg('正在解析并重建…')
      const r = await importRebuild({ main, report })
      setImportMsg(`重建完成：${r.periods[0]}..${r.periods[1]}（${r.period_count} 期，${r.cells} 单元格）` +
                   `${r.clones.length ? `；已克隆 → ${r.clones.map((c) => c.name).join('、')}` : '；未新增克隆'}`)
      importFiles.current = { main: null, report: null }
      const scs = await listScenarios()
      setScenarios(scs)
      const active = scs.find((s) => s.is_active) || scs[0]
      setScenarioId(active ? active.id : null)
      if (onImport) onImport()
    } catch (e) {
      setImportMsg('导入失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="page">
      <header className="app-header">
        <h1>参数计算器</h1>
        <div className="scenario-bar">
          <select value={scenarioId ?? ''} onChange={(e) => setScenarioId(Number(e.target.value))}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
      </header>

      {user && user.role !== 'viewer' && (
        <section className="card import-card">
          <h2>导入表格 · 重建基础数据</h2>
          <p className="hint">上传现金流测算 .xls 主表 + 财务报表__202607期 .xlsx，重建「中性/乐观/悲观」三情景的基础数据（仅管理员/编辑可见）。</p>
          <div className="import-files">
            <label className="import-file">
              <span className="import-file-label">主表（.xls）</span>
              <input type="file" accept=".xls" onChange={setImportFile('main')} />
            </label>
            <label className="import-file">
              <span className="import-file-label">财务报表（.xlsx）</span>
              <input type="file" accept=".xlsx" onChange={setImportFile('report')} />
            </label>
          </div>
          <button className="btn primary" onClick={doImport} disabled={importing}>
            {importing ? '导入中…' : '导入并重建'}
          </button>
          {importMsg && <div className="recalc-msg import-msg">{importMsg}</div>}
        </section>
      )}

      {!ready ? <div className="loading">加载中…</div> : (
        <>
          <section className="card">
            <h2>平均成本计算器</h2>
            <p className="hint">按当前情景全期合计：(研发 + 运营 + 采购 + 推广) ÷ 总销量，得每台平均成本。仅显示，不写库。</p>
            <div className="calc-out-grid">
              <Stat label="研发（万元）" val={fmt(cost.rd, 0)} />
              <Stat label="运营管理（万元）" val={fmt(cost.ops, 0)} />
              <Stat label="推广/营销（万元）" val={fmt(cost.promo, 0)} />
              <Stat label="采购付款（万元）" val={fmt(cost.purchase, 0)} />
              <Stat label="总销量（万台）" val={fmt(cost.qty, 1)} />
              <Stat label="成本合计（万元）" val={fmt(cost.totalCost, 0)} />
              <Stat label="平均成本" val={yuan(cost.avg)} big />
            </div>
          </section>

          <section className="card">
            <h2>平均售价计算器</h2>
            <p className="hint">包装决定定价、渠道决定渠道成本（占定价%）与线上/线下归属；每层净价 = (Σ定价×量 − Σ定价×成本%×量) ÷ Σ量。仅显示。</p>

            <div className="calc-sub-head">
              <h3>包装定价（元/台）</h3>
              <button className="link-btn" onClick={() => setPackages((r) => [...r, { id: uid(), name: '', price: '' }])}>+ 添加包装</button>
            </div>
            {packages.map((p) => (
              <div className="calc-row" key={p.id}>
                <input className="calc-name" placeholder="包装名（如 典藏版）" value={p.name}
                  onChange={(e) => setPkg(p.id, 'name', e.target.value)} />
                <input type="number" placeholder="定价" value={p.price}
                  onChange={(e) => setPkg(p.id, 'price', e.target.value)} />
                <button className="calc-del" onClick={() => remove(setPackages)(p.id)}>×</button>
              </div>
            ))}

            <div className="calc-sub-head">
              <h3>渠道（渠道成本 % / 占定价）</h3>
              <button className="link-btn" onClick={() => setChannels((r) => [...r, { id: uid(), name: '', side: 'online', cost: '' }])}>+ 添加渠道</button>
            </div>
            {channels.map((c) => (
              <div className="calc-row" key={c.id}>
                <input className="calc-name" placeholder="渠道名（如 京东）" value={c.name}
                  onChange={(e) => setChan(c.id, 'name', e.target.value)} />
                <select value={c.side} onChange={(e) => setChan(c.id, 'side', e.target.value)}>
                  <option value="online">线上</option>
                  <option value="offline">线下</option>
                </select>
                <span className="calc-pct">
                  <input type="number" placeholder="成本" value={c.cost}
                    onChange={(e) => setChan(c.id, 'cost', e.target.value)} />
                  <em>%</em>
                </span>
                <button className="calc-del" onClick={() => remove(setChannels)(c.id)}>×</button>
              </div>
            ))}

            <div className="calc-sub-head">
              <h3>销售明细（渠道 × 包装 × 数量）</h3>
              <button className="link-btn" onClick={() => setLines((r) => [...r, { id: uid(), channelId: channels[0]?.id ?? '', packageId: packages[0]?.id ?? '', qty: '' }])}>+ 添加明细</button>
            </div>
            {lines.map((ln) => (
              <div className="calc-row" key={ln.id}>
                <select value={ln.channelId} onChange={(e) => setLine(ln.id, 'channelId', e.target.value)}>
                  {channels.map((c) => <option key={c.id} value={c.id}>{c.name || '(未命名渠道)'}</option>)}
                </select>
                <select value={ln.packageId} onChange={(e) => setLine(ln.id, 'packageId', e.target.value)}>
                  {packages.map((p) => <option key={p.id} value={p.id}>{p.name || '(未命名包装)'}</option>)}
                </select>
                <input type="number" placeholder="数量" value={ln.qty}
                  onChange={(e) => setLine(ln.id, 'qty', e.target.value)} />
                <button className="calc-del" onClick={() => remove(setLines)(ln.id)}>×</button>
              </div>
            ))}

            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="data-table data-table--full">
                <thead><tr><th>层级</th><th>销量</th><th>毛均价</th><th>净售价</th></tr></thead>
                <tbody>
                  {price.byChannel.map((b) => (
                    <tr key={b.name + b.side}>
                      <td className="row-name">{b.name}（{b.side === 'online' ? '线上' : '线下'}）</td>
                      <td>{fmt(b.qty, 0)}</td><td>{yuan(b.gross)}</td><td>{yuan(b.net)}</td>
                    </tr>
                  ))}
                  <tr><td className="row-name"><b>线上汇总</b></td><td>{fmt(price.online.qty, 0)}</td><td>{yuan(price.online.gross)}</td><td>{yuan(price.online.net)}</td></tr>
                  <tr><td className="row-name"><b>线下汇总</b></td><td>{fmt(price.offline.qty, 0)}</td><td>{yuan(price.offline.gross)}</td><td>{yuan(price.offline.net)}</td></tr>
                  <tr><td className="row-name"><b>整体</b></td><td>{fmt(price.overall.qty, 0)}</td><td>{yuan(price.overall.gross)}</td><td>{yuan(price.overall.net)}</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

function Stat({ label, val, big }) {
  return (
    <div className={`calc-stat${big ? ' calc-stat--big' : ''}`}>
      <span className="calc-stat-label">{label}</span>
      <b>{val}</b>
    </div>
  )
}
