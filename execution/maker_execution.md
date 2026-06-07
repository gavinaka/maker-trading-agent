# Maker 账户执行规则（图谱一节 + 六节 + 八节）

> Maker = OKX 上的日内交易账户。
> **与中线主账户互不干扰（一直如此）**；"不能做"是 Maker 自身当天日内禁令，非主账户下达。
> 当前核心目标：**洁净样本打造**（50 笔，当前 22%）。

---

## 账户基本信息

| 项 | 值 |
|---|---|
| 交易所 | **OKX** |
| 标的 | BTCUSDT 永续合约（主） / ETHUSDT（辅助） |
| 周期 | 日内（不隔夜） |
| 单笔规模 | BTC $500-$1000 / ETH $300-$800 |
| 杠杆 | **5x 固定**（2026.3 起标准） |
| 角色 | 日内交易（高空 / 低多 / 反弹空） |

---

## 执行模式（图谱第六节）

### 策略类型 A：Maker（标准模式）

**胜率高于 60% 极强共振支撑**

#### 核心要求
* 必须经过完整评分系统（总分 ≥ 70）
* 需要多重技术信号共振：
  - 支撑压力
  - 流动性
  - 盘口（CVD / OI / Funding）
  - 结构

#### 执行标准
* **R:R ≥ 1:2.5**
* 执行概率 ≥ 60%
* 胜率 ≥ 70%

### 策略类型 B：Taker（至少两次流动性）

**已合并到主账户，2026.3.8 起不再用作独立 Maker 路径**。
历史定义见 `execution/taker_history.md`。

---

## 入场方式（图谱第六节）

详见 `execution/entry_models.md`。

* **左侧入场（主要）**：提前限价挂单，接受不确定性
* **右侧入场（辅助）**：等待价格行为确认

---

## 仓位执行方式（图谱第六节）

### 标准模式：分批入场
```
50% 先入 + 50% 等待二次确认
```

### 特殊模式：一次性 100%
* 仅用于极端强信号（如 C01/C02 极端组合）
* 必须在备注说明理由

---

## 仓位规模约束

| 标的 | 区间 | 杠杆 |
|---|---:|---|
| BTC | $500 - $1000 | 5x |
| ETH | $300 - $800 | 5x |

state 来源：`state/maker_state.json.position_rules.default_position_size_usd`

risk_agent **Gate 4** 严格校验，超出 → deny。

---

## 浮盈防守（2-3 层，图谱第七节）

详见 `execution/exit_models.md` 和 `risk/floating_defense.md`。

* 第一层（动态止损层）
* 第二层（保本层）
* 第三层（减仓层，可选）

→ 比主账户 5 层简化。

---

## 当天 Maker「不能做」→ 可做方向（2026-05-31 订正：与主账户无关）

「不能做」由当天市场推导（盘口>盘面>基本面=禁追最拥挤一边），写完日报最后回填：

| 当天 Maker 不能做 | Maker 可做方向 | 备注 |
|---|---|---|
| 做多 | 只做空（高空 / 反弹空） | 入场区：日内压力区间 |
| 做空 | 只做多（低多） | 支撑区反弹买入 |
| 追多空 | 观望优先 | 震荡结构，评分通常 < 70 |

详见 `constitution/cannot_do_mapping.md`（已改 Maker 内部）。

---

## 每日交易上限

* `state/maker_state.json.position_rules.max_daily_trades = 3`
* 超过 3 笔 → risk_agent Gate 4 deny
* 历史教训：V003 分时高频交易（2025.8.18）→ 此上限强制

---

## 时间窗口

| 时段 | 任务 |
|---|---|
| 早间盘前（09:00-11:00） | Maker 上午计划生成 |
| 11:00 | 早间评分点 |
| 09:00-12:00 | 早间执行窗口（一般高空/低多） |
| 14:00-18:00 | 午盘观察期（一般减少新开仓） |
| 19:00-22:00 | 晚间执行窗口（一般反弹空） |
| 20:00 | 晚间评分点 |
| 20:00-20:30 | Maker 晚间新增计划生成 |
| 23:00 | 当日 review |

→ 严格在窗口内执行；其他时段开仓 → risk_agent Gate 2 第5项（交易时间窗）deny。

---

## 隔夜规则

* `state/maker_state.json.position_rules.allow_overnight = false`
* Maker 不允许隔夜持仓
* 当日 23:00 前必须平仓
* 例外：极端强信号（需用户在备注说明 + risk_agent metadata override）

---

## 当前状态快照（state/maker_state.json）

```json
"execution_mode": "intraday",
"primary_strategy": "高空 / 反弹空",
"default_entry_type": "left_side",
"score_requirement": {
  "minimum_total_score": 70
},
"clean_sample_system": {
  "enabled": true,
  "target_clean_trades": 50,
  "current_progress_pct": 22
},
"current_focus": [
  "洁净样本打造",
  "系统一致性",
  "降低随机性",
  "严格执行评分系统"
]
```

---

## Maker 行为禁令（state/maker_state.json.maker_behavior_rules）

```json
"allow_fomo":                  false,
"allow_chasing":               false,
"allow_random_entry":          false,
"allow_unplanned_trade":       false,
"allow_manual_stoploss_change": false
```

任一违反 → penalty_agent 必判违规（V004 / V008 / V001 等）。

---

## Maker 与主账户的独立性

```
主账户中线持仓时（方向为做空或做多·真值见 Notion 交易Check）
  ├─ Maker 方向由当天自身「不能做」决定，**不受主账户约束**（互不干扰，2026-05-31 订正）
  ├─ 仓位、止损、防守计划完全独立
  └─ Maker 平仓不影响主账户中线
```

→ 描述字段也独立维护（Maker = 单次事后；主账户 = 跨日演变）。

---

## 与 review_agent 的数据流

```
Maker 执行
  ├─ check_records[].account = "maker"
  ├─ check_records[].entry_mode = "Maker" 或 "Taker"（指挂单方式）
  ├─ check_records[].entry_type = "左侧" 或 "右侧"
  ├─ check_records[].holding_period = "短线" 或 "实时盯盘"
  └─ check_records[].clean_sample_eligible 由 review_agent 判定
```

---

## 禁止行为

* 禁止隔夜（除非用户 metadata override）
* 禁止超出 3 笔/日
* 禁止突破 BTC $1000 / ETH $800 仓位上限
* 禁止偏离当天 Maker「不能做」方向门禁（risk_agent Gate3）
* 禁止 FOMO / 追单 / 随机 / 无计划开仓 / 手动改止损
