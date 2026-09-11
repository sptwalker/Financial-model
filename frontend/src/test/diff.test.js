/**
 * diff.js 测试：版本快照对比的差异计算
 *
 * 这段逻辑决定"复盘"里哪些格被高亮、Δ 显示多少 —— 阈值定错会满屏假高亮
 * 或漏掉真变化，且只有人能判断对错，故逐条锁死。
 */
import { describe, expect, it } from 'vitest'
import { cellDelta, rowDelta } from '../diff'

const A = { cells: { 'qty.online': { '2026-08': { value: '3.00' }, '2026-09': { value: '5.00' } } } }
const B = { cells: { 'qty.online': { '2026-08': { value: '3.004' }, '2026-09': { value: '4.00' } } } }

describe('cellDelta', () => {
  it('取两网格同格数值并算差', () => {
    expect(cellDelta(A, B, 'qty.online', '2026-09')).toMatchObject({ a: 5, b: 4, delta: 1, changed: true })
  })

  it('|Δ|<0.005 视为未变（抹掉两位小数下的浮点噪声）', () => {
    expect(cellDelta(A, B, 'qty.online', '2026-08').changed).toBe(false)
  })

  it('缺失格按 0 处理，不抛异常', () => {
    expect(cellDelta(A, B, '不存在', '2099-01')).toEqual({ a: 0, b: 0, delta: 0, changed: false })
    expect(cellDelta(null, undefined, 'qty.online', '2026-08')).toMatchObject({ a: 0, b: 0 })
  })
})

describe('rowDelta', () => {
  it('按期间集合求整行合计差', () => {
    const r = rowDelta(A, B, 'qty.online', ['2026-08', '2026-09'])
    expect(r.a).toBe(8)
    expect(r.b).toBeCloseTo(7.004, 6)
    expect(r.changed).toBe(true)
  })

  it('空期间集合 → 全 0 未变', () => {
    expect(rowDelta(A, B, 'qty.online', [])).toEqual({ a: 0, b: 0, delta: 0, changed: false })
  })
})
