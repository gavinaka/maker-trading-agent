# 入场模型（图谱第六节）

> 本文件定义入场模式的细节规则。
> 与 `risk/entry_exit_rules.md` 互补：本文聚焦"模式"，那边聚焦"决策"。

---

## 两种入场模式

| 模式 | 别名 | 触发逻辑 | 优先级 |
|---|---|---|---|
| **左侧** | 提前限价挂单 | 在目标区间提前挂单，不等 K 线确认 | **主要方式** |
| **右侧** | 价格行为确认入场 | 等待 K 线确认后入场（趋势延续 / 结构突破） | 辅助方式 |

---

## 左侧入场（图谱第六节）

### 执行逻辑
1. 在目标区间**提前限价挂单**
2. **不等待**确认 K 线
3. **接受不确定性**

### 特点
- 优先使用
- 风险：可能被精准止损猎杀（2026.2 曾遭遇多次）
- 适合：盘口分数高 + 结构清晰 + 防守逻辑明确

### 仓位执行
- 正式可执行 Maker 计划只允许 `ladder`：在同一目标价格区间离散为 **2 至 5 个真实不同价位**，逐档写明比例且合计 100%。
- 50% + 50% 只是合法的两档示例，不是固定模板；档数与比例必须由本轮证据和全部非空成交组合的风险验算确定。
- 不存在强信号例外：当前 production 盘口最高 60；未来即使原生结构化证明能力获批启用并确认 70 分极端组合，也禁止 `single`、代表价、单点或单一价位一次性 100% 入场。

### 适用策略类型
- Maker / 左侧 / 高空
- Maker / 左侧 / 低多
- Maker / 左侧 / 反弹空

### 止损位
- 由同账户 `invalidation_path` 只从本轮 TradingView 4H/1H/15m timeframe-bearing zone 选择可机械定位且严格位于入场区与全部挂单价外侧的真正失效锚。合法锚仅为 readable `user_drawn_manual_only` 手绘 profile 中性上/下外沿，或非当前入场区 structure zone 外沿；空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`。裸支撑/阻力/摆动数组只供展示，禁止补周期后充当锚；不强制数值最近层，不得强用弱中间结构。该 `invalidation_path` 必须在 reasoning 阶段密封 exact `structural-noise-buffer-v2`：`certified` 绑定可达的本轮 TradingView observation、`4h|1h|15m`、同周期截图、可机械定位锚、图上 `noise_outer_boundary`、正 `price_distance` 与 `risk_budget_input_used=false`，stop 严格越过该边界；证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis identity/anchor/distance 必须精确等于 reasoning owner，Gate 另读 status/visual/boundary，compiler 不推断。buffer 不是固定点数、ATR 或风险预算倒推公式，挂单区边界本身不能单独充当止损依据
- 结构止损确定后再枚举全部成交组合，必须满足 Maker 5x 名义风险 ≤3% 与 TP1 R:R≥1:2.5；不合格时调整阶梯或观望，禁止压缩结构止损过门

### 浮盈防守
- 仅两层：报告前按计划全档加权锚和全部非空成交组合分别生成两层阿拉伯数字精确触发价，保留原始值、取整规则/步长与最终价；成交后按 actual weighted fill 重算唯一值。多单向上加 1.5R/2R，空单向下减 1.5R/2R，禁止 `+/-` 或 `±`。第一层触发后使用成交后后续形成并确认的 4H 极点移动止损并取消加仓；第二层触发后只移至实际加权成交价保本。
- 防守层不减仓；仓位扣减只发生在 TP1 精确减仓 50% 与 TP2 清理剩余 50%。
- 详见 `risk/floating_defense.md`

### 注意事项
- 必含“取消价格”及 Gate 派生的 `maker-order-lifecycle-v1`
- 只有 cancel 位于 current→entries 的反方向分支才为 `fillable`；同向更近 `cancel_blocks_all_entries`、同向更远 `entry_before_cancel`、碰撞/混合侧 `invalid_geometry` 均不得执行；实际 `fill_probability=null`
- 已触发取消未取消 → V012 违规

---

## 右侧入场（图谱第六节）

### 执行逻辑
1. **等待价格行为确认**后入场
2. 适用于趋势延续 / 结构突破确认

### 特点
- 胜率更高
- 入场成本更差
- 适合：盘口分数中 + 结构突破中

### 仓位执行
- 短线为主，等待右侧确认后重新定义当前可执行价格区间。
- 确认后仍须生成 2 至 5 档 `ladder`，各档价格真实不同、比例合计 100%；确认 K 线或当前价格本身不能成为单点订单。
- 若确认后无法形成满足全部成交情景 R:R 与风险约束的 `ladder`，则不下单；不得退化为一次入场。

### 适用策略类型
- Maker / 右侧 / 高空
- Maker / 右侧 / 低多
- Maker / 右侧 / 反弹空

### 止损位
- 与左侧相同：只允许本轮 TradingView 4H/1H/15m 的 readable 手绘 profile 中性上/下外沿或非当前入场区 structure zone 外沿，并遵守空单 `resistance|breakdown_retest`、多单 `support|breakout_retest` 的 role 约束；裸支撑/阻力/摆动数组只供展示。同账户 `invalidation_path` 必须在 reasoning 阶段密封同一 exact `structural-noise-buffer-v2`；`certified` 必须绑定同周期截图、锚、可见 `noise_outer_boundary` 且 stop 严格越界，证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis 字段必须精确等于 reasoning owner，Gate 另读 status/visual/boundary；右侧确认、固定点数、ATR、3% 与 R:R 均不得生成或压缩 buffer，compiler 不推断。确认区边界本身不是充分止损依据

### 浮盈防守
- 与左侧完全相同，仅使用两层止损保护；真实成交前也必须展示计划锚及全部成交组合的两层精确触发价，成交后再以 actual weighted fill 替换为唯一值。

### 注意事项
- 必含“取消价格”并通过与左侧相同的 `maker-order-lifecycle-v1`；右侧确认不构成生命周期豁免

---

## 入场模式选择决策树

```
当前评分 ≥ 65？
├─ 否 → 强制观望（不入场）
└─ 是
    ├─ 当前 production 盘口是否为 0–60 内的高质量强信号？（70 为未来保留且当前不可用）
    │   ├─ 是 → 再按结构位置选择左侧/右侧，不因分数跳过区间与风险合同
    │   └─ 否
    │       ├─ 盘面结构突破中？
    │       │   ├─ 是 → 右侧（等确认）
    │       │   └─ 否 → 左侧（提前布局）
    │       └─ 持仓周期？
    │           ├─ 长持 → 左侧（接受不确定性）
    │           └─ 短线 → 右侧（更精准）
```

---

## 历史权重监控（图谱十七节 Q3）

review_agent 每日 Q3 跟踪：
- 本日左侧入场笔数
- 本日右侧入场笔数
- 最近 7 日趋势：左→右偏移 / 右→左偏移 / 持平

→ 偏移可能反映：
- 市场结构变化（趋势 vs 震荡）
- 个人心态变化（保守 vs 激进）

→ 周报必须分析此趋势。

---

## 禁止行为

* 禁止无计划入场（直接 V008 / V013 违规）
* 禁止"看到价格了就先挂着"（不算左侧，算追单）
* 禁止已挂单超时未触发就追加（属于"被动加速"V009）
* 禁止右侧入场后还想"反向追单"
* 禁止入场后立即修改止损（V001 移动止损违规）
