/**
 * scenario.js 纯逻辑测试：情景销量系数换算
 *
 * 对比页把「乐观 +20%」改成「+35%」时，送引擎的必须是相对系数（目标/当前实际），
 * 否则会在已含 1.2 的情景上叠乘成 1.62（实测过 1.3× 送进去会变成 1.56×）。
 * 这里锁死换算、夹取与「未改动不覆盖」三点。
 */
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_OPTIMISTIC, DEFAULT_PESSIMISTIC, FACTOR_MAX, FACTOR_MIN,
  clampFactor, factorPct, relativeFactor, scaleOverride, scenarioKind,
} from '../scenario'

describe('scenarioKind', () => {
  it('识别乐观/悲观，中性与其他方案不参与调节', () => {
    expect(scenarioKind('乐观')).toBe('optimistic')
    expect(scenarioKind('悲观方案')).toBe('pessimistic')
    expect(scenarioKind('中性')).toBeNull()
    expect(scenarioKind('自定义 A')).toBeNull()
    expect(scenarioKind(null)).toBeNull()
  })
})

describe('clampFactor', () => {
  it('百分比转系数', () => {
    expect(clampFactor(20)).toBeCloseTo(1.2)
    expect(clampFactor(-20)).toBeCloseTo(0.8)
    expect(clampFactor(0)).toBe(1)
  })
  it('超出上下限时夹取', () => {
    expect(clampFactor(999)).toBe(FACTOR_MAX)
    expect(clampFactor(-99)).toBe(FACTOR_MIN)
  })
  it('非法输入回落到 1', () => {
    expect(clampFactor('abc')).toBe(1)
    expect(clampFactor(NaN)).toBe(1)
    expect(clampFactor(undefined)).toBe(1)
  })
})

describe('factorPct', () => {
  it('系数转百分比（回显用）', () => {
    expect(factorPct(1.2)).toBeCloseTo(20)
    expect(factorPct(0.8)).toBeCloseTo(-20)
    expect(factorPct(1)).toBe(0)
  })
  it('非法输入回落 0', () => {
    expect(factorPct(undefined)).toBe(0)
    expect(factorPct('x')).toBe(0)
  })
})

describe('relativeFactor', () => {
  it('相对当前实际系数换算（关键：不叠乘）', () => {
    expect(relativeFactor(1.2, 1.35)).toBeCloseTo(1.125)   // 已含 1.2 → 再 ×1.125 = 1.35
    expect(relativeFactor(0.8, 0.7)).toBeCloseTo(0.875)    // 已含 0.8 → 再 ×0.875 = 0.7
  })
  it('当前系数等于目标时为 1', () => {
    expect(relativeFactor(1.2, 1.2)).toBeCloseTo(1)
  })
  it('当前值缺失/为 0 时按 1 处理，避免除零', () => {
    expect(relativeFactor(undefined, 1.3)).toBeCloseTo(1.3)
    expect(relativeFactor(0, 1.3)).toBeCloseTo(1.3)
    expect(relativeFactor('', 1.3)).toBeCloseTo(1.3)
  })
})

describe('scaleOverride', () => {
  it('换算成引擎 params 覆盖', () => {
    expect(scaleOverride(1.2, 1.35)).toEqual({ qty_scale: '1.125' })
  })
  it('未改动（≈1）返回 null —— 直接用存档网格，省一次重算', () => {
    expect(scaleOverride(1.2, 1.2)).toBeNull()
    expect(scaleOverride(1, 1)).toBeNull()
  })
  it('结果不含浮点噪声', () => {
    expect(scaleOverride(0.8, 0.7)).toEqual({ qty_scale: '0.875' })
  })
})

describe('默认值', () => {
  it('默认乐观 +20% / 悲观 -20%', () => {
    expect(DEFAULT_OPTIMISTIC).toBe(1.2)
    expect(DEFAULT_PESSIMISTIC).toBe(0.8)
    expect(factorPct(DEFAULT_OPTIMISTIC)).toBeCloseTo(20)
    expect(factorPct(DEFAULT_PESSIMISTIC)).toBeCloseTo(-20)
  })
})
