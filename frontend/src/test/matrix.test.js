import { describe, it, expect } from 'vitest'
import { FACTORS, cellValue, colorDomain, pctLabel } from '../matrix'

describe('matrix', () => {
  it('FACTORS 覆盖 ±30% 共 7 档', () => {
    expect(FACTORS).toEqual([0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3])
  })

  it('cellValue: min 取全期最低，月模式取该月', () => {
    const closing = [100, 20, 80, -5]
    expect(cellValue(closing, 'min')).toBe(-5)
    expect(cellValue(closing, 'month', 2)).toBe(80)
    expect(cellValue([], 'min')).toBe(null)
  })

  it('colorDomain: 安全水位居中，两侧对称', () => {
    const dom = colorDomain([-200, 50, 300], 100)  // 偏移 300/50/200 → R=300
    expect(dom).toEqual({ min: -200, max: 400 })
  })

  it('colorDomain: 全等时不塌缩', () => {
    expect(colorDomain([100, 100], 100)).toEqual({ min: 99, max: 101 })
  })

  it('pctLabel', () => {
    expect(pctLabel(1)).toBe('基线')
    expect(pctLabel(1.3)).toBe('+30%')
    expect(pctLabel(0.7)).toBe('-30%')
  })
})
