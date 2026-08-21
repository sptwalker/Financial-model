import React, { useEffect, useMemo, useRef, useState } from 'react'
import Chart from '../components/Chart'
import {
  applyForecast, fmt, importActuals, listActuals, listScenarios,
  runForecast, upsertActuals,
} from '../api'
import { FORECAST_METHODS, SCENARIO_COLORS } from '../rows'

// 预测工作台（阶段 3）：
// 历史销量（sales_actuals）→ 方法阶梯 + 回测选优 → 置信区间 → 接受回填 qty 并重算现金流。
// 历史只有 1-2 个月时走计划锚定（形状=计划曲线，水平=实际/计划校准），并明示"数据不足"。

const DEFAULT_HORIZON = ['2026-07', '2027-12']

function nextMonth(p) {
  const [y, m] = p.split('-').map(Number)
  const d = new Date(y, m, 1) // m 即下月的 0 号 → 简单进位
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function methodMeta(method) {
  return FORECAST_METHODS.find((m) => m.key === method) || null
}

export default function Forecast({ user }) {
  const canEdit = user && (user.role === 'admin' || user.role === 'editor')

  const [scenarios, setScenarios] = useState([])
  const [scenarioId, setScenarioId] = useState(null)
  const [actuals, setActuals] = useState({ actuals: [], n_effective: 0, total_by_period: {} })
  const [run, setRun] = useState(null)
  const [method, setMethod] = useState('')            // '' = 自动
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON)
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState(null)                // run 反馈
  const [applyMsg, setApplyMsg] = useState(null)      // apply 反馈
  const [err, setErr] = useState(null)
  const [showEntry, setShowEntry] = useState(false)
  const [triple, setTriple] = useState(true)          // 三情景开关
  const fileRef = useRef(null)

  // 历史最末月 → 默认水平线（起点=下月，18 期）
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
      const res = await runForecast({
        scenario_id: scenarioId,
        method: method || null,
        horizon,
      })
      setRun(res)
      setMsg(`${res.method}（有效历史 ${res.n_actual} 个月）· 线上占比 ${fmt(Number(res.ratio_online), 1)}%`)
    } catch (e) {
      setErr(String(e.response?.data?.detail || e.message))
    } finally {
      setRunning(false)
    }
  }

  async function onApply() {
    if (!run || !run.series.length) return
    const ratio = Number(run.ratio_online)
    // 渠道拆分：yhat/lower/upper 都是总量口径，按线上占比 ratio 拆成 online/offline
    const split = (totalOf) => run.series.map((p) => ({
      period: p.period,
      online: fmt(Number(totalOf(p)) * ratio, 4),
      offline: fmt(Number(totalOf(p)) * (1 - ratio), 4),
    }))
    const withCI = triple && run.data_sufficient
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

  // ---------- 图表：实际（有则实心）+ 预测 + CI 带 ----------
  const chartOption = useMemo(() => {
    if (!run) return null
    const cats = run.series.map((p) => p.period)
    const actualByPeriod = Object.fromEntries(
      Object.entries(actuals.total_by_period).filter(([p]) => cats.includes(p)),
    )
    const band = run.series
      .filter((p) => p.lower !== p.upper)
      .map((p) => [{ xAxis: p.period, yAxis: Number(p.lower) }, { xAxis: p.period, yAxis: Number(p.upper) }])
    return {
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v) => `${fmt(v, 2)} 万台`,
      },
      grid: { left: 46, right: 14, top: 30, bottom: 30 },
      xAxis: {
        type: 'category',
        data: cats,
        axisLabel: { rotate: 45 },
      },
      yAxis: { type: 'value' },
      series: [{
        name: '预测销量',
        type: 'line',
        data: run.series.map((p) => Number(p.yhat)),
        color: SCENARIO_COLORS.base,
        symbol: (_, i) => (actualByPeriod[cats[i]] != null ? 'circle' : 'none'),
        symbolSize: 5,
        markArea: band.length
          ? { silent: true, itemStyle: { color: 'rgba(79, 140, 255, 0.14)' }, data: band }
          : undefined,
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#999', type: 'dashed' },
          label: { formatter: '0' },
          data: [{ yAxis: 0 }],
        },
      }],
    }
  }, [run, actuals.total_by_period])

  return (
    <div>
      <div className="card">
        <div className="action-row">
          <div>
            <select value={scenarioId ?? ''} onChange={(e) => setScenarioId(Number(e.target.value))}>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name}{s.is_active ? '（当前）' : ''}</option>
              ))}
            </select>
          </div>
          <div className="hint">
            方法阶梯：季节朴素 12 个月解锁 · Holt-Winters 24 个月 · SARIMA 36 个月；不足时自动使用计划锚定
          </div>
        </div>
        {err && <div className="error-banner">{err}</div>}
        {msg && <div className="recalc-msg">{msg}</div>}
        {applyMsg && <div className="recalc-msg">{applyMsg}</div>}
      </div>

      {/* 历史销量 */}
      <div className="card">
        <div className="action-row">
          <h3>历史销量</h3>
          <span className="hint">有效历史 {actuals.n_effective} 个月（月度合计 &gt; 0 计入）</span>
          {canEdit && (
            <div style={{ marginLeft: 'auto' }}>
              <button className="btn" onClick={() => setShowEntry(true)}>手工录入</button>
              <button className="btn" style={{ marginLeft: 8 }} onClick={() => fileRef.current?.click()}>
                导入 Excel
              </button>
              <input ref={fileRef} type="file" accept=".xlsx" style={{ display: 'none' }}
                onChange={(e) => onImport(e.target.files[0])} />
            </div>
          )}
        </div>
        <div className="hint">导入格式：第一行表头「月份 | 线上(万台) | 线下(万台)」，之后每行一个月；重复期间覆盖更新。</div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>期间</th><th>线上(万台)</th><th>线下(万台)</th><th>合计(万台)</th><th>来源</th></tr>
            </thead>
            <tbody>
              {Object.entries(actuals.total_by_period).map(([p, tot]) => {
                const on = actuals.actuals.find((a) => a.period === p && a.channel === 'online')
                const off = actuals.actuals.find((a) => a.period === p && a.channel === 'offline')
                return (
                  <tr key={p}>
                    <td>{p}</td>
                    <td>{on ? fmt(Number(on.units), 2) : '—'}</td>
                    <td>{off ? fmt(Number(off.units), 2) : '—'}</td>
                    <td>{fmt(Number(tot), 2)}</td>
                    <td>{on?.source || off?.source || ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 预测预览 */}
      <div className="card">
        <div className="action-row">
          <h3>预测预览</h3>
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="">自动（按历史选档）</option>
            {FORECAST_METHODS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}{m.min ? `（≥${m.min}个月）` : ''}</option>
            ))}
          </select>
          <select value={horizon.join(',')} onChange={(e) => setHorizon(e.target.value.split(','))}>
            <option value={DEFAULT_HORIZON.join(',')}>2026-07 ~ 2027-12</option>
            <option value={['2026-08', '2027-12'].join(',')}>2026-08 ~ 2027-12</option>
            <option value={['2027-01', '2028-12'].join(',')}>2027-01 ~ 2028-12</option>
          </select>
          <button className="btn primary" onClick={onRun} disabled={running || !scenarioId}>
            {running ? '计算中…' : '运行预测'}
          </button>
        </div>

        {run && (
          <>
            <div className="hint">
              {run.reason}
              {run.data_sufficient ? '' : '　⚠ 历史不足 12 个月，区间带宽取保底值，仅供参考。'}
            </div>
            <div className="scenario-bar">
              <span className="version-chip" style={{ borderColor: SCENARIO_COLORS.base }}>
                实际+预测
              </span>
              <span className="hint">浅蓝带 = 置信区间（80% 量级）</span>
            </div>
            <Chart option={chartOption} height={300} />
            {run.candidates && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>候选方法</th><th>sMAPE</th><th>MAE</th><th>RMSE</th><th>样本</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(run.candidates).map(([k, c]) => (
                      <tr key={k}>
                        <td>{methodMeta(k)?.label || k}{run.method === k ? ' ✓' : ''}</td>
                        <td>{c.smape != null ? `${fmt(Number(c.smape), 1)}%` : '—'}</td>
                        <td>{c.mae != null ? fmt(Number(c.mae), 2) : '—'}</td>
                        <td>{c.rmse != null ? fmt(Number(c.rmse), 2) : '—'}</td>
                        <td>{c.n || 0}{c.reason ? <span className="hint">（{c.reason}）</span> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {/* 接受预测 */}
      {run && (
        <div className="card">
          <div className="action-row">
            <h3>接受预测</h3>
            {canEdit && (
              <label className="hint" style={{ marginLeft: 'auto' }}>
                <input type="checkbox" checked={triple}
                  onChange={(e) => setTriple(e.target.checked)}
                  disabled={!run.data_sufficient} />
                生成三情景（悲观/乐观）
              </label>
            )}
          </div>
          {!canEdit ? (
            <div className="hint">仅管理员/编辑可接受预测回填销量。</div>
          ) : (
            <>
              <div className="hint">
                回填 {horizon[0]} ~ {horizon[1]} 的线上/线下销量并重算现金流（覆盖月度计划，年度目标保留）；
                生成新版本，可随时在「参数」页回退。
              </div>
              {!triple && <div className="hint">⚠ 仅接受中性版本；历史不足 12 个月时区间不可靠，故三情景需更多历史。</div>}
              <button className="btn primary" onClick={onApply} disabled={running}>
                接受并回填
              </button>
            </>
          )}
        </div>
      )}

      {/* 手工录入弹窗 */}
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
