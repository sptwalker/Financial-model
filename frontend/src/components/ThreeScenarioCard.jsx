import React, { useEffect, useMemo, useState } from 'react'
import Chart from '../components/Chart'
import { fmt, getGrid, gridPeriods, listForecastRuns } from '../api'
import { SCENARIO_COLORS } from '../rows'

// 三情景并排（阶段 3）：读最新 ForecastRun 的版本链，对比悲观/中性/乐观的期末现金。
// 无预测记录时不报错，提示去「预测」页运行。
const TONES = [
  { key: 'lower_version', label: '悲观', color: SCENARIO_COLORS.lower },
  { key: 'base_version', label: '中性', color: SCENARIO_COLORS.base },
  { key: 'upper_version', label: '乐观', color: SCENARIO_COLORS.upper },
]

// v → 该版本在 run 中的角色（悲观/中性/乐观）；不属于版本链则为 null
function toneOf(run, v) {
  for (const t of TONES) {
    if (run[t.key] != null && Number(run[t.key]) === Number(v)) return t
  }
  return null
}

export default function ThreeScenarioCard({ scenarioId }) {
  const [run, setRun] = useState(null)
  const [grids, setGrids] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!scenarioId) return
    let stale = false
    setLoading(true)
    setErr(null)
    ;(async () => {
      try {
        const { runs } = await listForecastRuns(scenarioId)
        if (stale) return
        const latest = runs[0] // 最新在前
        setRun(latest || null)
        if (!latest) {
          setGrids(null)
          return
        }
        const versions = TONES.map((t) => latest[t.key]).filter(Boolean)
        const loaded = await Promise.all(
          versions.map((v) => getGrid(scenarioId, v).then((g) => ({ v, g })))
        )
        if (!stale) setGrids(loaded)
      } catch (e) {
        if (!stale) setErr(String(e.response?.data?.detail || e.message))
      } finally {
        if (!stale) setLoading(false)
      }
    })()
    return () => { stale = true }
  }, [scenarioId])

  const option = useMemo(() => {
    if (!grids || !grids.length) return null
    const periods = gridPeriods(grids[0].g)
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => fmt(v, 2) },
      legend: { bottom: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10 } },
      grid: { left: 44, right: 8, top: 12, bottom: 34, containLabel: true },
      xAxis: {
        type: 'category',
        data: periods.map((p) => `${p.slice(2, 4)}/${p.slice(5)}`),
        axisLabel: { fontSize: 9, interval: 5 },
      },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#eee' } } },
      series: grids.map(({ v, g }) => {
        const t = toneOf(run, v)
        return {
          name: t ? `${t.label} v${v}` : `v${v}`,
          type: 'line',
          symbol: 'none',
          color: t?.color,
          lineStyle: { width: 1.8, type: t ? 'solid' : 'dashed' },
          data: periods.map((p) => Number(g.cells['cash.closing']?.[p]?.value ?? 0)),
        }
      }),
    }
  }, [grids, run])

  return (
    <section className="card">
      <h2>三情景现金流对比</h2>
      {loading ? (
        <div className="loading">加载中…</div>
      ) : err ? (
        <div className="error-banner">{err}</div>
      ) : run ? (
        <>
          <p className="hint">
            预测方法 {run.method}（有效历史 {run.n_actual} 个月），预测期 {run.horizon_start} ~ {run.horizon_end}。
            悲观/乐观为置信区间上下沿回填后的版本。
          </p>
          <div className="scenario-bar">
            {TONES.map((t) => run[t.key] != null && (
              <span key={t.key} className="version-chip" style={{ borderColor: t.color }}>
                {t.label} v{run[t.key]}
              </span>
            ))}
          </div>
          <Chart option={option} height={260} />
        </>
      ) : (
        <p className="hint">
          尚无预测记录。去「预测」页运行预测并接受回填后，这里会并排对比悲观/中性/乐观三版本的现金流。
        </p>
      )}
    </section>
  )
}
