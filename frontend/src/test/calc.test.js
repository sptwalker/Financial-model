import { describe, it, expect } from 'vitest'
import { avgCost, priceAverages } from '../calc'

const cell = (v) => ({ value: String(v) })
const gridOf = (rows) => ({
  cells: Object.fromEntries(Object.entries(rows).map(([k, per]) => [
    k, Object.fromEntries(Object.entries(per).map(([p, v]) => [p, cell(v)])),
  ])),
})

describe('avgCost', () => {
  it('(研发+运营+采购+推广) 全期 ÷ 总销量 = 元/台', () => {
    const grid = gridOf({
      'exp.game_dev': { '2026-01': 10 },      // 研发
      'exp.salary': { '2026-01': 20 },        // 运营管理
      'exp.brand': { '2026-01': 5 },          // 营销/推广
      'purchase.total': { '2026-01': 65 },
      'qty.total': { '2026-01': 1 },          // 1 万台
    })
    // 成本合计 100 万元 ÷ 1 万台 = 100 元/台
    const r = avgCost(grid, ['2026-01'])
    expect(r.totalCost).toBe(100)
    expect(r.avg).toBe(100)
  })
  it('销量为 0 → avg 为 null', () => {
    expect(avgCost(gridOf({ 'qty.total': { '2026-01': 0 } }), ['2026-01']).avg).toBeNull()
  })
})

describe('priceAverages', () => {
  const packages = [{ id: 'p1', price: 2000 }, { id: 'p2', price: 1000 }]
  const channels = [
    { id: 'c1', name: '天猫', side: 'online', cost: 100 },
    { id: 'c2', name: '创维', side: 'offline', cost: 50 },
  ]
  it('各层净价 = (Σ定价×量 − Σ渠道成本×量) ÷ Σ量', () => {
    const lines = [
      { channelId: 'c1', packageId: 'p1', qty: 1 }, // 线上 2000, 成本100
      { channelId: 'c2', packageId: 'p2', qty: 1 }, // 线下 1000, 成本50
    ]
    const r = priceAverages(packages, channels, lines)
    expect(r.online.net).toBe(1900)
    expect(r.offline.net).toBe(950)
    expect(r.overall.gross).toBe(1500)         // (2000+1000)/2
    expect(r.overall.net).toBe(1425)           // (3000-150)/2
    expect(r.byChannel).toHaveLength(2)
  })
  it('无销量 → 各层 null', () => {
    const r = priceAverages(packages, channels, [])
    expect(r.overall.net).toBeNull()
    expect(r.byChannel).toHaveLength(0)
  })
})
