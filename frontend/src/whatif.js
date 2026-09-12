// what-if 推演：把滑杆值翻译成引擎增量（叠加到情景快照上做非持久化预览）。
// 单价/销量/采购成本均为"相对基线的系数"（1=不变），回款为"当月回款占比"。
//
// 成本分两条路：
// - 采购单价（主机+配件）是纯参数、引擎必算 → 走 params，同一系数缩放两者。
// - 运营/研发费用在库里多是逐月输入行、非参数，params 缩放不了；改由
//   buildExpenseInputs 把基线网格的 exp.* 行整体按系数缩放后回传 inputs 覆盖
//   （inputs 优先级高于引擎计算，故佣金等"输入驱动"的费用也能生效）。
export function buildOverride(base, knobs) {
  const {
    priceFactor = 1, qtyFactor = 1, collectNow = 0.5, costBuy = 1,
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
    cost_main: (cm * costBuy).toFixed(2),
    cost_accessory: (ca * costBuy).toFixed(2),
    collect_weight_online: [collectNow.toFixed(2), (1 - collectNow).toFixed(2)],
  }
}

// exp.* 行分两组：研发成本（研发外包/商业IP/版号）单列，其余归运营费用。
export const RD_ROWS = new Set(['exp.game_dev', 'exp.commercial_ip', 'exp.license'])

// 运营/研发系数 → inputs 覆盖：基线网格 exp.* 明细行（不含合计）各按所属组系数缩放。
// 回传全部月份 → 引擎按逐月输入处理，不触发年度目标再摊，故总额精确 = 原额 × 系数。
export function buildExpenseInputs(baseGrid, { opexFactor = 1, rdFactor = 1 } = {}) {
  if (!baseGrid?.cells) return null
  const out = {}
  for (const [key, byPeriod] of Object.entries(baseGrid.cells)) {
    if (!key.startsWith('exp.') || key === 'exp.total') continue
    const f = RD_ROWS.has(key) ? rdFactor : opexFactor
    if (f === 1) continue
    out[key] = {}
    for (const [p, cell] of Object.entries(byPeriod)) {
      out[key][p] = (Number(cell.value ?? 0) * f).toFixed(4)
    }
  }
  return Object.keys(out).length ? out : null
}

// 推演关注的结果：期末现金、全期最深资金缺口、累计回款/销售收入/总成本
export function impactOf(grid, periods) {
  if (!grid || !periods.length) return null
  const at = (key, p) => Number(grid.cells[key]?.[p]?.value ?? 0)
  const sum = (key) => periods.reduce((a, p) => a + at(key, p), 0)
  return {
    cashClose: at('cash.closing', periods[periods.length - 1]),
    maxGap: periods.reduce((m, p) => Math.min(m, at('cash.gap', p)), 0),
    collect: sum('collect.total'),
    sales: sum('sale.total.amount'),   // 销售收入合计
    cost: sum('cash.expense'),         // 总成本 = 采购合计 + 运营费用合计
  }
}
