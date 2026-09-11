// what-if 推演：把三个滑杆值翻译成引擎参数增量（叠加到情景快照参数上预览）。
// 单价/销量为"相对基线的系数"，回款为"当月回款占比"；引擎默认值兜底（price 1799/1475.18）。
export function buildOverride(base, { priceFactor, qtyFactor, collectNow }) {
  const po = Number(base?.price_online ?? 1799)
  const pf = Number(base?.price_offline ?? 1475.18)
  const qs = Number(base?.qty_scale ?? 1)
  return {
    price_online: (po * priceFactor).toFixed(2),
    price_offline: (pf * priceFactor).toFixed(2),
    qty_scale: (qs * qtyFactor).toFixed(4),
    collect_weight_online: [collectNow.toFixed(2), (1 - collectNow).toFixed(2)],
  }
}

// 推演关注的三个结果：期末现金、全期最深资金缺口、累计回款
export function impactOf(grid, periods) {
  if (!grid || !periods.length) return null
  const at = (key, p) => Number(grid.cells[key]?.[p]?.value ?? 0)
  return {
    cashClose: at('cash.closing', periods[periods.length - 1]),
    maxGap: periods.reduce((m, p) => Math.min(m, at('cash.gap', p)), 0),
    collect: periods.reduce((a, p) => a + at('collect.total', p), 0),
  }
}
