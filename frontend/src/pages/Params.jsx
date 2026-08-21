import React, { useEffect, useRef, useState } from 'react'
import { getVersions, listScenarios, recalc } from '../api'
import { PARAM_FIELDS } from '../rows'

export default function Params({ onRecalc }) {
  const [scenarioId, setScenarioId] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [params, setParams] = useState(null)
  const [versionNo, setVersionNo] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const fetchSeq = useRef(0)

  // 切换情景时重新拉取该情景的参数快照与版本列表（防过期响应覆盖）
  const loadVersions = async (id) => {
    const seq = ++fetchSeq.current
    try {
      const { versions, params: p } = await getVersions(id)
      if (seq !== fetchSeq.current) return // 过期响应丢弃
      const latest = versions[0]
      setVersionNo(latest ? latest.version_no : null)
      setParams(latest ? p || {} : null)
    } catch (e) {
      if (seq === fetchSeq.current) setMsg(String(e.response?.data?.detail || e.message))
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const scs = await listScenarios()
        setScenarios(scs)
        const active = scs.find((s) => s.is_active) || scs[0]
        setScenarioId(active ? active.id : null)
      } catch (e) {
        setMsg(String(e.response?.data?.detail || e.message))
      }
    })()
  }, [])

  // 情景切换 / 重算后：同步该情景的参数与版本
  useEffect(() => {
    if (scenarioId != null) loadVersions(scenarioId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId])

  const setField = (key, val) => setParams((prev) => ({ ...prev, [key]: val }))

  const doRecalc = async () => {
    try {
      setBusy(true)
      setMsg('计算中…')
      const r = await recalc(scenarioId, { comment: '参数页调整后重算', params })
      setMsg(`已生成 v${r.version_no}（共 ${r.cell_count} 个单元格）`)
      await loadVersions(scenarioId) // 刷新版本列表与最新版本号
      if (onRecalc) onRecalc()
    } catch (e) {
      setMsg('重算失败：' + String(e.response?.data?.detail || e.message))
    } finally {
      setBusy(false)
    }
  }

  const resetDefaults = () => {
    // 恢复引擎默认参数：重新拉取版本快照不可行（快照已是默认），直接前端内置一份
    setParams({
      price_online: '1799',
      price_offline: '1475.18',
      cost_main: '1150',
      cost_accessory: '60',
      acc_ratio: '0.5',
      acc_revenue_per_unit: '200',
      sub_ratio: '0.7',
      sub_revenue_per_unit: '200',
      channel_commission_rate: '0.05',
      purchase_lag: 2,
    })
  }

  return (
    <div className="page">
      <header className="app-header">
        <h1>参数与重算</h1>
        <div className="scenario-bar">
          <select value={scenarioId ?? ''} onChange={(e) => setScenarioId(Number(e.target.value))}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <span className="version-chip">当前版本 v{versionNo ?? '-'}</span>
        </div>
      </header>

      {msg && <div className="recalc-msg">{msg}</div>}

      {!params ? (
        <div className="loading">加载中…</div>
      ) : (
        <>
          <section className="card">
            <h2>计算参数</h2>
            <p className="hint">修改后点击底部“重算”，生成新版本；不影响历史版本。</p>
            <div className="param-list">
              {PARAM_FIELDS.map((f) => (
                <label className="param-item" key={f.key}>
                  <span className="param-label">
                    {f.label}
                    {f.hint && <em>{f.hint}</em>}
                  </span>
                  <input type="number" step={f.step}
                    value={params[f.key] ?? ''}
                    onChange={(e) => setField(f.key, e.target.value)} />
                </label>
              ))}
            </div>
          </section>

          <div className="action-row">
            <button className="btn" onClick={resetDefaults}>恢复默认参数</button>
            <button className="btn primary" onClick={doRecalc} disabled={busy}>
              {busy ? '重算中…' : '重算'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
