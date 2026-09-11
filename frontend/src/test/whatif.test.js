/**
 * whatif.js 测试：滑杆值 → 引擎参数增量，及结果指标提取
 *
 * buildOverride 的系数语义（1=不变）和 impactOf 的 maxGap（全期最深负值）是推演页
 * 的判断核心，算错会让"提价 10%"变成绝对价、或缺口显示成 0，故单测锁死。
 */
import { describe, expect, it } from 'vitest'
import { buildOverride, buildExpenseInputs, impactOf } from '../whatif'

describe('buildOverride', () => {
  it('系数=1 时价格/销量维持基线（仅格式化）', () => {
    const o = buildOverride({ price_online: '1799', price_offline: '1475.18', qty_scale: '1.2' },
      { priceFactor: 1, qtyFactor: 1, collectNow: 0.5 })
    expect(o.price_online).toBe('1799.00')
    expect(o.qty_scale).toBe('1.2000')       // 乐观基线 1.2 × 1
    expect(o.collect_weight_online).toEqual(['0.50', '0.50'])
  })

  it('提价 10% / 降量 20% 按系数缩放基线', () => {
    const o = buildOverride({ price_online: '2000', price_offline: '1000', qty_scale: '1' },
      { priceFactor: 1.1, qtyFactor: 0.8, collectNow: 0.7 })
    expect(o.price_online).toBe('2200.00')
    expect(o.price_offline).toBe('1100.00')
    expect(o.qty_scale).toBe('0.8000')
    expect(o.collect_weight_online).toEqual(['0.70', '0.30'])
  })

  it('无基线参数时用引擎默认价兜底', () => {
    const o = buildOverride(null, { priceFactor: 1, qtyFactor: 1, collectNow: 0.5 })
    expect(o.price_online).toBe('1799.00')
    expect(o.price_offline).toBe('1475.18')
  })

  it('采购成本系数同步缩放主机/配件采购价；缺省视为不变', () => {
    // 只给采购旋钮，收入侧缺省 → 价格/销量维持基线
    const o = buildOverride(
      { cost_main: '1150', cost_accessory: '60' },
      { costBuy: 1.1 })
    expect(o.cost_main).toBe('1265.00')       // 1150 × 1.1
    expect(o.cost_accessory).toBe('66.00')    // 60 × 1.1
    expect(o.price_online).toBe('1799.00')    // 缺省价格系数=1
    expect(o.qty_scale).toBe('1.0000')
  })

  it('采购无基线参数时用引擎默认兜底（1150/60）', () => {
    const o = buildOverride(null, { costBuy: 1 })
    expect(o.cost_main).toBe('1150.00')
    expect(o.cost_accessory).toBe('60.00')
  })
})

describe('buildExpenseInputs', () => {
  const grid = {
    cells: {
      'exp.salary': { '2026-08': { value: '100' }, '2026-09': { value: '120' } },
      'exp.rent': { '2026-08': { value: '30' } },
      'exp.game_dev': { '2026-08': { value: '50' } },       // 研发组
      'exp.commercial_ip': { '2026-08': { value: '40' } },  // 研发组
      'exp.total': { '2026-08': { value: '260' } },   // 合计行不缩放
      'sale.online.amount': { '2026-08': { value: '999' } },  // 非费用行忽略
    },
  }
  it('运营/研发分组各按系数缩放，跳过合计与非费用行', () => {
    const o = buildExpenseInputs(grid, { opexFactor: 1.1, rdFactor: 0.8 })
    expect(o['exp.salary']).toEqual({ '2026-08': '110.0000', '2026-09': '132.0000' })
    expect(o['exp.rent']).toEqual({ '2026-08': '33.0000' })
    expect(o['exp.game_dev']).toEqual({ '2026-08': '40.0000' })       // 50 × 0.8
    expect(o['exp.commercial_ip']).toEqual({ '2026-08': '32.0000' })  // 40 × 0.8
    expect(o['exp.total']).toBeUndefined()
    expect(o['sale.online.amount']).toBeUndefined()
  })
  it('只缩放系数≠1 的组：运营=1 则运营行不覆盖，仅研发行输出', () => {
    const o = buildExpenseInputs(grid, { opexFactor: 1, rdFactor: 1.2 })
    expect(o['exp.salary']).toBeUndefined()
    expect(o['exp.rent']).toBeUndefined()
    expect(o['exp.game_dev']).toEqual({ '2026-08': '60.0000' })       // 50 × 1.2
  })
  it('两组系数均=1 或空网格返回 null（不必要则不覆盖）', () => {
    expect(buildExpenseInputs(grid, { opexFactor: 1, rdFactor: 1 })).toBeNull()
    expect(buildExpenseInputs(grid)).toBeNull()
    expect(buildExpenseInputs(null, { opexFactor: 1.2 })).toBeNull()
  })
})

describe('impactOf', () => {
  const periods = ['2026-08', '2026-09', '2026-10']
  const grid = {
    cells: {
      'cash.closing': { '2026-10': { value: '320' } },
      'cash.gap': { '2026-08': { value: '-10' }, '2026-09': { value: '-55' }, '2026-10': { value: '0' } },
      'collect.total': { '2026-08': { value: '5' }, '2026-09': { value: '8' }, '2026-10': { value: '12' } },
    },
  }
  it('提取期末现金/最深缺口/累计回款', () => {
    expect(impactOf(grid, periods)).toEqual({ cashClose: 320, maxGap: -55, collect: 25 })
  })
  it('空网格返回 null', () => {
    expect(impactOf(null, periods)).toBeNull()
    expect(impactOf(grid, [])).toBeNull()
  })
})
