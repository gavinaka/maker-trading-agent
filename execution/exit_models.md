# 出场模型（图谱第七节 + 二十节）

> 系统核心理念：**出场比入场更重要**。
> TP1 后的剩余仓位运行是关键（图谱二十节）。
> 与 `risk/floating_defense.md` 配合使用。
> 当前 vNext Maker 的执行真相以 `scoring/scoring_contract.json`、`risk/floating_defense.md` 与 `governance/vnext_daily_workflow.md` 为准：固定两层浮盈防守，TP1 减仓 50%，TP2 清剩余 50%。本文历史性的“2-3 层”或“30%-50%”口径不得覆盖 active authority。

---

## 出场优先级（图谱二十节，2026.5 迭代后）

| 优先级 | 维度 |
|---|---|
| **第一** | 盈亏比（1.5R / 2.5R） |
| **第二** | 胜率（参考，非核心决策变量） |

> ⚠️ 此处「胜率非核心决策变量」仅指**离场/选单阶段**的优化优先级（盈亏比 > 胜率）。与**开单前置硬门槛「胜率自估 ≥60%」**（见 `constitution/maker_principles.md` / `agents/risk_agent.md` Gate5）是两个不同阶段，不矛盾：先过 ≥60% 胜率门才允许开单，开单后/合格单之间再按盈亏比为主排序。

---

## TP（止盈）模型

### TP1（标准止盈第一档）
- **Maker 精确减仓 50%；主账户按独立计划减仓 20%**
- 触发：价格到达计划 TP1 价
- 操作：
  1. Maker 减仓 50%（主账户中线按 20%）
  2. 剩余仓位止损同时移至开仓均价（保本层）
  3. 进入剩余仓位"防守计划"运行

### TP2 与防守计划分层
- Maker TP2 清理剩余 50%；两层浮盈防守本身不减仓
- 主账户中线最高可达 **5 层**
- Maker 日内固定 **2 层**

---

## 浮盈防守层级（图谱第七节）

### Maker 2 层

| 层 | 触发 | 操作 |
|---|---|---|
| 第一层（动态止损层） | 价格触及认证的 1.5R 精确触发价 | 止损移至成交后后续形成并确认的 4H 结构极点 |
| 第二层（保本层） | 价格进一步向有利方向运动 | 止损移至开仓均价或更优（保本损） |

### 主账户 5 层（图谱第十四节）

| 层 | 触发 | 操作 |
|---|---|---|
| 第一层 | 价格触及关键位置 | 设保本损 + 取消所有加仓策略 |
| 第二层 | 价格再进一步 | 止损升级到日线级别极点 |
| 第三层 | 价格触及关键结构未突破反转 | 重设结构性止损 |
| 第四层 | 价格触及 TP1 | 减仓 20%（主账户中线减仓比例小于 Maker） |
| 第五层 | 价格再触及 | 止损升级到周线级别极点 |

---

## SL（止损）模型

### 硬规则
- **账户独立风险上限**：Maker 每个非空成交组合 ≤3%；主账户四档的全部 15 个非空成交组合 ≤8%
- 统一计算：`abs(weighted_entry - sl) / weighted_entry × leverage × 100`；禁止把 Maker 3% 套到主账户，也禁止用 Main 8% 放宽 Maker

### 止损位选取
- Maker 左侧/右侧：同账户 `invalidation_path` 只从本轮 TradingView 的 4H/1H/15m timeframe-bearing zone 选择可机械定位且严格位于入场区与全部挂单价外侧的真正失效锚。合法锚仅为 readable `user_drawn_manual_only` 手绘 profile 中性外沿（空单上沿、多单下沿），或非当前入场区的 structure zone 外沿；空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`。裸支撑/阻力/摆动数组只供展示，禁止补周期后作为锚；不强制最近数值层，不得强用弱中间结构。该 `invalidation_path` 必须在 reasoning 阶段密封 exact `structural-noise-buffer-v2`；`certified` 绑定可达的本轮 TradingView observation、`4h|1h|15m`、同周期截图、可机械定位锚、图上 `noise_outer_boundary`、正 `price_distance` 与 `risk_budget_input_used=false`，stop 严格越界；证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis identity/anchor/distance 必须精确等于 reasoning owner，Gate 另读 status/visual/boundary，compiler 不得推断。入场区或确认区边界本身不是充分止损依据
- 结构止损确定后才运行全部成交组合风险/R:R；不合格时调整阶梯或观望，禁止压缩止损过门
- 主账户中线：只按自身 `invalidation_path` 使用本轮 TradingView 1D/4H timeframe-bearing zone 选择结构性止损锚，合法 zone kind、方向角色与禁止裸 level 数组的规则和上文一致；reasoning 阶段的 exact `structural-noise-buffer-v2` 只允许绑定可达 TradingView observation、`1d|4h`、同周期截图、机械锚与可见 `noise_outer_boundary`。`certified` 的 stop 必须严格越界；证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis 字段必须精确等于 reasoning owner，Gate 另读 status/visual/boundary，compiler 不推断。不得借用 Maker 的 1H/15m 锚或 Maker 风险门，随后枚举四档全部 15 个非空成交组合并保持名义风险≤8%；禁止固定点数、ATR 或 8% 倒推/压缩结构止损

### 止损迭代（仅按防守计划）
- 允许：按防守层级递进升级
- 禁止：擅自移动（V001 违规）
- 禁止：扩大风险
- 禁止：情绪化补仓后改止损

---

## 注意事项 / 取消价格（图谱第七节强制）

### 每笔计划必含
```
注意事项：若价格优先触及 [价格] 则取消此策略
```

### 取消价格选取
- 左侧入场：通常为入场区间反向极点
- 右侧入场：通常为确认信号反向无效价

### 取消触发
- 一旦价格触及取消价 → **无论如何立即取消策略**
- 不允许"再观察一下"
- 已触发未取消 → V012 违规（图谱十三节 2026.4.1 案例）

---

## 出场决策树

```
持仓中
  ├─ 价格触及取消价？
  │   ├─ 是 → 立即取消（如未开仓）/ 不适用（如已开仓，按 SL 走）
  │   └─ 否
  │       ├─ 价格触及 SL？
  │       │   ├─ 是 → 强制止损（不允许移动）
  │       │   └─ 否
  │       │       ├─ 价格触及第一层防守触发位？
  │       │       │   ├─ 是 → 按层操作（动态止损 / 保本损）
  │       │       │   └─ 否 → 继续持有
  │       │       └─ 价格触及 TP1？
  │       │           ├─ 是 → Maker 精确减仓 50% / 主账户减仓 20%
  │       │           └─ 否 → 等待
  │       └─ 价格触及更高层防守触发位？
  │           ├─ 是 → 按对应层操作
  │           └─ 否 → 继续运行
```

---

## 与 risk_agent 的协作

risk_agent **Gate 6** 专门校验出场操作：

| 操作 | risk_agent 校验 |
|---|---|
| 减仓 | 是否触发 TP 层？是否到达对应层级？ |
| modify_stop | 是否符合层级递进（保本 → 结构 → 日线极点 → 周线极点）？ |
| close | 是否触及 SL 或 取消价？ |

任何"回退"操作（如已设保本想撤回到结构止损）→ deny。

---

## 历史教训（图谱十三节）

| 违规 | 出场相关教训 |
|---|---|
| V001 移动止损 | **2025.7.11** 擅自修改原计划止损 → 破坏盈亏比 + 强化侥幸 |
| V012 已触发未取消 | **2026.4.1** 喝酒分心 → 注意事项失效未执行 |

---

## 禁止行为

* 禁止止损"扩大"（只能层级递进收紧）
* 禁止主观提前止盈（必须按 TP 层）
* 禁止 TP1 后立即全部清仓（剩余仓位的运行才是关键）
* 禁止取消价被触发后"再观察"
* 禁止主账户中线减仓比例像 Maker 那样大（中线维持稳定）

---

## 核心原则（图谱二十节）

> 出场是比入场更重要的技术。
> TP1 后的剩余仓位运行是关键。
> 第一优先级盈亏比，第二优先级胜率。
