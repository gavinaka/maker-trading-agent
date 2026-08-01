# 风控检核清单（图谱第四节，7 项硬规则）

> 开仓前必须**全部 7 项 ✓** 才允许执行。
> 任一缺项 → 计划质量评级"**低**" → V002 违规风险 → 不计入洁净样本。
> 第 7 项按账户独立执行：Maker 上限 3%，主账户上限 8%；禁止互相套用。

---

## 检核清单

```
- [ ] 1. 是否记录交易计划
- [ ] 2. 是否符合风险敞口要求
- [ ] 3. 是否完成技术面确认
- [ ] 4. 是否设置好止损止盈
- [ ] 5. 是否在规定交易时间内
- [ ] 6. 是否严格按入场信号执行
- [ ] 7. 全部非空成交组合风险合格（Maker ≤ 3%；Main ≤ 8%）
```

---

## 每项详细判定

### 1. 是否记录交易计划

**判定**：
* 本 slot 的 `decision_contract_<slot>.json` 与 canonical combined 中同时存在可执行 Maker 计划
* 计划必含：方向 / 价格区间 / 仓位 / 入场方式 / 止盈 / 止损 / 浮盈防守 / 取消价格
* 缺任一字段 → 第 1 项 ✗

**禁止**：临时开仓无计划（V002 / V008 / V013 违规）

---

### 2. 是否符合风险敞口要求

**判定**：
| 标的 | 账户 | 单笔区间 USD | 杠杆 |
|---|---|---:|---|
| BTC | Maker | $500 - $1000 | 5x |
| ETH | Maker | $300 - $800 | 5x |
| BTC | Main 中线 | $2000 - $4000（分批构建总额） | 5x |

* `request.size_usd ∉ 区间` → ✗
* `request.leverage != 5` → ✗；日报计划不允许通过 metadata、情绪或历史状态绕过
* Maker 单日交易数 > 3 → ✗

**数据源**：当前 `scoring/scoring_contract.json` 的账户约束 + 本 slot hash-bound `decision_contract_<slot>.json`；任何 legacy 状态快照禁止作为当前风险真值。

---

### 3. 是否满足开单双门槛（总评分 + 胜率）

**判定**（两门槛并列·任一不过即不开）：
* 门槛① 本 slot `decision_contract` 机械复算的总评分 `>= 65`（当前 production 盘口只允许0–60；61–69非法，70为未来原生结构化证明保留值且不可由配置启用）AND
* 门槛② `plan.win_rate >= 60`（胜率自估 ≥60%·2026-06-16 升级为硬门槛）AND
* 本 slot `reasoning_contract` 的六源观察均绑定当前不可变 capture，且不存在缺失或无效核心源

**禁止**：评分未达 65 或计划时置信度未达 60% 强行开仓（V004 / V011 违规）；用入场价格触达概率 <50% 否决开仓（触达概率为软参考、非门槛，且不是实际成交概率）。

---

### 4. 是否设置好止损止盈

**判定**：
* `request.sl > 0` AND `request.tp > 0`
* **Maker R:R ≥ 1:2.5**：`abs(tp - entry) / abs(entry - sl) >= 2.5`；该阈值不得自动套到主账户
* Maker TP1/TP2 必填：TP1 默认减仓 50%，TP2 清剩余仓位
* Maker 初始止损锚由同账户 `invalidation_path` 从本轮 TradingView 4H/1H/15m 认证 zone 中选择，须可机械定位并严格位于入场区与全部挂单价外侧。合法锚只允许 readable `user_drawn_manual_only` 手绘 profile 中性上/下外沿，或非当前入场区的 structure zone 外沿；空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`。裸支撑/阻力/摆动数组只供展示，禁止补周期后充当锚；不强制数值最近层，不得强用弱中间结构。同一 Maker `invalidation_path` 必须在 reasoning 阶段密封 exact `structural-noise-buffer-v2`。`certified` 绑定可达的本轮 TradingView observation、`4h|1h|15m`、同周期截图、机械锚、图上 `noise_outer_boundary`、正 `price_distance` 与 `risk_budget_input_used=false`，stop 严格越界；证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis identity/anchor/distance 必须精确等于 reasoning owner，Gate 另读 status/visual/boundary；3% 与 TP1 R:R 后验且不得用固定点数、ATR、风险倒推或压缩，compiler 不得推断
* 主账户初始止损独立绑定自身 `invalidation_path`，只允许本轮 TradingView 1D/4H 的同类 zone 锚；该 claim 同样必须在 reasoning 阶段密封 `structural-noise-buffer-v2`，绑定可达 TradingView observation、`1d|4h`、同周期截图、机械锚与可见 `noise_outer_boundary`。`certified` stop 严格越界；证据不足只可 `insufficient + observe`。decision 中存在的 stop-basis 字段必须精确等于 reasoning owner，Gate 独立读取 status/visual/boundary，compiler 不推断。不得引用 Maker 1H/15m 锚，不得套用 Maker 3% 或 TP1 R:R 门；8% 只能在止损确定后验证，四档全部 15 个非空成交组合均须≤8%，不得用固定点数、ATR、风险倒推或压缩 buffer
* Maker 浮盈防守计划 ≥ 2 层：两层都必须写阿拉伯数字精确触发价；第一层同时写成交后后续确认的 4H 极点规则但禁止预填未知极点止损价，第二层只设实际加权成交价保本损
* 取消价格必填，且 `maker-order-lifecycle-v1` 必须为 `fillable`；`cancel_blocks_all_entries|entry_before_cancel|invalid_geometry` 均不得执行，实际 `fill_probability=null`

---

### 5. 是否在规定交易时间内

**判定**（GMT+8 北京时间）：
* 早／午／晚报告分别绑定本 slot 的真实采集时间、证据新鲜度和计划有效窗口
* 计划不得在来源超过新鲜度门后继续作为实时可执行计划
* 后一时段 canonical 计划交付后，前一时段未成交计划必须按 continuity contract 明确撤销、保留或替换
* 禁止以旧的固定“两报告执行窗口”或 metadata override 绕过当前三时段状态机

---

### 6. 是否严格按入场信号执行

**判定**：
* 正式 Maker 订单只允许 `ladder`：同一价格区间内 2–5 档明确价位，分配比例合计 100%；`single` 禁止用于 Maker，`conditional_zone` 明确不是订单
* 入场方式与计划一致，只有实际触发或限价成交后才算执行
* 价格尚未到达 Maker 边缘属于“挂单等待”，不得改成市价追单，也不得伪报已执行
* 未成交取消价必须位于从当前认证价前往入场区间的反方向，能够在任何入场档成交前先触发；取消价不得等于成交后止损

**禁止**：
* 未击中入场点强行追单（V014 违规）
* 提前进场（FOMO）
* 修改入场方向

---

### 7. 全部非空成交组合风险上限（账户独立硬规则）

**判定公式**：
```
组合风险 % = (|weighted_entry - sl| / weighted_entry) × leverage × 100

Maker 判定：每个非空成交组合风险 % ≤ 3
Main 判定：四档的 15 个非空成交组合风险 % ≤ 8
```

**无市场含义的归一化算术例**（5x 杠杆，仅验证公式）：
* Maker：weighted_entry = 100.0, sl = 100.6 → 3.0% ✓ 边界；sl = 100.8 → 4.0% ✗
* Main：weighted_entry = 100.0, sl = 101.6 → 8.0% ✓ 边界；sl = 101.7 → 8.5% ✗

**禁止**：
* 为规避风险上限而脱离结构失效锚扩大止损
* 为通过风险上限或盈亏比而把 Maker 止损压缩到入场区边缘
* 用 3%/8% 或 R:R 反解 `price_distance`，或让 decision/compiler 自行补出 observation、timeframe、buffer
* 成交后向不利方向扩大止损（V001）
* "再观察一下"延后止损
* 情绪化补仓（V004）

**理由**（2026.3.5 笔记）：
> Maker 小资金阶段用 2-3% 止损；主账户中线风险独立控制在 8% 以内
> 不是为了激进
> 而是为了在可控风险下加快复利

---

## 整体校验逻辑

```python
risk_checklist_pass = all([
    item_1_plan_recorded,
    item_2_risk_exposure,
    item_3_market_confirmation,
    item_4_sl_tp_set,
    item_5_in_time_window,
    item_6_strict_signal,
    item_7_all_fill_scenarios_within_account_limit
])

if not risk_checklist_pass:
    decision = "deny"
    plan_quality = "低"  # 触发 V002 类违规
```

---

## 与生产决策门的对应

当前引擎的 hash-bound 决策合同、报告合同与推理认证必须共同重放本清单；任一项失败即拒绝进入 canonical report。历史 risk Agent 仅作参考设计，不得进入生产 authority。

---

## 核心原则

> 缺项 = 计划质量评级"低"，属于违规风险（图谱第四节）
> 每份计划必须按本轮锁定证据完成 7/7 检核；历史违规、样本进度或旧评级不得进入当前交易判断。
