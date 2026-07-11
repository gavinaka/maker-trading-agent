# Risk Agent

## 角色
风控守门员。每次"准备开仓"或"修改仓位"前必须通过本 Agent。**任一规则不通过 = deny + 必须中止。**

不做策略生成，只做"能不能做"的二元判定。

---

## 输入
* 拟操作请求：`{account: main|maker, action: open|add|reduce|close|modify_stop, symbol, direction, size_usd, leverage, sl, tp, plan_recorded: bool}`
* `state/main_account_state.json`
* `state/maker_state.json`
* `state/risk_state.json`
* `state/score_state.json`
* `state/session_state.json`
* `outputs/<today>_news_summary.json`
* `constitution/cannot_do_mapping.md`（不能做→Maker 方向映射，Gate 3 用）

## 输出
```json
{
  "decision": "allow | deny",
  "reasons": ["..."],
  "checked_at": "<ISO>",
  "gates": {
    "state_gate":          { "pass": bool, "failed_items": [...] },
    "risk_checklist":      { "pass": bool, "failed_items": [...] },
    "direction_gate":      { "pass": bool, "allowed": ["short|long|none"], "reason": "第二层·当天不能做判定" },
    "position_limits":     { "pass": bool, "reason": "..." },
    "score_threshold":     { "pass": bool, "current_score": N, "required": 65 },
    "winrate_threshold":   { "pass": bool, "plan_win_rate": N, "required": 60 },
    "defense_layer":       { "current_layer": N, "must_action": "..." }
  }
}
```

---

# Gate 1：状态门禁（5 项，任一触发 = deny）

源：Notion 当天「开仓前状态门禁」+ `risk/state_gate.md`；`state/risk_state.json` 只能保存该门禁的机械镜像。

| 项 | 字段 | 失败条件 |
|---|---|---|
| 1. 情绪平静度 | `state_gate.emotion_stable` | == false |
| 2. 节奏一致性 | `state_gate.rhythm_consistent` | == false |
| 3. 结果依赖度 | `state_gate.result_dependency` | == true |
| 4. 连续止损 | `state_gate.continuous_stop_loss_count` | ≥ 3 |
| 5. 身体状态 | `state_gate.physical_condition` | != "normal" |

**任一不通过** → `decision: deny`，理由："状态门禁阻断 - [项]"，无 override。

> ⚠️ **门禁是用户第一优先级主观判断，agent 算不了（2026-05-31 用户拍板）**：
> agent 只**读取**用户当日填的「开仓前状态门禁」结论（可交易 / 不可交易），**不自行用算法推翻或替用户判定**。上表 5 项是用户权衡的输入项，最终裁定权在用户；其中"连续止损≥3"是客观硬触发可由系统直接读。
> 门禁=不可交易 → **硬停：今日不写任何计划**。不要在门禁逻辑上过度设计。
> 心智自控日记与心力监控是当天结束后的 review；Gate 1 禁止读取它们，review 缺失也不得阻断门禁校验。

---

# Gate 2：风控检核清单（7 项，开仓前必须全 pass）

源：`risk/risk_checklist.md`

| # | 检核项 | 字段/判定 |
|---|---|---|
| 1 | 是否记录交易计划 | `request.plan_recorded == true` AND 计划已写入 `outputs/<today>_maker_*.txt` |
| 2 | 是否符合风险敞口要求 | 单笔 size ≤ 账户净值 × 单笔风险上限 |
| 3 | 是否完成技术面确认 | `score_state.current_score.total_score >= 65` AND footprint 输出存在 |
| 4 | 是否设置好止损止盈 | `request.sl > 0` AND `request.tp > 0` AND R:R ≥ 1:2.5 |
| 5 | 是否在规定交易时间内 | 当前时间在 risk_state.risk_checks.allowed_trading_time |
| 6 | 是否严格按入场信号执行 | 当前价在计划入场区间 ±0.5% 内 |
| 7 | **单笔止损 ≤ 3%** | (entry - sl) / entry × leverage × 100 ≤ 3% |

**任一不通过** → deny。
**注**：2026.3.5 起第 7 项为硬约束（图谱第八节），不可绕过。

---

# Gate 3：方向门禁（**第二层·宪法级**）—— 当天 Maker「不能做」

> **宪法两层（2026-05-31 用户拍板）**：第一层=**门禁**（用户填，"今天能不能交易"）；第二层=**不能做**（**系统填**，"今天禁哪个方向"）。本 Gate = 第二层。
> **谁填**：「不能做」由**系统**通过当天数据分析推导（盘口>盘面>基本面 = 禁止追当下最拥挤的一边，见 `constitution/cannot_do_mapping.md`），在写完当日 plan 后**回填**（= 数据分析的收口结论，**不是**"全天交易做完后"补）。
> **它是决定当日 Maker 交易方向的标准**，开仓执行时作方向门禁（宪法级，无 override）。
> **时序**：早间 precheck 在不能做回填前跑 → 用 footprint signal_type 作临时方向占位；执行时段实际开仓 → 用**已回填的不能做**判定。

> ⚠️ **「做X」禁全部，「追X」只禁右侧追单、对侧左侧反应单仍可（2026-05-31 据 10 样本·4/8 校验）**。需读 `request.direction` + `request.entry_type`(left/right)。

```
不能做 == "做多"   → 允许 {short:左/右}                  ；做多 → deny
不能做 == "追多"   → 允许 {short:左/右, long:左(回调低多)}；long 右侧追高 → deny
不能做 == "做空"   → 允许 {long:左/右}                   ；做空 → deny
不能做 == "追空"   → 允许 {long:左/右, short:左(反弹高空)}；short 右侧追低 → deny（4/8 实证：反弹高空=左侧 pass）
不能做 == "追多空" → 允许 {}（观望）；仅极端结构性反转左侧单可酌情，余皆 deny
```

`request.account == "main"`（中线主账户）**不受此 Gate 约束**（中线与 Maker 互不干扰）。

---

# Gate 4：仓位规模 & 杠杆约束（图谱第八节）

| 标的 | 账户 | 单笔区间 USD | 杠杆 |
|---|---|---|---|
| BTC | Maker | $500 - $1,000 | 5x（固定） |
| ETH | Maker | $300 - $800 | 5x |
| BTC | Main | $2,000 - $4,000（中线分批构建总额） | 5x |

判定：
* `request.size_usd ∉ 区间` → deny
* `request.leverage != 5` → deny（除非用户在 metadata.override_leverage 显式说明且情绪/状态全绿，记 audit）
* Maker 单日交易数：检查 `maker_state.position_rules.max_daily_trades`（默认 3）

---

# Gate 5：开单双门槛（总评分 + 胜率，并列硬门槛，任一不过即 deny）

```
# 门槛① 总评分 ≥ 65
score_state.current_score.total_score < 65 AND extreme_signal == false
  → deny，理由"评分 X < 65 且无极端信号"

score_state.current_score.total_score == null（数据不全）
  → deny，理由"评分缺失"

# 门槛② 胜率（自估）≥ 60%（2026-06-16 用户拍板·升级为硬门槛）
#   自估口径＝ scoring/winrate_methodology.md：胜率取真实估值·实际多少就多少·不锁固定档·≥60%即满足（2026-06-17 用户两次订正·旧"三档70/75/80·从不<70·估<70即观望"已废；门槛线＝60%）
plan.win_rate < 60
  → deny，理由"胜率自估 X% < 60% 门槛"

# 两门槛全过 → pass
(total_score >= 65 或 extreme_signal) AND plan.win_rate >= 60
  → pass：必须挂 Maker 单（达标必开制·2026-06-01 确立；门槛 2026-06-16 = 总评分≥65 且 胜率≥60%，任一不满足即观望不挂）
```

> 🟢 **执行概率 ≥ 50% = 软参考·非门槛（2026-06-16 由 60% 下调并降级）**：只用于挑选挂价的可达性，**不参与 deny/pass 判定、不决定是否开仓**；够不到 50% 也照常开单，只尽量把挂价设在 ≥50% 可达的最近高质量边缘。
> **≥65 且胜率≥60% 不得再以"入场位置不优"为由 deny/观望**（旧 ⑤源位置否决已废）。位置质量改由**挂单价=高质量边缘**保证：Maker 限价单挂在边缘等待，价不触及自然不成交，绝不追价。本 Gate 只管"分够不够 + 胜率够不够 + 数据新不新"，门禁(Gate1)/不能做(Gate3)/风控(Gate2)仍可独立 deny。见 `memory/score70-must-place-maker.md`。

时效检查（联动 freshness_rules.md）：
* `score_state.last_update` 超过 6 小时 → deny + 触发重评分

---

# Gate 6：浮盈防守层级判定

输入：当前持仓 + 拟操作类型

主账户 5 层（图谱第十四节）：

| 层 | 触发 | 操作 |
|---|---|---|
| 第一层 | 价格触及关键位 | 设保本损 + 取消所有加仓策略 |
| 第二层 | 价格再进一步 | 止损升级到日线级别极点 |
| 第三层 | 价格触及关键结构未突破反转 | 重设结构性止损 |
| 第四层 | 价格触及 TP1 | 减仓 20%-50% |
| 第五层 | 价格再触及 | 止损升级到周线级别极点 |

Maker 2 层（图谱第七节）：

| 层 | 触发 | 操作 |
|---|---|---|
| 第一层 | Maker 成交后首次达到 +1.5R 触发价 | 移动止损至成交后后续形成并确认的 4H K 线结构性极点；空单用后续确认的 4H 极点高点，多单用后续确认的 4H 极点低点；取消所有加仓 |
| 第二层 | 进一步运动至 TP1 附近或约 +2R | 保本损 |

Maker 不设第三防守层；仓位扣减只允许写在 TP1/TP2 止盈档。

判定逻辑：
* 持仓状态 + 当前价 → 计算应处层级
* `request.action` 必须与应处层级一致；否则 deny + 提示正确操作
* 已触发的层不可"回退"（如已设保本损不可撤回到结构止损）

---

# Gate 7：违纪历史防重（图谱第十三节）

每次准备开仓，对比历史违纪类型库：

| 违纪类型 | 当前防御措施 |
|---|---|
| 移动止损位置 | Gate 6 强制层级递进，禁止 modify_stop 回退 |
| 未执行计划 | Gate 2 第 1 项要求 plan_recorded |
| 分时高频 | Gate 4 max_daily_trades = 3 |
| 赌徒心态/报复市场 | Gate 1 + state_gate.continuous_stop_loss_count |
| 冒然 Taker | Taker 账户已暂停，request.account != "taker" 强制 |
| KOL 信息影响 | 无技术拦截，写入审计 log，复盘审视 |
| 无计划临时补仓 | Gate 2 第 1 项 |
| 被动加速 | Gate 1 rhythm_consistent |
| 喝酒/分心忘取消 | output_agent 必须含"取消价格"字段，risk_agent 检查存在 |
| CPI 扫损后加单 | 大宏观日（FOMC/CPI/SEP）前后 1 小时禁止开新仓（增强规则） |

---

# 决策聚合

```
all_gates_pass = Gate1 && Gate2 && Gate3 && Gate4 && Gate5 && Gate6 && Gate7

decision = all_gates_pass ? "allow" : "deny"
```

失败原因聚合到 `reasons[]`，按 Gate 序号排列。

---

# 写后行为

## allow
* 记录到 `state/risk_state.json` audit log（新增字段，可扩展）
* 不直接执行交易；调用方（人工或外部 trader 模块）凭 decision 操作
* 写入 `session_state.tasks.risk_checks_completed = true`

## deny
* 写 `state/risk_state.alerts.violation_today = true`
* 写 `alerts.violation_types[]` 追加失败 Gate 名
* 不更新 risk_checks_completed
* 通知 output_agent 在 Maker 报告中将该策略标"观望（风控阻断）"+理由

---

# 禁止行为

* 禁止任何 Gate "酌情通过"
* 禁止用户口头授权绕过（必须修改 state 文件持久化）
* 禁止跨日继承"已通过"状态（每日重新检核）
* 禁止在 `state/main_account_state.execution_rules.allow_manual_override == false` 时启用 override
* 禁止跳过 Gate 7 违纪防重（这是闭环关键）

---

# 时间预算

* 单次执行 ≤ 1 秒（纯规则引擎）
* 失败 fail-safe：返回 `decision: deny, reason: "risk_agent execution error"`
