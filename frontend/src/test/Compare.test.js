/**
 * Compare.jsx 纯逻辑测试：情景并排的指标聚合与列序
 *
 * aggregate 的 minlast（现金缺口取全期最深）与列序 scnRank 是这页的判断核心，
 * 算错会让"最大资金缺口"显示成 0 或把三情景排乱，故单测锁死。
 */
import { describe, expect, it } from 'vitest'
import { aggregate, scnRank } from '../pages/Compare'

const P = ['2026-08', '2026-09', '2026-10']
const grid = {
  cells: {
    'sale.total.amount': { '2026-08': { value: '10' }, '2026-09': { value: '20' }, '2026-10': { value: '30' } },
    'cash.closing': { '2026-08': { value: '100' }, '2026-10': { value: '250' } },
    'cash.gap': { '2026-08': { value: '0' }, '2026-09': { value: '-40' }, '2026-10': { value: '-15' } },
  },
}

describe('aggregate', () => {
  it('sum 取全期合计', () => {
    expect(aggregate(grid, P, 'sale.total.amount', 'sum')).toBe(60)
  })
  it('last 取期末值（缺失中间月不影响）', () => {
    expect(aggregate(grid, P, 'cash.closing', 'last')).toBe(250)
  })
  it('minlast 取全期最深缺口（负得最多）', () => {
    expect(aggregate(grid, P, 'cash.gap', 'minlast')).toBe(-40)
  })
  it('无网格返回 null', () => {
    expect(aggregate(null, P, 'sale.total.amount', 'sum')).toBeNull()
  })
  it('缺失行按 0', () => {
    expect(aggregate(grid, P, '不存在', 'sum')).toBe(0)
  })
})

describe('scnRank', () => {
  it('中性<乐观<悲观，其余垫底', () => {
    expect(['悲观方案', '未知', '中性', '乐观'].sort((a, b) => scnRank(a) - scnRank(b)))
      .toEqual(['中性', '乐观', '悲观方案', '未知'])
  })
})
