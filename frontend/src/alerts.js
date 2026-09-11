// 预警：扫描现金流网格，标出「资金缺口月」和「现金水位低于阈值月」。
// gap<0 表示当月出现资金缺口（需融资/延付才能过关）；closing<minCash 表示期末现金低于安全水位。
// 纯函数，UI 负责格式化与展示。金额单位：万元。
const EPS = 0.005

export function detectAlerts(grid, periods, minCash = 0) {
  if (!grid || !periods.length) return []
  const at = (key, p) => Number(grid.cells[key]?.[p]?.value ?? 0)
  const out = []
  for (const p of periods) {
    const gap = at('cash.gap', p)
    if (gap < -EPS) out.push({ period: p, type: 'gap', value: gap })
    const close = at('cash.closing', p)
    if (close < minCash - EPS) out.push({ period: p, type: 'lowcash', value: close })
  }
  return out
}

// 汇总：缺口/低现金各自的最早月与最严重值，供 banner 一行概览
export function summarizeAlerts(alerts) {
  const gaps = alerts.filter((a) => a.type === 'gap')
  const lows = alerts.filter((a) => a.type === 'lowcash')
  const worst = (arr) => arr.reduce((m, a) => (a.value < m.value ? a : m), arr[0])
  return {
    total: alerts.length,
    gap: gaps.length ? { count: gaps.length, first: gaps[0].period, worst: worst(gaps) } : null,
    lowcash: lows.length ? { count: lows.length, first: lows[0].period, worst: worst(lows) } : null,
  }
}
