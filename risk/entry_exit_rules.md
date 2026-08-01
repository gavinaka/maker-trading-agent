# 入场与出场规则

## 入场规则

### 左侧入场（主要方式）
- 在目标区间提前限价挂单
- 不等待K线确认，接受不确定性
- 优先使用
- 风险：可能被精准止损猎杀
- 仓位：正式计划必须按 2–5 档 `ladder` 分批入场，各档比例明确且合计 100%；禁止一次性单价或代表价冒充区间
- 使用策略类型：Maker / 左侧 / 高空 / 低多 / 反弹空
- 止损：同账户 `invalidation_path` 只从本轮 TradingView 4H/1H/15m timeframe-bearing zone 选择可机械定位、严格位于入场区与全部挂单价外侧的真正失效锚。合法锚仅为 readable `user_drawn_manual_only` 手绘 profile 中性上/下外沿，或非当前入场区的 structure zone 外沿；空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`。裸支撑/阻力/摆动数组只供展示，禁止补周期后充当锚；不强制最近数值层，不得强用弱中间结构。同一 `invalidation_path` 在 reasoning 阶段必须密封 exact `structural-noise-buffer-v2`；`certified` 必须绑定可达的本轮 TradingView observation、`4h|1h|15m`、同周期截图、可机械定位锚、图上 `noise_outer_boundary`、正 `price_distance` 与 `risk_budget_input_used=false`，最终 stop 严格越过该边界。证据不足只允许 `insufficient`、闭合原因、空数值 owner 与 `observe`。decision 中存在的 stop-basis identity/anchor/distance 必须精确等于 reasoning owner，Gate 另读 status、截图与 boundary 验证；结构止损后才验证全部成交组合的 3% 与 TP1 1:2.5，失败时调整阶梯或观望，禁止固定点数、ATR、风险倒推或压缩，compiler 不得推断
- 浮盈防守：遵循两层防守结构（第一层动态止损 → 第二层保本损）；仓位扣减只发生在止盈档
- 注意事项：订单生命周期由 current price、全部 entries 与 cancel price 确定性派生；只有 cancel 位于触达 entries 的反方向分支才存在合法 `fillable` 路径。同向且更近为 `cancel_blocks_all_entries`，同向且更远为 `entry_before_cancel`，碰撞或混合侧为 `invalid_geometry`；实际 `fill_probability=null`，不得由价格触达概率猜测

### 右侧入场（辅助方式）
- 等待价格行为确认后入场
- 适用于趋势延续或结构突破确认
- 胜率高，但入场成本较差
- 仓位：短线为主，实时盯盘
- 使用策略类型：Maker / 右侧 / 高空 / 低多 / 反弹空
- 止损：与左侧相同，只允许本轮 TradingView 4H/1H/15m 的 readable 手绘 profile 中性上/下外沿或非当前入场区 structure zone 外沿，并遵守空单 `resistance|breakdown_retest`、多单 `support|breakout_retest` 的 role 约束；裸支撑/阻力/摆动数组只供展示。右侧确认后仍由同账户 `invalidation_path` 密封同一 exact `structural-noise-buffer-v2`：`certified` 必须绑定同周期截图、锚与可见 `noise_outer_boundary`，stop 严格越界；证据不足只可 `insufficient + observe`。确认 K 线、固定点数、ATR、3% 或 R:R 均不得生成或压缩 buffer；decision 中存在的 stop-basis 字段须与 reasoning owner 精确一致，Gate 独立校验 status/visual/boundary，compiler 不推断。确认区边界本身不能单独拥有止损
- 浮盈防守：遵循两层防守结构；第一层止损价只能由成交后后续确认的 4H K 线结构性极点动态确定
- 注意事项：右侧确认不免除 `maker-order-lifecycle-v1`；不存在合法 fill/cancel 路径时仍必须 `observe`

---

## 出场规则

### 优先级
1. 盈亏比（R值，1.5R / 2.5R）
2. 胜率（非核心决策变量，但作为参考）

> ⚠️ 此「胜率非核心决策变量」仅指**离场/选单**的优化优先级，**不等于**入场门槛：开单前置硬门槛「胜率自估 ≥60%」（与总评分≥65 并列）仍须先满足才允许开单。两阶段不矛盾。

### TP1/TP2层级出场
- TP1：默认减仓 50%，剩余仓位继续执行防守计划
- TP2：清理剩余仓位
- 剩余仓位：动态管理，第一层只移至成交后后续形成并确认的 4H 极点，第二层只设保本损

### 注意事项
- 每笔计划必须有明确取消价格，并通过 `maker-order-lifecycle-v1` 验证整条 current→entry/cancel 路径
- 只有 lifecycle 为 `fillable` 时才存在合法成交分支；`cancel_blocks_all_entries|entry_before_cancel|invalid_geometry` 均不得执行，实际成交概率保持 N/A
- 不得因为个人判断擅自修改入场或出场
- 所有执行必须遵循每日Plan、风控检核及状态门禁
