# Maker 账户执行规则（图谱一节 + 六节 + 八节）

> Maker = OKX 上的日内交易账户。
> **与中线主账户互不干扰（一直如此）**；"不能做"是 Maker 自身当天日内禁令，非主账户下达。
> 本文只定义稳定业务规则，不携带样本目标、当前进度、实仓、旧 state 或其它 run 事实。

---

## 账户基本信息

| 项 | 值 |
|---|---|
| 交易所 | **OKX** |
| 标的 | BTCUSDT 永续合约（主） / ETHUSDT（辅助） |
| 周期 | 日内（不隔夜） |
| 单笔规模 | BTC $500-$1000 / ETH $300-$800 |
| 杠杆 | **5x 固定** |
| 角色 | 日内交易（高空 / 低多 / 反弹空） |

---

## 执行模式（图谱第六节）

### 策略类型 A：Maker（标准模式）

**胜率高于 60% 极强共振支撑**

#### 核心要求
* 必须经过完整评分系统（总分 ≥ 65）
* 需要多重技术信号共振：
  - 支撑压力
  - 流动性
  - 盘口（CVD / OI / Funding）
  - 结构

#### 执行标准
* **R:R ≥ 1:2.5**
* **计划时置信度（非回测命中率）≥ 60%**（硬门槛·开单前置·与「总评分 ≥ 65」并列共存，任一不满足即不开单）。按 `scoring/winrate_methodology.md` 取 0–100 连续整数真实估值，不锁固定档；样本不足期间禁止声称已校准命中概率。
* 入场价格触达概率 ≥ 50%（软参考、**非硬门槛**，只描述当前价到挂单区的可达性，不是实际成交概率，也不决定是否开仓）

### 策略类型 B：Taker（至少两次流动性）

Taker 当前暂停，不属于日报 Maker 生产路径，也不得并入主账户或作为 Maker 单点入场例外。

---

## 入场方式（图谱第六节）

详见 `execution/entry_models.md`。

* **左侧入场（主要）**：提前限价挂单，接受不确定性
* **右侧入场（辅助）**：等待价格行为确认

### 订单价格合同

* `ladder`：正式可执行计划的唯一形态。2至5档，每档价格与比例明确、比例合计100%；系统枚举全部非空成交组合，任何组合不满足 R:R≥1:2.5 或5倍名义风险≤3%即拒绝。该 3% 是 Maker 独立上限，不得被主账户 8% 替代。
* `conditional_zone`：只表达等待区域和确认规则，明确不是可执行订单；确认后必须重新生成 `ladder` 合同。
* 禁止 `single`、代表价或用一个具体价格冒充入场区间。
* 禁止“入场区间 + 代表入场价”替代成交情景验证。
* 决策中的 Maker 计划必须严格等于当前 decision gate 认证的闭合字段集合；禁止新增 `plan_text`、`entry_price`、自由文本订单摘要或任何“代表值”作为第二套业务真相。可见报告只能由该 typed schema 确定性投影。
* current price、全部 ladder entries 与 cancel price 必须由 Gate 派生 exact `maker-order-lifecycle-v1`。只有 cancel 位于 current→entries 的反方向分支才为 `fillable`；同向且更近为 `cancel_blocks_all_entries`，同向且更远为 `entry_before_cancel`，碰撞、跨侧或混合几何为 `invalid_geometry`。后三者必须先于风险数学以 `order_lifecycle_invalid` 拒绝。`entry_reach_probability` 只说明价格触达，不能代替生命周期；实际 `fill_probability` 固定为 `null`/N/A。
* 初始硬止损锚必须由同账户 `invalidation_path` 从本轮 TradingView 认证结构中选择，且可机械定位并严格位于 `entry_zone` 与全部挂单价外侧。合法来源只限带 timeframe 的两类 zone：`status=readable`、`source_mode=user_drawn_manual_only` 手绘 profile 的中性外沿（空单 `manual_profile_upper_outer_boundary`、多单 `manual_profile_lower_outer_boundary`），或非当前入场区的认证 `structure_zone_outer_boundary`。Maker 允许 4H/1H/15m；空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`。裸支撑/阻力/摆动价格数组只供展示，禁止主观补周期后充当锚；手绘 profile role 不承担方向语义；当前入场区边界本身禁止。不要求使用数值最近层，也不得把弱中间结构硬编码成锚。
* 锚外结构噪声判断必须在 reasoning 阶段由同一 Maker `invalidation_path` 以 exact `structural-noise-buffer-v2` 密封 13 个字段。`certified` 必须使用 `method_code=pre_risk_tradingview_structure_noise_judgment`，绑定该 claim support DAG 可达的本轮 TradingView、`4h|1h|15m`、同周期 `visual_evidence_ref`、可机械定位的 anchor、图上 `noise_outer_boundary`、正 `price_distance` 与 `risk_budget_input_used=false`，最终 stop 严格越过该边界；证据不足只允许 `insufficient`、闭合原因、空 anchor/boundary/distance 与 `observe`。decision stop basis 中存在的 observation/timeframe/anchor identity/price/outward distance 必须精确等于 reasoning owner，并保留 `buffer_basis_code=current_run_typed_market_noise_allowance`、同一 `buffer_claim_id`、`buffer_backsolved_from_risk=false`；Gate 另读 status、截图与 boundary 验证。3%/R:R 只在结构止损后验算，若不合格只能调整阶梯或观望；禁止固定点数、ATR、风险倒推或压缩，compiler 只校验/投影、不得推断。清算地图、Exocharts POC 或代表价都不能充当止损锚。
* 报告前基于每种可能成交组合的加权价做风险验算，但不得把任何假设组合的加权价写成实际成交均价。控制器必须同时给出计划全档加权锚及全部非空成交组合对应的两层阿拉伯数字精确触发价；每个组合保留 canonical Decimal 原始值、闭合取整规则、绑定价格步长和最终价，四者必须可复算。计划锚只用于 prefill 风险/防守投影，不是单点入场。真实成交后按成交明细计算实际加权成交价，并以多单向上加 1.5R/2R、空单向下减 1.5R/2R 重算唯一触发价，替换 prefill 投影；禁止 `+/-` 或 `±` 泛化表达。

---

## 仓位执行方式（图谱第六节）

### 唯一模式：2 至 5 档分批入场
* 每档价格与比例必须明确，比例合计 100%。
* 50% + 50% 只是合法的两档示例，不是固定模板；实际档数与比例由本轮独立推理和全部成交组合风险验算决定。
* 当前 production 盘口最高 60；未来即使原生结构化证明能力获批启用并确认 70 分极端强信号，也不得使用 `single`、代表价或单一价位一次性 100% 入场；信号强度不改变订单结构宪法。

---

## 仓位规模约束

| 标的 | 区间 | 杠杆 |
|---|---:|---|
| BTC | $500 - $1000 | 5x |
| ETH | $300 - $800 | 5x |

仓位范围的机器单一真相源是当前 phase 内 `scoring/scoring_contract.json.risk_execution.maker_instruments`；决策门按该结构复算，不读任何 legacy 状态目录。

---

## 浮盈防守（2 层，图谱第七节）

完整规则以当前 reasoning phase 内的 `risk/floating_defense.md` 为准。

* 第一层（动态止损层）
* 第二层（保本层）

→ 比主账户 5 层简化。仓位扣减只发生在 TP1 精确减仓 50% 与 TP2 清剩余 50%；两层浮盈防守只移动止损、取消加仓，不减仓。

---

## 当天 Maker「不能做」计划相容性校验（与主账户无关）

Maker 方向必须先由自身完整证据链独立形成；`cannot_do` 仅在全部分析完成后末位生成，用于机械检查既有候选计划是否冲突。冲突时该候选不可构造并转为观望；不冲突只表示未触禁，绝不授权相反方向，也不得生成、翻转或倒推 Maker thesis。精确枚举与校验以 `scoring/scoring_contract.json` 和 decision gate 为准。

---

## 每日交易上限

* 单日最多 3 笔，机器真相源为 `scoring/scoring_contract.json.risk_execution.maker_daily_trade_limit`
* 超过 3 笔 → 当次 decision 拒绝
* 该上限是稳定风控合同，不得由模型、样本进度或临时观点放宽

---

## 报告 slot 与执行时间边界

| 报告 slot | 证据与判断要求 |
|---|---|
| morning | 本 slot 完整六源重新分析 |
| midday | 本 slot 完整六源重新分析，禁止沿用早报评分或策略 |
| evening | 本 slot 完整六源重新分析，禁止沿用午报评分或策略 |

pre-cutover shadow 的 slot 是验证标签，可在获批准后于任意时间执行；必须如实记录实际采集时间，不冒充固定评分点，不执行真实订单。切换后的计划有效窗口必须来自当次认证 decision，不得用本方法文件中的旧固定时钟代替。

---

## 隔夜规则

* Maker 不允许隔夜持仓
* 当日 23:00 前必须平仓
* 不存在由模型、备注或旧 state 自行生成的隔夜例外

---

## 运行态边界与行为禁令

本 reasoning authority 不读取、不内嵌、不推测任何 legacy 状态快照、样本进度或当前策略。FOMO、追单、随机、无计划开仓和手动放宽止损始终禁止；当次执行事实只能在独立推理锁后由 source/hash-bound continuity 合同引入。

---

## Maker 与主账户的独立性

```
主账户中线事实如在分析锁后由当次 continuity 合同提供
  ├─ Maker 方向由自身六源证据链独立形成，**不受主账户约束**
  ├─ 「不能做」只在完整推理后末位汇总禁止方向，不得反向生成 Maker thesis
  ├─ 仓位、止损、防守计划完全独立
  └─ Maker 平仓不影响主账户中线
```

→ 描述字段也独立维护（Maker = 单次事后；主账户 = 跨日演变）。

---

## 锁后执行数据流

```
Maker 执行
  ├─ check_records[].account = "maker"
  ├─ check_records[].entry_mode = "Maker" 或 "Taker"（指挂单方式）
  ├─ check_records[].entry_type = "左侧" 或 "右侧"
  ├─ check_records[].holding_period = "短线" 或 "实时盯盘"
  └─ 执行事实只写入当次 source/hash-bound continuity 工件
```

连续性语义必须精确：`reconcile_filled` 仅在前序状态为 `filled`、累计成交比例恰为 `100%` 且前后均不存在 active order 时合法。`open` partial remainder 必须显式执行 `keep`、`cancel` 或 `cancel_replace`，不得借 `reconcile_filled` 消失；无论选择哪种合法动作，既有成交账本均必须保留，且 continuity 不得回写已锁定分析。

---

## 禁止行为

* 禁止隔夜
* 禁止超出 3 笔/日
* 禁止突破 BTC $1000 / ETH $800 仓位上限
* 禁止候选计划违反末位 `cannot_do` 相容性校验；该终值不得作为方向依据
* 禁止 FOMO / 追单 / 随机 / 无计划开仓 / 手动改止损
