// 参数页两个「仅显示」计算器的纯计算（不写库、不重算）：平均成本 + 平均售价。
import { BUDGET_COST_GROUPS } from './rows'

const sumRow = (grid, key, periods) =>
  periods.reduce((s, p) => s + Number(grid?.cells?.[key]?.[p]?.value ?? 0), 0)
const groupKeys = (name) =>
  BUDGET_COST_GROUPS.find((g) => g.name === name)?.rows.map((r) => r.key) ?? []

// 平均成本 = (研发+运营+采购+推广) 全期合计 ÷ 总销量。研发/运营/推广取预算成本分组，
// 采购取 purchase.total，推广=营销分组。销量为 0 时均价返回 null（不可算）。
export function avgCost(grid, periods) {
  const sumKeys = (keys) => keys.reduce((s, k) => s + sumRow(grid, k, periods), 0)
  const rd = sumKeys(groupKeys('研发'))
  const ops = sumKeys(groupKeys('运营管理'))
  const promo = sumKeys(groupKeys('营销'))
  const purchase = sumRow(grid, 'purchase.total', periods)
  const qty = sumRow(grid, 'qty.total', periods) // 万台
  const totalCost = rd + ops + promo + purchase   // 万元
  // 单位换算：成本万元 ÷ 销量万台 = 元/台
  const avg = qty > 0 ? (totalCost * 1e4) / (qty * 1e4) : null
  return { rd, ops, promo, purchase, qty, totalCost, avg }
}

// 平均售价：包装决定定价、渠道决定渠道成本与线上/线下归属。
// 渠道成本为定价的百分比；每层净价 = (Σ定价×数量 − Σ定价×成本%×数量) ÷ Σ数量。
export function priceAverages(packages, channels, lines) {
  const priceOf = (id) => Number(packages.find((x) => x.id === id)?.price ?? 0)
  const chan = (id) => channels.find((x) => x.id === id)
  const blank = () => ({ qty: 0, gross: 0, costWt: 0 })
  const acc = { online: blank(), offline: blank(), all: blank() }
  const byChannel = new Map()

  for (const ln of lines) {
    const c = chan(ln.channelId)
    const q = Number(ln.qty) || 0
    if (!c || q <= 0) continue
    const price = priceOf(ln.packageId)
    const costPer = price * (Number(c.cost) || 0) / 100 // 渠道成本为定价百分比
    for (const bucket of [acc[c.side], acc.all]) {
      bucket.qty += q; bucket.gross += price * q; bucket.costWt += costPer * q
    }
    const cur = byChannel.get(c.id) || { ...blank(), name: c.name, side: c.side, cost: Number(c.cost) || 0 }
    cur.qty += q; cur.gross += price * q; cur.costWt += costPer * q
    byChannel.set(c.id, cur)
  }

  const net = (b) => (b.qty > 0 ? (b.gross - b.costWt) / b.qty : null)
  const grossAvg = (b) => (b.qty > 0 ? b.gross / b.qty : null)
  return {
    byChannel: [...byChannel.values()].map((b) => ({
      name: b.name, side: b.side, qty: b.qty, gross: grossAvg(b), cost: b.cost, net: net(b),
    })),
    online: { qty: acc.online.qty, gross: grossAvg(acc.online), net: net(acc.online) },
    offline: { qty: acc.offline.qty, gross: grossAvg(acc.offline), net: net(acc.offline) },
    overall: { qty: acc.all.qty, gross: grossAvg(acc.all), net: net(acc.all) },
  }
}
