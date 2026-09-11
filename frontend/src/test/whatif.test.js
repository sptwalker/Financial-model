/**
 * whatif.js 测试：滑杆值 → 引擎参数增量，及结果指标提取
 *
 * buildOverride 的系数语义（1=不变）和 impactOf 的 maxGap（全期最深负值）是推演页
 * 的判断核心，算错会让"提价 10%"变成绝对价、或缺口显示成 0，故单测锁死。
 */
import { describe, expect, it } from 'vitest'
import { buildOverride, impactOf } from '../whatif'

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
