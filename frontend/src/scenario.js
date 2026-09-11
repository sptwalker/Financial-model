// 对比页的情景销量系数调节逻辑。
//
// 三情景的销量差异在库里没有单一存放处：导入克隆把系数直接乘进了 qty 输入行
// （params.qty_scale 仍是 1），预算页保存则相反（qty 中性、系数写 qty_scale）。
// 所以「当前系数」由后端 /scenarios/{id}/scale 观测给出（factor），前端算相对系数：
// 目标系数 / 当前系数，再作为 params.qty_scale 覆盖送预览。直接送目标值会在
// 已含 1.2 的情景上叠乘成 1.62。

export const DEFAULT_OPTIMISTIC = 1.2
export const DEFAULT_PESSIMISTIC = 0.8
export const FACTOR_MIN = 0.5
export const FACTOR_MAX = 2

// 只认乐观/悲观，其余情景（中性、自定义方案）不参与系数调节
export function scenarioKind(name) {
  if (!name) return null
  if (name.includes('乐观')) return 'optimistic'
  if (name.includes('悲观')) return 'pessimistic'
  return null
}

// 百分比（-20 表示 -20%）→ 系数，夹到 [FACTOR_MIN, FACTOR_MAX]
export function clampFactor(pct) {
  const n = Number(pct)
  if (!Number.isFinite(n)) return 1
  const f = 1 + n / 100
  return Math.min(FACTOR_MAX, Math.max(FACTOR_MIN, f))
}

// 系数 → 百分比（用于回显输入框）
export function factorPct(factor) {
  const f = Number(factor)
  return Number.isFinite(f) ? (f - 1) * 100 : 0
}

// 相对系数：目标 / 当前实际系数；当前值缺失或非法按 1（避免除零与叠乘）
export function relativeFactor(currentFactor, targetFactor) {
  const cur = Number(currentFactor)
  const safe = Number.isFinite(cur) && cur !== 0 ? cur : 1
  return targetFactor / safe
}

// 送引擎的 params 覆盖：相对系数；≈1 时不覆盖（保持存档结果，省一次重算）
export function scaleOverride(currentFactor, targetFactor) {
  const rel = relativeFactor(currentFactor, targetFactor)
  return Math.abs(rel - 1) < 1e-9 ? null : { qty_scale: String(Number(rel.toFixed(6))) }
}
