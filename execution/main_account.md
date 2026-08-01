# 主账户执行规则（图谱一节 + 十四节）

> 主账户 = Binance 上的 BTC USDT 永续合约中线持仓账户。
> 决定**自身中线大方向**（基本面>盘面>盘口）；**与 Maker 计划互不干扰，一直如此**。
> ⚠️ 订正（2026-05-31）：「不能做」是**当天 Maker** 字段、与中线无关，**不**由主账户决定。
> 当前持仓、均价、方向、防守层与已执行比例都是动态业务事实，不属于 reasoning authority。vNext 只能在独立推理锁定后从当次 run 绑定的 `continuity_contract` 读取；缺失时写未提供，禁止读 Notion、旧 state、历史报告或用计划数字反推。
> 主账户必须拥有独立的 `market_regime → strongest_counterevidence → invalidation_path → base/counter/invalidation scenarios → main_account_thesis → plan` 闭环。它不拥有 `cannot_do`；Maker 的 `cannot_do` 也不得进入、改写或否决主账户闭环。

---

## 账户基本信息

| 项 | 值 |
|---|---|
| 交易所 | **Binance** |
| 标的 | BTCUSDT 永续合约（主） / ETHUSDT（辅助） / XAUUSDT（锁仓年化做空） |
| 周期 | 日 / 周 / 月级别 |
| 仓位规模 | $2000 - $4000（分批构建总额） |
| 杠杆 | 5x（当前标准） |
| 角色 | 决定自身中线大方向（基本面>盘面>盘口）；与 Maker 互不干扰（不约束、不发"不能做"） |

---

## 中线持仓策略结构（图谱十四节）

### 核心原则
**不是一次性入场，而是分批构建。**

### 入场结构（分批构建）

| 档 | 比例 | 触发价 |
|---|---:|---|
| 底仓 | 由当次主账户计划决定 | 由当次主账户证据决定 |
| 后续档 | 各档明确，全部比例闭合 | 每档必须有当次结构依据 |

止损、TP1、终局止盈和每档价格都由本轮主账户闭环生成；本方法文件不嵌入任何历史市场价格。

主账户计划中的承重方向、计划状态、动作、价格区间、分档、仓位、止损、止盈、反证和失效条件必须由结构化主账户决策字段唯一拥有；正文只能从这些字段投影，不得让自由 `plan_text` 另写一套事实或数字。shadow 不读取实际持仓，相关字段只能明确写“未验证”；production 的锁后 continuity 事实只做连续性校准，不得回改独立计划。

### 主账户独立风险上限

主账户不受 Maker 3% 上限约束。四档分批计划必须枚举全部 `2^4-1=15` 个非空成交组合，按各组合真实比例计算加权入场，并逐一复算：

`名义风险% = abs(加权入场 - 止损) / 加权入场 × 杠杆 × 100`

每个组合均须 `≤8%`；任一组合超过 8% 时主账户计划不可认证。该 8% 只属于主账户，不得传递给 Maker，也不取代结构止损、反证与失效闭环。

### 主账户独立初始止损

主账户不得复用 Maker 止损政策。初始止损只能由主账户 `invalidation_path` 从本轮 TradingView 认证的 1D/4H 中线结构选择真正失效锚；1H/15m 只可服务短周期观察或 Maker 执行，不得作主账户初始止损主锚。当前 active 锚只允许带 timeframe 的 readable 手绘 profile 中性上/下沿或非当前入场区的 structure zone 外沿；裸支撑/阻力/摆动价格数组只供展示，不能先主观贴周期再充当 authority。空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`；手绘 profile role 不承担方向语义。合法锚还须严格位于主账户入场区与全部分档价外侧，当前入场区边界自身、弱中间结构和数值最近层都不能自动取得优先权。

外向 buffer 不是由 8% 反解的万能公式。主账户 `invalidation_path` 必须在 reasoning 阶段拥有 exact `structural-noise-buffer-v2` 的 13 个字段：`schema_version/status/method_code/observation_id/timeframe/visual_evidence_ref/anchor_kind/anchor_source_field/anchor_price/noise_outer_boundary/price_distance/risk_budget_input_used/insufficiency_reason_code`。`certified` 必须绑定该 claim support DAG 可达的本轮 TradingView、`1d|4h`、同周期截图、可机械定位锚与图上 `noise_outer_boundary`，`risk_budget_input_used=false`，最终 stop 严格越过该边界；证据不足只允许 `insufficient`、闭合原因、空 anchor/boundary/distance 与 `observe`。decision 的主账户 stop basis 中存在的 observation/timeframe/anchor identity/price/outward distance 必须精确等于 reasoning owner，并维持同一 `buffer_claim_id`、`buffer_backsolved_from_risk=false`；Gate 另读 reasoning 的 status、截图与 boundary 验证。8% 只在止损确定后验算，不得用固定点数、ATR、风险倒推或压缩，compiler 只能校验/投影、不得推断。结构止损不合格时只能调整分档或观察。

---

## 仓位演变日志（结构模板）

每次价格触及关键位都更新一次描述字段：

```
"触发[当次认证价格] 后已执行[可核验比例]"
"基于[当次结构证据]迭代仓位/止损"
```

→ 一个持仓历时数十天，描述字段可有 **20+ 条更新**。

---

## 五层浮盈防守（图谱十四节 + 七节）

主账户的浮盈防守比 Maker 复杂（更长周期，更细分层）。

### 抽象模板

| 层 | 触发 | 操作 |
|---|---|---|
| 第一层 | 价格触及 XXXX | 设立保本损 + 取消所有加仓策略 |
| 第二层 | 价格触及 XXXX | 设立日线级别高点极点为止损 |
| 第三层 | 价格反弹触及 XXXX（关键结构）未突破反转 | 设止损为 XXX |
| 第四层 | 价格触及 XXXX | 减仓 20% |
| 第五层 | 价格再次触及 XXXX | 止损设为当周线级别极点高点 |

### 5 层防守执行原则

5 层只定义防守动作的递进关系，不携带当前层级、方向、持仓或历史价格。当前已触发层级必须来自分析锁后绑定的 continuity 事实；缺失即不得宣称任何层级已生效。

---

## 动态加仓规则

* 当价格到达**更好的做空位**（高位）→ 追加仓位
* 当价格到达**更好的做多位**（低位）→ 追加仓位
* 加仓后**重算均价**："仓位成本"概念

```
new_avg = (old_qty × old_avg + add_qty × add_price) / (old_qty + add_qty)
```

---

## 止损迭代规则

中线止损随结构变化"**迭代**"（更新止损位）：

* 价格朝有利方向运动 → 止损向有利方向移动
* 但**禁止**朝不利方向移动（V001 违规）
* 迭代必须基于结构性原因（如新极点 / 新支撑突破）
* 不允许情绪化迭代

---

## 与 Maker 的关系：互不干扰（2026-05-31 订正）

**中线计划与 Maker 计划互不干扰，一直如此。**
* 主账户**不**向 Maker 下达"不能做"，**不**约束 Maker 方向。
* 「不能做」是**当天 Maker 自身**的日内禁令（写完日报后最后回填的收口结论），由当天市场（盘口>盘面>基本面）推导，与中线持仓方向无关。
* Maker「不能做」的终局限制与计划兼容校验见 `constitution/cannot_do_mapping.md`；它不得反向生成或翻转 Maker thesis。
* 旧框架「主账户 cannot_do → Maker 允许方向」**已废弃**（误把两账户耦合）。

---

## 主账户与 Maker 关键差异

| 维度 | 主账户 | Maker |
|---|---|---|
| 周期 | 天 ~ 周 | 日内 |
| 单笔规模 | $2000 - $4000 | $500 - $1000 |
| 入场 | 分批 4 档 25% | 2 至 5 档 `ladder`，比例合计 100%，禁止单一价位一次性入场 |
| 浮盈防守层数 | **5 层** | **2 层**（只移动止损／取消加仓，不减仓） |
| 减仓比例（TP1） | 20% | 精确 50%（TP2 清剩余 50%） |
| 描述字段 | 跨日演变日志 | 事后单次复盘 |
| 是否有终局止盈位 | **有**（具体价格由当次主账户证据决定） | 无 |

---

## 持仓快照边界

本文不保存任何持仓快照。当次主账户事实只能在独立 reasoning 锁后进入 source/hash-bound continuity 工件，并且只用于撤旧、保留、迭代与执行对照，不得改变已锁定的方向、价格区间、评分或决策。

---

## 数据更新职责

| 字段 | 谁维护 |
|---|---|
| 当次实仓事实 | 分析锁后的 source/hash-bound continuity 工件 |
| 当次防守层级 | 同一 continuity 工件中的可核验记录 |
| trend_confirmation | 当次六源中 TradingView 1D/4H/1H/15m 结构独立推导 |

> 注：「不能做」**不是主账户字段**，归当天 Maker（写完日报最后回填），不在本表维护。

---

## 禁止行为

* 禁止一次性满仓入场（必须分批）
* 禁止不基于结构迭代止损
* 禁止主账户与 Maker 计划"互通"（持仓互不干扰）
* 禁止跳过描述字段更新（每次防守层升级都要写）
* 禁止主账户参与日内高频交易（违反账户角色）
