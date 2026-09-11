// what-if 推演：把滑杆值翻译成引擎增量（叠加到情景快照上做非持久化预览）。
// 单价/销量/采购成本均为"相对基线的系数"（1=不变），回款为"当月回款占比"。
//
// 成本分两条路：
// - 采购单价（主机/配件）是纯参数、引擎必算 → 走 params。
// - 运营费用（工资/租金/营销/佣金…）在库里多是逐月输入行、非参数，params 缩放
//   不了；改由 buildExpenseInputs 把基线网格的 exp.* 行整体按系数缩放后回传 inputs
//   覆盖（inputs 优先级高于引擎计算，故佣金等"输入驱动"的费用也能生效）。
export function buildOverride(base, knobs) {
  const {
    priceFactor = 1, qtyFactor = 1, collectNow = 0.5, costMain = 1, costAcc = 1,
  } = knobs || {}
  const n = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d)
  const po = n(base?.price_online, 1799)
  const pf = n(base?.price_offline, 1475.18)
  const qs = n(base?.qty_scale, 1)
  const cm = n(base?.cost_main, 1150)
  const ca = n(base?.cost_accessory, 60)
  return {
    price_online: (po * priceFactor).toFixed(2),
    price_offline: (pf * priceFactor).toFixed(2),
    qty_scale: (qs * qtyFactor).toFixed(4),
    cost_main: (cm * costMain).toFixed(2),
    cost_accessory: (ca * costAcc).toFixed(2),
    collect_weight_online: [collectNow.toFixed(2), (1 - collectNow).toFixed(2)],
  }
}

// 运营费用系数 → inputs 覆盖：基线网格所有 exp.* 明细行（不含合计 exp.total）× 系数。
// 回传全部月份 → 引擎按逐月输入处理，不触发年度目标再摊，故总额精确 = 原额 × 系数。
export function buildExpenseInputs(baseGrid, factor) {
  if (!baseGrid?.cells || factor === 1) return null
  const out = {}
  for (const [key, byPeriod] of Object.entries(baseGrid.cells)) {
    if (!key.startsWith('exp.') || key === 'exp.total') continue
    out[key] = {}
    for (const [p, cell] of Object.entries(byPeriod)) {
      out[key][p] = (Number(cell.value ?? 0) * factor).toFixed(4)
    }
  }
  return Object.keys(out).length ? out : null
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
