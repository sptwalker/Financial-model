/**
 * alerts.js 测试：现金流预警检测与汇总
 *
 * 预警只看期末现金 closing<minCash（反映账户未来实际现金）。阈值边界（恰好等于阈值
 * 不报警）和最严重月的选取是预警可信度的核心，算错会漏报或误报安全月，故单测锁死。
 */
import { describe, expect, it } from 'vitest'
import { detectAlerts, summarizeAlerts } from '../alerts'

const P = ['2026-08', '2026-09', '2026-10', '2026-11']
const grid = {
  cells: {
    'cash.closing': { '2026-08': { value: '100' }, '2026-09': { value: '5' }, '2026-10': { value: '80' }, '2026-11': { value: '200' } },
  },
}

describe('detectAlerts', () => {
  it('低现金按阈值判定，恰好等于阈值不报警', () => {
    expect(detectAlerts(grid, P, 5)).toEqual([])   // 最低 closing=5，阈值 5 → 不报
    const lows = detectAlerts(grid, P, 10)
    expect(lows.map((a) => a.period)).toEqual(['2026-09'])
    expect(lows[0].type).toBe('lowcash')
  })
  it('空网格/空期间返回空', () => {
    expect(detectAlerts(null, P)).toEqual([])
    expect(detectAlerts(grid, [])).toEqual([])
  })
})

describe('summarizeAlerts', () => {
  it('汇总低现金的数量、首月与最严重月', () => {
    const s = summarizeAlerts(detectAlerts(grid, P, 10))
    expect(s.total).toBe(1)
    expect(s.lowcash.count).toBe(1)
    expect(s.lowcash.first).toBe('2026-09')
    expect(s.lowcash.worst.period).toBe('2026-09')
    expect(s.lowcash.worst.value).toBe(5)
  })
  it('无预警时 lowcash 为 null', () => {
    const s = summarizeAlerts([])
    expect(s.total).toBe(0)
    expect(s.lowcash).toBeNull()
  })
})
