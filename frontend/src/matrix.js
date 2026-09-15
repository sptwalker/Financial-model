// 现金流矩阵：销量系数 × 研发成本系数 的笛卡尔积，每格重算一次得到全期各月期末现金。
// 纯逻辑：系数档位、格值提取、上色域。UI 负责发请求与渲染。金额单位：万元。

// ±30%，10% 一档 → 7 档（0.70 ~ 1.30）
export const FACTORS = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]

// 系数 → 展示标签：1=基线，其余显示相对增减
export const pctLabel = (f) => (f === 1 ? '基线' : `${f > 1 ? '+' : ''}${Math.round((f - 1) * 100)}%`)

// 某格的展示值：'min'=全期最低期末现金（默认主色）；否则取指定月下标的期末现金
export function cellValue(closing, mode, monthIdx) {
  if (!closing || !closing.length) return null
  if (mode === 'min') return Math.min(...closing)
  return closing[monthIdx] ?? null
}

// 上色域：把安全水位 minCash 锚在中点（黄），两侧对称 → 红=破水位越深，绿=越安全。
// R 取数据到水位的最大绝对偏移（至少 1，避免全相等时域塌缩）。
export function colorDomain(values, minCash) {
  const devs = values.filter((v) => v != null).map((v) => Math.abs(v - minCash))
  const R = Math.max(1, ...devs)
  return { min: minCash - R, max: minCash + R }
}
