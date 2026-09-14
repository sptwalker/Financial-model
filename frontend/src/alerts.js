// 预警：扫描现金流网格，标出「期末现金低于安全水位」的月份——反映账户未来实际现金状况，
// 供制定节支/提前贷款/按需融资等策略。closing<minCash 即该月末账上现金跌破安全线。
// 注：当月经营缺口(cash.gap) 不进预警（借款/融资不影响它，只是当月经营流水），仅作现金流水图参考线。
// 纯函数，UI 负责格式化与展示。金额单位：万元。
const EPS = 0.005

export function detectAlerts(grid, periods, minCash = 0) {
  if (!grid || !periods.length) return []
  const at = (key, p) => Number(grid.cells[key]?.[p]?.value ?? 0)
  const out = []
  for (const p of periods) {
    const close = at('cash.closing', p)
    if (close < minCash - EPS) out.push({ period: p, type: 'lowcash', value: close })
  }
  return out
}

// 汇总：低现金月的数量、最早月与最低值，供 banner 一行概览
export function summarizeAlerts(alerts) {
  const lows = alerts.filter((a) => a.type === 'lowcash')
  const worst = (arr) => arr.reduce((m, a) => (a.value < m.value ? a : m), arr[0])
  return {
    total: alerts.length,
    lowcash: lows.length ? { count: lows.length, first: lows[0].period, worst: worst(lows) } : null,
  }
}
