import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import {
  applyForecast, fmt, importActuals, listActuals, listScenarios,
  runForecast, upsertActuals,
} from '../api'
import { FORECAST_METHODS, SCENARIO_COLORS } from '../rows'

// 预测工作台（阶段 3 · 移动/桌面分流）：
// 手机端以输出+简单调节为主；导入导出、回测明细、三情景、缩放年度目标下沉桌面端（.pc-only）。
// 2026-07 为已发生月（报表实际≈0 台），引擎轴 2026-08 起；历史 1-2 个月时走计划锚定并明示"数据不足"。

const DEFAULT_HORIZON = ['2026-08', '2027-12']

function nextMonth(p) {
  const [y, m] = p.split('-').map(Number)
  const d = new Date(y, m, 1) // m 即下月的 0 号 → 简单进位
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function methodMeta(method) {
  return FORECAST_METHODS.find((m) => m.key === method) || null
}

// 小图标（描边风，随 currentColor）
const Icon = ({ d, w = 15 }) => (
  <svg viewBox="0 0 24 24" width={w} height={w} fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
)
const IPlay = <Icon d={<path d="M5 3l14 9-14 9V3z" />} />
const ICheck = <Icon d={<path d="M20 6L9 17l-5-5" />} />
const IPlus = <Icon d={<path d="M12 5v14M5 12h14" />} />
const IUp = <Icon d={<path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14" />} />
const IWarn = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path
    d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z" /></svg>

export default function Forecast({ user }) {
  const canEdit = user && (user.role === 'admin' || user.role === 'editor')

  const [scenarios, setScenarios] = useState([])
  const [scenarioId, setScenarioId] = useState(null)
  const [actuals, setActuals] = useState({ actuals: [], n_effective: 0, total_by_period: {} })
  const [run, setRun] = useState(null)
  const [method, setMethod] = useState('')            // '' = 自动
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON)
  const [scale, setScale] = useState({ 2028: '', 2029: '' })  // 缩放年度目标（桌面端复杂参数）
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState(null)                // run 反馈
  const [applyMsg, setApplyMsg] = useState(null)      // apply 反馈
  const [err, setErr] = useState(null)
  const [showEntry, setShowEntry] = useState(false)
  const [triple, setTriple] = useState(true)          // 三情景开关（桌面端）
  const fileRef = useRef(null)

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        setScenarioId((scs.find((s) => s.is_active) || scs[0] || {}).id ?? null)
      } catch (e) {
        setErr(String(e.response?.data?.detail || e.message))
      }
    })()
  }, [])

  useEffect(() => {
    (async () => {
      try {
        setActuals(await listActuals())
      } catch (e) {
        setErr(String(e.response?.data?.detail || e.message))
      }
    })()
  }, [])

  // 切换情景后旧预测结果失效（预测是情景私有的）
  useEffect(() => { setRun(null); setApplyMsg(null) }, [scenarioId])

  async function refreshActuals() {
    setActuals(await listActuals())
  }

  function refreshAfterImport() {
    setShowEntry(false)
    refreshActuals().catch((e) => setErr(String(e.response?.data?.detail || e.message)))
  }

  async function onRun() {
    setErr(null)
    setRun(null)
    setMsg(null)
    setRunning(true)
    try {
      const scaleTargets = {}
      for (const y of [2028, 2029]) if (scale[y] !== '') scaleTargets[y] = String(scale[y])
      const res = await runForecast({
        scenario_id: scenarioId,
        method: method || null,
        horizon,
        scale_targets: Object.keys(scaleTargets).length ? scaleTargets : null,
      })
      setRun(res)
      setMsg(`${res.method}（有效历史 ${res.n_actual} 个月）· 线上占比 ${fmt(Number(res.ratio_online) * 100, 1)}%`)
    } catch (e) {
      setErr(String(e.response?.data?.detail || e.message))
    } finally {
      setRunning(false)
    }
  }

  // allowTriple=false（手机）→ 只回填中性单版本；桌面按 triple 勾选
  async function onApply(allowTriple = true) {
    if (!run || !run.series.length) return
    const ratio = Number(run.ratio_online)
    // 渠道拆分：yhat/lower/upper 都是总量口径，按线上占比 ratio 拆成 online/offline
    const split = (totalOf) => run.series.map((p) => ({
      period: p.period,
      online: fmt(Number(totalOf(p)) * ratio, 4),
      offline: fmt(Number(totalOf(p)) * (1 - ratio), 4),
    }))
    const withCI = allowTriple && triple && run.data_sufficient
    const t = withCI ? '将生成悲观/中性/乐观三个版本（覆盖' + horizon[0] + '~' + horizon[1] + '），' : ''
    if (!window.confirm(t + '接受预测并回填销量，重算现金流？')) return
    setApplyMsg(null)
    setErr(null)
    try {
      const out = await applyForecast({
        scenario_id: scenarioId,
        method: run.method,
        base: split((p) => p.yhat),
        lower: withCI ? split((p) => p.lower) : null,
        upper: withCI ? split((p) => p.upper) : null,
        comment: `预测(${run.method})`,
      })
      const parts = [`中性 v${out.base_version}`]
      if (out.lower_version) parts.unshift(`悲观 v${out.lower_version}`)
      if (out.upper_version) parts.push(`乐观 v${out.upper_version}`)
      setApplyMsg(`已回填：${parts.join(' / ')}。回到看板查看现金流对比。`)
      await refreshActuals().catch(() => {})
    } catch (e) {
      setErr(String(e.response?.data?.detail || e.message))
    }
  }

  async function onImport(file) {
    if (!file) return
    try {
      const res = await importActuals(file)
      setMsg(`导入成功：${res.upserted} 条`)
      refreshAfterImport()
    } catch (e) {
      setErr(String(e.response?.data?.detail || e.message))
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // 历史概览（手机迷你统计）
  const hist = useMemo(() => {
    const entries = Object.entries(actuals.total_by_period).sort()
    const cum = entries.reduce((a, [, v]) => a + Number(v), 0)
    const [lastP, lastV] = entries[entries.length - 1] || [null, null]
    return { lastP, lastV: lastV == null ? null : Number(lastV), cum, count: entries.length }
  }, [actuals.total_by_period])

  // ---------- 图表：置信带（stacked-area）+ 预测线 + 实际点 ----------
  const chartOption = useMemo(() => {
    if (!run) return null
    const cats = run.series.map((p) => p.period)
    const actualByPeriod = Object.fromEntries(
      Object.entries(actuals.total_by_period).filter(([p]) => cats.includes(p)),
    )
    const yhat = run.series.map((p) => Number(p.yhat))
    const lower = run.series.map((p) => Number(p.lower))
    const band = run.series.map((p) => Number(p.upper) - Number(p.lower))  // 面积 = upper−lower
    const hasBand = band.some((v) => v > 0)
    return {
      tooltip: {
        trigger: 'axis',
        // 只呈现预测值 + 区间范围，避免堆叠系列刷屏
        formatter: (ps) => {
          const i = ps[0]?.dataIndex
          if (i == null) return ''
          const s = run.series[i]
          const rng = Number(s.upper) - Number(s.lower) > 0
            ? `<br/>区间 ${fmt(Number(s.lower), 2)} ~ ${fmt(Number(s.upper), 2)}` : ''
          return `${s.period}<br/>预测 <b>${fmt(Number(s.yhat), 2)}</b> 万台${rng}`
        },
      },
      grid: { left: 40, right: 12, top: 12, bottom: 28, containLabel: true },
      xAxis: {
        type: 'category', data: cats,
        axisLabel: { fontSize: 9, interval: 5 },
      },
      yAxis: {
        type: 'value', axisLabel: { fontSize: 9 },
        splitLine: { lineStyle: { color: '#eef1f6' } },
      },
      series: [
        // 下沿（透明，作为堆叠基线）
        {
          name: '下沿', type: 'line', stack: 'ci', data: lower, symbol: 'none',
          lineStyle: { opacity: 0 }, silent: true, z: 1,
        },
        // 区间带（堆在下沿之上，面积 = 带宽）
        {
          name: '区间', type: 'line', stack: 'ci', data: band, symbol: 'none',
          lineStyle: { opacity: 0 }, silent: true, z: 1,
          areaStyle: { color: 'rgba(79,140,255,0.16)' },
        },
        // 预测线（实际月显点）
        {
          name: '预测销量', type: 'line', data: yhat, z: 3,
          color: SCENARIO_COLORS.base,
          lineStyle: { width: 2 },
          symbol: (_, params) => (actualByPeriod[cats[params.dataIndex]] != null ? 'circle' : 'none'),
          symbolSize: 6,
          markLine: {
            silent: true, symbol: 'none',
            lineStyle: { color: '#c5ccd8', type: 'dashed' },
            data: [{ yAxis: 0 }],
          },
        },
      ],
      // hasBand 无带时也无妨（区间系列全 0）
    }
  }, [run, actuals.total_by_period])

  const methodLabel = run ? (methodMeta(run.method)?.label || run.method)
    : (method ? (methodMeta(method)?.label || method) : '自动（计划锚定）')

  return (
    <div className="page">
      {/* 顶栏 */}
      <div className="fc-appbar">
        <div className="scenario-bar" style={{ justifyContent: 'space-between' }}>
          <div>
            <h1>销量预测</h1>
            <div className="sub">运行预测 · 回填现金流</div>
          </div>
          <select value={scenarioId ?? ''} onChange={(e) => setScenarioId(Number(e.target.value))}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}{s.is_active ? '（当前）' : ''}</option>
            ))}
          </select>
        </div>
      </div>

      {err && <div className="error-banner">{err}</div>}
      {msg && <div className="recalc-msg">{msg}</div>}
      {applyMsg && <div className="recalc-msg">{applyMsg}</div>}

      {/* ① 历史销量 */}
      <div className="card">
        <div className="fc-sec-head">
          <span className="fc-step done">1</span>
          <h3>历史销量</h3>
          <span className="fc-pill ok">有效 {actuals.n_effective} 个月</span>
          {canEdit && (
            <div className="fc-toolbar pc-only">
              <button className="btn" onClick={() => setShowEntry(true)}>{IPlus}手工录入</button>
              <button className="btn" onClick={() => fileRef.current?.click()}>{IUp}导入 Excel</button>
              <input ref={fileRef} type="file" accept=".xlsx" style={{ display: 'none' }}
                onChange={(e) => onImport(e.target.files[0])} />
            </div>
          )}
        </div>

        {/* 手机：迷你概览 */}
        <div className="fc-mobile">
          <div className="fc-mini">
            <div className="box">
              <div className="l">最新月 {hist.lastP || '—'}</div>
              <div className="v">{hist.lastV == null ? '—' : fmt(hist.lastV, 2)} <small>万台</small></div>
            </div>
            <div className="box">
              <div className="l">累计出货</div>
              <div className="v">{fmt(hist.cum, 2)} <small>万台</small></div>
            </div>
          </div>
          <p className="hint" style={{ margin: '10px 0 0' }}>历史录入与 Excel 导入请在电脑端操作。</p>
        </div>

        {/* 电脑：完整表 */}
        <div className="pc-only">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>期间</th><th>线上(万台)</th><th>线下(万台)</th><th>合计</th><th>来源</th></tr>
              </thead>
              <tbody>
                {Object.entries(actuals.total_by_period).sort().map(([p, tot]) => {
                  const on = actuals.actuals.find((a) => a.period === p && a.channel === 'online')
                  const off = actuals.actuals.find((a) => a.period === p && a.channel === 'offline')
                  return (
                    <tr key={p}>
                      <td className="row-name">{p}</td>
                      <td>{on ? fmt(Number(on.units), 2) : '—'}</td>
                      <td>{off ? fmt(Number(off.units), 2) : '—'}</td>
                      <td>{fmt(Number(tot), 2)}</td>
                      <td><span className="fc-chip">{on?.source || off?.source || '—'}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ margin: '10px 0 0' }}>
            导入格式：表头「月份 ｜ 线上(万台) ｜ 线下(万台)」，每行一个月，重复期间覆盖更新。
          </p>
        </div>
      </div>

      {/* ② 运行预测 */}
      <div className="card">
        <div className="fc-sec-head">
          <span className="fc-step">2</span>
          <h3>运行预测</h3>
        </div>

        {/* 手机：方法只读 + 预测期 + 运行 */}
        <div className="fc-mobile">
          <div className="fc-method-line">
            <Icon d={<><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></>} w={15} />
            当前方法 <b>{methodLabel}</b> · 历史满 12 个月自动升级
          </div>
          <div className="fc-fields">
            <label className="fc-field">
              <span>预测期</span>
              <select value={horizon.join(',')} onChange={(e) => setHorizon(e.target.value.split(','))}>
                <option value={DEFAULT_HORIZON.join(',')}>2026-08 ~ 2027-12（推荐）</option>
                <option value={['2027-01', '2028-12'].join(',')}>2027-01 ~ 2028-12</option>
              </select>
            </label>
          </div>
          <button className="btn primary lg" onClick={onRun} disabled={running || !scenarioId}>
            {IPlay}{running ? '计算中…' : '运行预测'}
          </button>
        </div>

        {/* 电脑：方法可选 + 预测期 + 运行（一行）+ 缩放年度目标 */}
        <div className="pc-only">
          <div className="fc-fields run">
            <label className="fc-field">
              <span>预测方法</span>
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="">自动（按历史选档）</option>
                {FORECAST_METHODS.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}{m.min ? `（≥${m.min}个月）` : ''}</option>
                ))}
              </select>
            </label>
            <label className="fc-field">
              <span>预测期</span>
              <select value={horizon.join(',')} onChange={(e) => setHorizon(e.target.value.split(','))}>
                <option value={DEFAULT_HORIZON.join(',')}>2026-08 ~ 2027-12（推荐）</option>
                <option value={['2027-01', '2028-12'].join(',')}>2027-01 ~ 2028-12</option>
              </select>
            </label>
            <button className="btn primary" onClick={onRun} disabled={running || !scenarioId}>
              {IPlay}{running ? '计算中…' : '运行'}
            </button>
          </div>
          <p className="fc-eyebrow" style={{ marginTop: 12 }}>缩放到年度目标（选填 · 万台）</p>
          <div className="fc-fields two">
            <label className="fc-field">
              <span>2028 目标</span>
              <input type="number" min="0" step="any" placeholder="不缩放"
                value={scale[2028]} onChange={(e) => setScale({ ...scale, 2028: e.target.value })} />
            </label>
            <label className="fc-field">
              <span>2029 目标</span>
              <input type="number" min="0" step="any" placeholder="不缩放"
                value={scale[2029]} onChange={(e) => setScale({ ...scale, 2029: e.target.value })} />
            </label>
          </div>
        </div>
      </div>

      {/* 预测结果 */}
      {run && (
        <div className="card">
          <div className="fc-meta">
            <span className="fc-badge">{methodLabel}</span>
            <span className="fc-kv">有效历史 <b>{run.n_actual}</b> 个月</span>
            {run.ratio_online != null && (
              <span className="fc-kv">线上占比 <b>{fmt(Number(run.ratio_online) * 100, 1)}%</b></span>
            )}
          </div>
          {!run.data_sufficient && (
            <div className="fc-callout">
              {IWarn}
              <p><b>历史不足 12 个月</b>，置信区间取保底带宽，仅供参考。形状取自计划曲线，水平按实际/计划校准。</p>
            </div>
          )}
          <div className="fc-chart-top">月度销量预测（万台）</div>
          <Chart option={chartOption} height={260} />
          <div className="fc-legend">
            <span><i className="dot" style={{ background: SCENARIO_COLORS.base }} />实际</span>
            <span><i style={{ background: SCENARIO_COLORS.base }} />预测 yhat</span>
            <span><i className="band" />置信区间</span>
          </div>

          {/* 电脑：候选方法回测明细 */}
          {run.candidates && (
            <div className="pc-only">
              <hr className="fc-divider" />
              <p className="fc-eyebrow">候选方法回测</p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>方法</th><th>sMAPE</th><th>MAE</th><th>RMSE</th><th>样本</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(run.candidates).map(([k, c]) => (
                      <tr key={k} className={run.method === k ? 'pick' : ''}>
                        <td className="row-name">
                          {methodMeta(k)?.label || k}{run.method === k ? <span className="fc-check"> ✓</span> : ''}
                        </td>
                        <td>{c.smape != null ? `${fmt(Number(c.smape), 1)}%` : <span className="fc-dash">—</span>}</td>
                        <td>{c.mae != null ? fmt(Number(c.mae), 2) : <span className="fc-dash">—</span>}</td>
                        <td>{c.rmse != null ? fmt(Number(c.rmse), 2) : <span className="fc-dash">—</span>}</td>
                        <td>{c.n || 0}{c.reason ? <span className="fc-rq">（{c.reason}）</span> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ③ 接受回填 */}
      {run && (
        <div className="card">
          <div className="fc-sec-head">
            <span className="fc-step">3</span>
            <h3>接受并回填</h3>
          </div>
          {!canEdit ? (
            <p className="hint">仅管理员/编辑可接受预测回填销量。</p>
          ) : (
            <>
              {/* 手机：一键接受中性 */}
              <div className="fc-mobile">
                <p className="hint">回填销量并重算现金流，生成新版本；可在电脑端回退或生成三情景。</p>
                <button className="btn primary lg" onClick={() => onApply(false)} disabled={running}>
                  {ICheck}接受并回填
                </button>
              </div>

              {/* 电脑：三情景 + 完整说明 */}
              <div className="pc-only">
                <label className={`fc-checkbox${run.data_sufficient ? '' : ' disabled'}`}>
                  <input type="checkbox" checked={triple && run.data_sufficient}
                    onChange={(e) => setTriple(e.target.checked)}
                    disabled={!run.data_sufficient} />
                  <span>生成<b>三情景</b>（悲观 / 中性 / 乐观）——
                    {run.data_sufficient ? '按置信区间上下沿各生成一个版本。'
                      : '历史满 12 个月后启用，当前区间不可靠故暂锁。'}</span>
                </label>
                <p className="hint">
                  回填 {horizon[0]} ~ {horizon[1]} 的线上/线下销量并重算现金流（覆盖月度计划，年度目标保留）；
                  生成新版本，可随时在「参数」页回退。
                </p>
                <button className="btn primary lg" onClick={() => onApply(true)} disabled={running}>
                  {ICheck}接受并回填{triple && run.data_sufficient ? '（生成三情景）' : ''}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* 手工录入弹窗（桌面触发） */}
      {showEntry && (
        <ManualEntry
          onClose={() => setShowEntry(false)}
          onSaved={refreshAfterImport}
          onError={(e) => setErr(String(e.response?.data?.detail || e.message))}
        />
      )}
    </div>
  )
}

function ManualEntry({ onClose, onSaved, onError }) {
  const [month, setMonth] = useState(nextMonth(new Date().toISOString().slice(0, 7)))
  const [online, setOnline] = useState('')
  const [offline, setOffline] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!/^\d{4}-\d{2}$/.test(month)) return
    setSaving(true)
    try {
      await upsertActuals([
        { period: month, channel: 'online', units: online || '0', note: 'manual' },
        { period: month, channel: 'offline', units: offline || '0', note: 'manual' },
      ])
      onSaved()
    } catch (e) {
      onError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>录入历史销量</h3>
          <button className="btn" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <label className="edit-cell">
            <span>月份</span>
            <input value={month} onChange={(e) => setMonth(e.target.value)} placeholder="2026-08" />
          </label>
          <label className="edit-cell">
            <span>线上 (万台)</span>
            <input type="number" min="0" step="0.01" value={online}
              onChange={(e) => setOnline(e.target.value)} />
          </label>
          <label className="edit-cell">
            <span>线下 (万台)</span>
            <input type="number" min="0" step="0.01" value={offline}
              onChange={(e) => setOffline(e.target.value)} />
          </label>
          <div className="action-row">
            <button className="btn" onClick={onClose}>取消</button>
            <button className="btn primary" onClick={save} disabled={saving || !month}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
