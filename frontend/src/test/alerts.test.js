/**
 * alerts.js 测试：现金流预警检测与汇总
 *
 * 缺口用 gap<0、低现金用 closing<minCash，阈值边界（恰好等于阈值不报警）和
 * 最严重月的选取是预警可信度的核心，算错会漏报缺口或误报安全月，故单测锁死。
 */
import { describe, expect, it } from 'vitest'
import { detectAlerts, summarizeAlerts } from '../alerts'

const P = ['2026-08', '2026-09', '2026-10', '2026-11']
const grid = {
  cells: {
    'cash.gap': { '2026-08': { value: '0' }, '2026-09': { value: '-40' }, '2026-10': { value: '-15' }, '2026-11': { value: '0' } },
    'cash.closing': { '2026-08': { value: '100' }, '2026-09': { value: '5' }, '2026-10': { value: '80' }, '2026-11': { value: '200' } },
  },
}

describe('detectAlerts', () => {
  it('标出所有资金缺口月（gap<0）', () => {
    const gaps = detectAlerts(grid, P, 0).filter((a) => a.type === 'gap')
    expect(gaps.map((a) => a.period)).toEqual(['2026-09', '2026-10'])
    expect(gaps[0].value).toBe(-40)
  })
  it('低现金按阈值判定，恰好等于阈值不报警', () => {
    const lows = detectAlerts(grid, P, 5).filter((a) => a.type === 'lowcash')
    expect(lows).toEqual([])                       // 最低 closing=5，阈值 5 → 不报
    const lows2 = detectAlerts(grid, P, 10).filter((a) => a.type === 'lowcash')
    expect(lows2.map((a) => a.period)).toEqual(['2026-09'])
  })
  it('空网格/空期间返回空', () => {
    expect(detectAlerts(null, P)).toEqual([])
    expect(detectAlerts(grid, [])).toEqual([])
  })
})

describe('summarizeAlerts', () => {
  it('分类汇总缺口/低现金的数量、首月与最严重月', () => {
    const s = summarizeAlerts(detectAlerts(grid, P, 10))
    expect(s.total).toBe(3)
    expect(s.gap.count).toBe(2)
    expect(s.gap.first).toBe('2026-09')
    expect(s.gap.worst.value).toBe(-40)
    expect(s.lowcash.count).toBe(1)
    expect(s.lowcash.worst.period).toBe('2026-09')
  })
  it('无预警时两类均为 null', () => {
    const s = summarizeAlerts([])
    expect(s.total).toBe(0)
    expect(s.gap).toBeNull()
    expect(s.lowcash).toBeNull()
  })
})
