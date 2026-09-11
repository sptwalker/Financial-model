// 版本快照对比（复盘）：两份网格里同一格的差异。
// 值单位为万元、展示两位小数，故 |Δ|<0.005 视为无变化（抹掉四舍五入/浮点噪声）。
export function cellDelta(a, b, key, period) {
  const va = Number(a?.cells?.[key]?.[period]?.value ?? 0)
  const vb = Number(b?.cells?.[key]?.[period]?.value ?? 0)
  const delta = va - vb
  return { a: va, b: vb, delta, changed: Math.abs(delta) >= 0.005 }
}

// 一整行在给定期间集合上的合计差异（复盘卡片/整行高亮用）
export function rowDelta(a, b, key, periods) {
  let sa = 0, sb = 0
  for (const p of periods) {
    sa += Number(a?.cells?.[key]?.[p]?.value ?? 0)
    sb += Number(b?.cells?.[key]?.[p]?.value ?? 0)
  }
  return { a: sa, b: sb, delta: sa - sb, changed: Math.abs(sa - sb) >= 0.005 }
}
