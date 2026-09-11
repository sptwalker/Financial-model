import React, { useEffect, useRef, useState } from 'react'
import { getVersions, listScenarios, recalc, importRebuild } from '../api'
import { PARAM_FIELDS } from '../rows'

export default function Params({ user, onImport }) {
  const [scenarioId, setScenarioId] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [params, setParams] = useState(null)
  const [versionNo, setVersionNo] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [importMsg, setImportMsg] = useState(null)
  const [importing, setImporting] = useState(false)
  const [ready, setReady] = useState(false)   // 首次情景拉取是否完成（区分「加载中」与「空库」）
  const fetchSeq = useRef(0)
  const importFiles = useRef({ main: null, report: null })

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
      } finally {
        setReady(true)
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
      importFiles.current = { main: null, payroll: null, report: null }
      // 刷新情景列表与当前版本快照；跳回看板展示新数据
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

      {msg && <div className="recalc-msg">{msg}</div>}

      {!params ? (
        ready && scenarios.length === 0
          ? <div className="empty-hint">{user && user.role !== 'viewer'
              ? <>暂无基础数据，请用上方<b>「导入表格·重建基础数据」</b>上传三张表格重建后再使用。</>
              : <>暂无基础数据，请联系管理员导入表格重建。</>}</div>
          : <div className="loading">加载中…</div>
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
