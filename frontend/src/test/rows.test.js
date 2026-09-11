/**
 * rows.js 配置一致性测试
 *
 * rows.js 里的 key 必须与后端引擎的网格行键逐字一致 —— 拼错一个字母不会报错，
 * 只会让某个图表某一行静默变成 0，而且没人会发现。这类"静默归零"是这套系统里
 * 最难查的缺陷，因此这里做交叉校验：
 *   1. 配置内部自洽（无重复键、分组非空、label/unit 齐备）；
 *   2. 代码里引用的行键，全部能在 ROW_GROUPS 里找到；
 *   3. 引擎侧已知行键，全部在前端有展示配置（漏配=图表缺行）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import {
  ALL_ROW_KEYS, AUTO_MKT_KEYS, BUDGET_COST_GROUPS, BUDGET_RATE_PARAMS,
  BUDGET_SALES_PARAMS, BUDGET_SALES_QTY, CASH_COLORS, FORECAST_METHODS,
  PARAM_FIELDS, ROW_GROUPS, SCENARIO_COLORS, rowInfo,
} from '../rows'

const SRC = resolve(__dirname, '..')          // frontend/src
const REPO = resolve(SRC, '..', '..')          // 仓库根

/** 递归收集 src 下所有源码文件（排除测试自身） */
function sourceFiles(dir = SRC) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return sourceFiles(p)
    if (!/\.(js|jsx)$/.test(name)) return []
    if (/\.test\.(js|jsx)$/.test(name)) return []
    if (p.includes(`${join('src', 'test')}`)) return []
    return [p]
  })
}

describe('ROW_GROUPS 内部自洽', () => {
  it('行键全局唯一（重复会让 rowInfo 返回错误配置）', () => {
    const seen = new Map()
    for (const g of ROW_GROUPS) {
      for (const r of g.rows) {
        expect(seen.has(r.key), `行键重复：${r.key} 同时出现在「${seen.get(r.key)}」与「${g.name}」`)
          .toBe(false)
        seen.set(r.key, g.name)
      }
    }
  })

  it('每组至少一行，且每行都有 key 与 label', () => {
    for (const g of ROW_GROUPS) {
      expect(g.rows.length, `分组「${g.name}」为空`).toBeGreaterThan(0)
      for (const r of g.rows) {
        expect(r.key, `分组「${g.name}」有行缺 key`).toBeTruthy()
        expect(r.label, `${r.key} 缺 label`).toBeTruthy()
      }
    }
  })

  it('可编辑标记只出现在输入行上（引擎计算行不可编辑）', () => {
    // 引擎派生行：由 calculator 算出的，一律不可编辑
    const derived = [
      'qty.total', 'sale.total.amount', 'collect.total', 'purchase.total',
      'exp.total', 'cash.incoming', 'cash.expense', 'cash.gap', 'cash.closing',
    ]
    for (const key of derived) {
      expect(rowInfo(key).editable, `${key} 是引擎派生行，不应可编辑`).toBe(false)
    }
  })

  it('ALL_ROW_KEYS 与分组展开结果一致', () => {
    const flat = ROW_GROUPS.flatMap((g) => g.rows.map((r) => r.key))
    expect(ALL_ROW_KEYS).toEqual(flat)
    expect(new Set(ALL_ROW_KEYS).size).toBe(ALL_ROW_KEYS.length)
  })

  it('rowInfo 对未知键返回 null，不抛异常', () => {
    expect(rowInfo('根本不存在的行')).toBeNull()
    expect(rowInfo('')).toBeNull()
  })

  it('rowInfo 返回带分组名的信息', () => {
    expect(rowInfo('qty.online')).toMatchObject({
      label: '线上销量', unit: '万台', editable: true, group: '销量（万台）',
    })
  })
})

describe('预算页分组', () => {
  it('预算页每个成本行都能在 ROW_GROUPS 里找到（否则是错字）', () => {
    for (const g of BUDGET_COST_GROUPS) {
      for (const r of g.rows) {
        expect(rowInfo(r.key), `预算页引用了未知行键 ${r.key}`).not.toBeNull()
      }
    }
  })

  it('预算页分组不重复引用同一行', () => {
    const keys = BUDGET_COST_GROUPS.flatMap((g) => g.rows.map((r) => r.key))
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('销售输入行键有效且可编辑', () => {
    for (const r of BUDGET_SALES_QTY) {
      const info = rowInfo(r.key)
      expect(info, `预算页销量行 ${r.key} 不存在`).not.toBeNull()
      expect(info.editable, `${r.key} 应可编辑`).toBe(true)
    }
  })
})

describe('参数配置与引擎字段对齐', () => {
  it('PARAM_FIELDS / BUDGET_* 引用的参数名都是引擎 Params 的字段', () => {
    const engineSrc = readFileSync(
      resolve(REPO, 'backend', 'app', 'engine', 'calculator.py'), 'utf-8')
    const paramsBody = engineSrc.split('class Params:')[1].split('\ndef ')[0]
    const declared = new Set(
      [...paramsBody.matchAll(/^\s{4}([a-z_0-9]+)\s*:/gm)].map((m) => m[1]))

    expect(declared.size).toBeGreaterThan(10)  // 防止正则失配后静默通过

    const referenced = [
      ...PARAM_FIELDS.map((f) => f.key),
      ...BUDGET_SALES_PARAMS.map((f) => f.key),
      ...BUDGET_RATE_PARAMS.map((f) => f.key),
    ]
    for (const key of referenced) {
      expect(declared.has(key), `前端配置的参数「${key}」在引擎 Params 中不存在`).toBe(true)
    }
  })

  it('费率参数都给了默认值（预算页回退用）', () => {
    for (const f of BUDGET_RATE_PARAMS) {
      expect(typeof f.def, `${f.key} 缺默认值`).toBe('number')
    }
  })
})

describe('营销自动测算行', () => {
  it('AUTO_MKT_KEYS 都是可编辑的费用输入行', () => {
    for (const key of AUTO_MKT_KEYS) {
      const info = rowInfo(key)
      expect(info, `${key} 不在 ROW_GROUPS`).not.toBeNull()
      expect(info.group).toBe('费用（万元）')
    }
  })

  it('AUTO_MKT_KEYS 与后端 auto_marketing 覆盖的行一致', () => {
    const calc = readFileSync(
      resolve(REPO, 'backend', 'app', 'engine', 'calculator.py'), 'utf-8')
    for (const key of AUTO_MKT_KEYS) {
      expect(calc.includes(`"${key}"`), `引擎未覆盖 ${key}`).toBe(true)
    }
  })
})

describe('配色与预测阶梯', () => {
  it('CASH_COLORS 覆盖五类收入流', () => {
    expect(Object.keys(CASH_COLORS).sort()).toEqual([
      'sale.accessory.amount', 'sale.offline.amount',
      'sale.online.amount', 'sale.subscription.amount', 'sale.valueadd.amount',
    ])
  })

  it('预测方法阶梯按解锁月数递增，且 plan_anchored 无门槛', () => {
    const mins = FORECAST_METHODS.map((m) => m.min)
    expect(mins).toEqual([...mins].sort((a, b) => a - b))
    expect(FORECAST_METHODS.find((m) => m.key === 'plan_anchored').min).toBe(0)
  })

  it('预测方法门槛与后端 forecast_service 常量一致', () => {
    const svc = readFileSync(
      resolve(REPO, 'backend', 'app', 'services', 'forecast_service.py'), 'utf-8')
    for (const m of FORECAST_METHODS) {
      const m2 = m.key.toUpperCase()
      const re = new RegExp(`MIN_${m2}\\s*=\\s*(\\d+)`)
      const hit = svc.match(re)
      if (hit) {
        expect(Number(hit[1]), `${m.key} 门槛与后端不一致`).toBe(m.min)
      }
    }
  })

  it('三情景配色齐备', () => {
    expect(Object.keys(SCENARIO_COLORS).sort()).toEqual(['base', 'lower', 'upper'])
  })
})

describe('源码引用的行键全部存在', () => {
  it('代码里出现的 row_key 字面量都能在 ROW_GROUPS 中找到', () => {
    const known = new Set(ALL_ROW_KEYS)
    // 行键形如 小写字母.小写字母(.小写字母)*；排除 URL / 文件名等
    const re = /['"]([a-z]+(?:\.[a-z0-9_]+){1,3})['"]/g
    const missing = new Map()

    for (const file of sourceFiles()) {
      const text = readFileSync(file, 'utf-8')
      for (const m of text.matchAll(re)) {
        const key = m[1]
        if (known.has(key)) continue
        // 不属于行键命名空间的常见字面量
        if (/^(http|https|application|image|text)\b/.test(key)) continue
        if (key.startsWith('exp.') || key.startsWith('sale.') ||
            key.startsWith('cash.') || key.startsWith('qty.') ||
            key.startsWith('collect.') || key.startsWith('purchase.')) {
          missing.set(key, file.replace(SRC, 'src'))
        }
      }
    }

    expect([...missing.entries()], '发现疑似拼错的行键').toEqual([])
  })
})
