// financing.js 测试：轮次 ↔ 引擎输入行的互转 + 迁移。
// 同月多轮必须相加（引擎只认逐期现金注入），空/零跳过；标注保留名称。
import { describe, expect, it } from 'vitest'
import { roundsToInput, migrateRounds, roundLabels } from '../financing'

describe('roundsToInput', () => {
  it('同月多轮相加、取整；空月/零额跳过', () => {
    expect(roundsToInput([
      { name: '天使', period: '2026-08', amount: 300 },
      { name: '朋友', period: '2026-08', amount: 50.4 },
      { name: 'A轮', period: '2027-03', amount: 500 },
      { name: '空', period: '', amount: 100 },
      { name: '零', period: '2027-06', amount: 0 },
    ])).toEqual({ '2026-08': '350', '2027-03': '500' })
  })
  it('空列表返回空对象', () => {
    expect(roundsToInput(null)).toEqual({})
  })
})

describe('migrateRounds', () => {
  it('从 cash.financing 行取非零月，占位名「融资」，按期排序', () => {
    expect(migrateRounds({ cells: { 'cash.financing': {
      '2027-03': { value: '500' }, '2026-08': { value: '300' }, '2026-09': { value: '0' },
    } } })).toEqual([
      { name: '融资', period: '2026-08', amount: 300 },
      { name: '融资', period: '2027-03', amount: 500 },
    ])
  })
  it('无网格返回空数组', () => {
    expect(migrateRounds(null)).toEqual([])
  })
})

describe('roundLabels', () => {
  it('名称+金额；同月多轮以 / 合并', () => {
    expect(roundLabels([
      { name: '天使', period: '2026-08', amount: 300 },
      { name: '朋友', period: '2026-08', amount: 50 },
      { name: '', period: '2027-03', amount: 500 },
    ])).toEqual({ '2026-08': '天使 300万 / 朋友 50万', '2027-03': '融资 500万' })
  })
})
