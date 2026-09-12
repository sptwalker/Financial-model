// 投融资轮次 ↔ 引擎输入行的互转 + 迁移。
// 轮次是 UI 真值：[{name, period, amount}]。引擎只认逐期现金注入（cash.financing），
// 故按期求和（同月多轮相加）后回传；名称随 params.financing_rounds 存档，供图表标注。
export const FINANCING_ROW = 'cash.financing'

// 轮次列表 → {period: '金额'} 求和；金额取整、不摊分；空月/零额跳过
export function roundsToInput(rounds) {
  const out = {}
  for (const r of rounds || []) {
    const amt = Math.round(Number(r?.amount) || 0)
    if (!r?.period || !amt) continue
    out[r.period] = String((Number(out[r.period]) || 0) + amt)
  }
  return out
}

// 从基线网格的 cash.financing 行迁移出轮次（每个非零月一轮，占位名「融资」）
export function migrateRounds(grid) {
  const row = grid?.cells?.[FINANCING_ROW] || {}
  return Object.entries(row)
    .map(([period, cell]) => ({ name: '融资', period, amount: Math.round(Number(cell?.value) || 0) }))
    .filter((r) => r.amount)
    .sort((a, b) => a.period.localeCompare(b.period))
}

// 轮次 → 图表标注 {period: '名称 金额万'}；同月多轮名称以 / 合并
export function roundLabels(rounds) {
  const out = {}
  for (const r of rounds || []) {
    const amt = Math.round(Number(r?.amount) || 0)
    if (!r?.period || !amt) continue
    const tag = `${r.name || '融资'} ${amt}万`
    out[r.period] = out[r.period] ? `${out[r.period]} / ${tag}` : tag
  }
  return out
}
