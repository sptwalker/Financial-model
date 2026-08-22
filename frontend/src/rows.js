// 网格行显示配置：分组、顺序、单位、是否可编辑（输入行可编辑，引擎行只读）
export const ROW_GROUPS = [
  {
    name: '销量（万台）',
    rows: [
      { key: 'qty.online', label: '线上销量', unit: '万台', editable: true },
      { key: 'qty.offline', label: '线下销量', unit: '万台', editable: true },
      { key: 'qty.total', label: '总销量', unit: '万台', editable: false },
    ],
  },
  {
    name: '销售额（万元）',
    rows: [
      { key: 'sale.online.amount', label: '线上销售额', editable: false },
      { key: 'sale.offline.amount', label: '线下销售额', editable: false },
      { key: 'sale.accessory.amount', label: '配件收入', editable: false },
      { key: 'sale.subscription.amount', label: '订阅收入', editable: false },
      { key: 'sale.total.amount', label: '销售额合计', editable: false },
    ],
  },
  {
    name: '回款（万元）',
    rows: [
      { key: 'collect.online', label: '线上回款', editable: false },
      { key: 'collect.offline', label: '线下回款', editable: false },
      { key: 'collect.subscription', label: '订阅回款', editable: false },
      { key: 'collect.total', label: '回款合计', editable: false },
    ],
  },
  {
    name: '采购（万元）',
    rows: [
      { key: 'purchase.main', label: '整机采购付款', editable: false },
      { key: 'purchase.accessory', label: '配件采购付款', editable: false },
      { key: 'purchase.total', label: '采购合计', editable: false },
    ],
  },
  {
    name: '费用（万元）',
    rows: [
      { key: 'exp.salary', label: '工资', editable: true },
      { key: 'exp.game_dev', label: '游戏外包开发', editable: true },
      { key: 'exp.commercial_ip', label: '商业IP', editable: true },
      { key: 'exp.license', label: '版号', editable: true },
      { key: 'exp.office_hw', label: '办公硬件', editable: true },
      { key: 'exp.it_service', label: '信息技术服务', editable: true },
      { key: 'exp.rent', label: '房租', editable: true },
      { key: 'exp.recruit', label: '招聘费', editable: true },
      { key: 'exp.office_other', label: '办公及其他', editable: true },
      { key: 'exp.brand', label: '品牌宣传', editable: true },
      { key: 'exp.channel_commission', label: '渠道佣金', editable: true },
      { key: 'exp.channel_promo', label: '渠道推广费', editable: true },
      { key: 'exp.online_promo', label: '线上推广费', editable: true },
      { key: 'exp.total', label: '费用合计', editable: false },
    ],
  },
  {
    name: '投融资（万元）',
    rows: [
      { key: 'cash.financing', label: '到账融资款', editable: true },
    ],
  },
  {
    name: '现金（万元）',
    rows: [
      { key: 'cash.opening', label: '期初现金', editable: true },
      { key: 'cash.incoming', label: '回款流入', editable: false },
      { key: 'cash.expense', label: '支出（费用+采购）', editable: false },
      { key: 'cash.gap', label: '资金缺口', editable: false },
      { key: 'cash.closing', label: '期末现金', editable: false },
    ],
  },
]

export const ALL_ROW_KEYS = ROW_GROUPS.flatMap((g) => g.rows.map((r) => r.key))

// 预算页成本重分组（研发/营销/运营管理）——独立于 ROW_GROUPS，不影响看板/全表
export const BUDGET_COST_GROUPS = [
  {
    name: '研发',
    rows: [
      { key: 'exp.game_dev', label: '游戏外包开发' },
      { key: 'exp.commercial_ip', label: '商业IP' },
      { key: 'exp.license', label: '版号' },
    ],
  },
  {
    name: '营销',
    rows: [
      { key: 'exp.brand', label: '品牌宣传' },
      { key: 'exp.channel_commission', label: '渠道佣金' },
      { key: 'exp.channel_promo', label: '渠道推广费' },
      { key: 'exp.online_promo', label: '线上推广费' },
    ],
  },
  {
    name: '运营管理',
    rows: [
      { key: 'exp.salary', label: '人力（工资）' },
      { key: 'exp.headcount', label: '人数' },
      { key: 'exp.rent', label: '房租' },
      { key: 'exp.office_hw', label: '办公硬件' },
      { key: 'exp.it_service', label: '信息技术服务' },
      { key: 'exp.recruit', label: '招聘费' },
      { key: 'exp.office_other', label: '办公及其他' },
    ],
  },
]

// 预算页销售设置：分渠道销量（inputs）+ 售价/采购成本标量（params）
export const BUDGET_SALES_QTY = [
  { key: 'qty.online', label: '线上销量', unit: '万台' },
  { key: 'qty.offline', label: '线下销量', unit: '万台' },
]
export const BUDGET_SALES_PARAMS = [
  { key: 'price_online', label: '线上平均售价（元/台）', step: '1' },
  { key: 'price_offline', label: '线下平均售价（元/台）', step: '0.01' },
  { key: 'cost_main', label: '整机采购成本（元/台）', step: '1' },
  { key: 'cost_accessory', label: '单台配件采购成本（元）', step: '1' },
]

export function rowInfo(key) {
  for (const g of ROW_GROUPS) {
    const r = g.rows.find((x) => x.key === key)
    if (r) return { ...r, group: g.name }
  }
  return null
}

// 参数页配置：字段名 → 显示名/说明（引擎 Params 字段）
export const PARAM_FIELDS = [
  { key: 'price_online', label: '线上售价（元/台）', step: '1' },
  { key: 'price_offline', label: '线下售价（元/台）', step: '0.01' },
  { key: 'cost_main', label: '整机采购成本（元/台）', step: '1' },
  { key: 'cost_accessory', label: '单台配件采购成本（元）', step: '1' },
  { key: 'acc_ratio', label: '配件销售占比', step: '0.01', hint: '每台 × 配件占比 × 200 元配件收入' },
  { key: 'acc_revenue_per_unit', label: '单台配件收入（元）', step: '1' },
  { key: 'sub_ratio', label: '订阅比例', step: '0.01', hint: '累计装机 × 订阅比例 × 200' },
  { key: 'sub_revenue_per_unit', label: '单台订阅收益（元）', step: '1' },
  { key: 'channel_commission_rate', label: '渠道佣金费率', step: '0.001', hint: '= 线下销售 × 费率' },
  { key: 'purchase_lag', label: '采购付款账期（N+M）', step: '1', hint: '2 = N+2，3 = N+3' },
]

export const CASH_COLORS = {
  'sale.online.amount': '#4f8cff',
  'sale.offline.amount': '#5ad8a6',
  'sale.accessory.amount': '#f6bd16',
  'sale.subscription.amount': '#9254de',
}

// 预测方法阶梯（与后端 forecast_service.MIN_* 门槛一致；min=解锁所需有效历史月数）
export const FORECAST_METHODS = [
  { key: 'plan_anchored', label: '计划锚定', min: 0, hint: '以计划曲线为形状，实际出货校准水平' },
  { key: 'seasonal_naive', label: '季节朴素', min: 12, hint: '同月最近一次观测' },
  { key: 'holt_winters', label: 'Holt-Winters', min: 24, hint: '三重指数平滑（需安装 statsmodels）' },
  { key: 'sarima', label: 'SARIMA', min: 36, hint: '差分自回归（未启用）' },
]

// 三情景配色（看板对比 / 预测页共用）
export const SCENARIO_COLORS = {
  base: '#4f8cff',
  lower: '#f6bd16',
  upper: '#00b578',
}
