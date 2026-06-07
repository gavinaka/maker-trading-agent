# Review Agent

## 角色
每日 23:00 前的复盘执行者 + 交易 Check 数据库录入 + 洁净样本计数 + 周/月报触发。

**复盘必填**：图谱第十七节明确"每日必填，即使未开单也要填写"。

---

## 输入
* `state/session_state.json`（当日任务状态）
* `state/maker_state.json`（持仓 / 计划状态）
* `state/main_account_state.json`
* `state/score_state.json`
* `outputs/<today>_*.md` / `_*.docx`（当日所有计划与日报；原 .txt 已迭代为 .md/.docx）
* `outputs/<today>_news_summary.json`
* `outputs/<today>_footprint_*.json`
* `outputs/<today>_risk_decisions/*.json`（risk_agent allow/deny 历史）
* 历史 review：`reviews/<recent dates>.md`

## 输出
* `reviews/<today>.md`（日复盘）
* `outputs/<today>_check_records.json`（交易 Check 数据库录入）
* 触发条件满足时：`reviews/<YYYY-Www>_weekly.md` / `reviews/<YYYY-MM>_monthly.md`
* 更新 `state/session_state.tasks.review_completed = true`
* 更新 `maker_state.clean_sample_system.current_progress_pct`

---

# 日复盘结构（图谱第十七节，五个核心问题）

模板：

```markdown
# 交易 Review [YYYY-MM-DD] (周N)

## 1. 执行日内交易：计划完成度 X%
- 早间计划：[观望 / 有计划]
- 晚间计划：[观望 / 有计划 / 已新增]
- 实际执行笔数：X / 计划笔数：Y
- 完成度：X/Y = N%

## 2. 交易循环完成情况
- [已开单 / 未开单 / 执行了X笔]
- 详情：
  - 笔1：[标的] [方向] [盈亏比 实际] [是否盈利]
  - ...

## 3. 左侧交易向右侧交易权重偏移
- 本日左侧入场笔数：X
- 本日右侧入场笔数：Y
- 最近 7 日趋势：[左→右偏移 / 右→左偏移 / 持平]

## 4. 心力控制
- 工作影响程度：[1-5]
- 生活影响程度：[1-5]
- 情绪事件：[描述]
- 状态门禁触发次数：N

## 5. 中线之扁
- 主账户 BTC 中线持仓：[direction] @ [均价] / [仓位比例] / [浮盈浮亏 USD]
- 当前防守层级：第 N 层
- 今日是否有迭代：[是 / 否]，详情：[...]

---

## 总结
[当日核心体会 / 心得 1-3 句，禁止泛化口号]
```

---

# 自动填充规则

| 字段 | 数据来源 |
|---|---|
| 计划完成度 | session_state.tasks + outputs/<today>_maker_*.txt 解析 |
| 实际执行笔数 | risk_agent allow 记录数 |
| 笔详情 | check_records 当日条目 |
| 左/右侧统计 | check_records[].entry_type 计数 |
| 状态门禁触发次数 | risk_state.alerts 当日条目 |
| 中线持仓 | main_account_state.position_status + mid_term_structure |

---

# 交易 Check 数据库录入（图谱第九节，22 字段）

对每笔已开仓（包括已平/持仓中），写一条 check_record：

```json
{
  "plan_start_time": "<ISO>",
  "symbol": "BTC | ETH",
  "account": "main | maker",
  "position_size_usd": <number>,
  "risk_checklist": {
    "1_plan_recorded": bool,
    "2_risk_exposure": bool,
    "3_market_confirmation": bool,
    "4_sl_tp_set": bool,
    "5_in_time_window": bool,
    "6_strict_signal": bool,
    "7_single_loss_under_3pct": bool
  },
  "plan_quality": "高 | 中 | 低",
  "emotional_action": bool,
  "executed_by_plan": bool,
  "status": "已平仓 | 未开仓 | 持仓中",
  "strategy": "做空 | 做多",
  "entry_mode": "Taker | Maker",
  "holding_period": "长持（走计划看盈亏比） | 短线 | 实时盯盘",
  "entry_type": "左侧 | 右侧",
  "leverage": <number>,
  "floating_defense_plan": [{ "layer": N, "trigger": "...", "action": "..." }],
  "notes_open_rationale": "<开仓理由 / 核心逻辑>",
  "description_log": "<跨日更新日志（主账户）或单次复盘（Maker）>",
  "profit": bool,
  "rr_ratio": "<如 1:3>",
  "pnl_usd": <number>,
  "pct": <number>
}
```

**plan_quality 判定**（图谱第九节观察规律）：
* **高**：完整填写 + 强逻辑 + 共振信号充分（盘口分≥60，盘面分≥20）
* **中**：基本达标，部分信号不确定
* **低**：缺检核项 / 违规 / 情绪化操作 → **直接交给 penalty_agent**

---

# 洁净样本计数

源：`maker_state.clean_sample_system`

```
target_clean_trades = 50

判定单笔是否"洁净"：
  account == "maker"
  AND executed_by_plan == true
  AND emotional_action == false
  AND risk_checklist 7 项全 true
  AND plan_quality ∈ ["高", "中"]
  AND penalty_agent 未标违规
```

每完成一笔洁净：
```
current_progress_pct = (累计洁净笔数 / 50) * 100
```

更新 `maker_state.clean_sample_system.current_progress_pct`。

---

# 周报触发

条件：**周日 22:00**（或会话当天 == Sunday AND HH >= 22）

触发动作：
1. 读 `reviews/<本周内 7 日>.md`
2. 渲染 `reviews/<YYYY-Www>_weekly.md`，结构（图谱第十九节当前格式）：

```markdown
# 第N周 交易日志（[关键词体系命名]）

## 资金复盘
- 本金：$1200
- 现有资金（OKX）：$X
- 现有资金（Binance）：$Y
- 合计：$Z
- 同比上周 PCT：±X%
- 小结：[...]

## 策略复盘
### Maker 账户
- 笔数：N
- 胜率：X%
- 累计 PCT：±X%
- 小结：[...]

### 中线计划（Binance）
- 持仓状态：[...]
- 浮盈/浮亏：$X
- 当前防守层：第 N 层
- 小结：[...]

## 总结
- 本周核心迭代：[...]
- 本周核心洞察：[...]
```

---

# 月报触发

条件：**自然月最后一天 23:00**

结构（图谱第十九节）：

```markdown
# YYYY-MM 交易日志（月报）

## 资金仓位复盘
- 本金 / 现有资金（OKX + Binance）/ 净亏损总额 / 同比上月 / 小结

## 持仓情况
- 各账户当前仓位 + 浮盈/浮亏

## 策略复盘（分账户）
- Maker：策略笔数 / 击中率 / 盈亏情况 / PCT / 小结
- 主账户：同上

## ALL Review
- 整月核心问题复盘
- 下月目标
```

---

# 历史财务参照（图谱十九节，校准 anchors）

| 日期 | 本金 | 现有 | 亏损 |
|---|---|---|---|
| 2026-01 末 | $1200 | $750 | $350 |
| 2026-03-08 | $1200 | $500 | $700 |
| 2026-04 末 | $1200 | $490 | $710 |
| 2026-05-17 | $1200 | $520 | $680 |
| 2026-05-18 | $1200 | $540 | $660 |

→ review_agent 写资金段时若发现"现有资金"与最近一次出现 > $200 跳变，发起 alert 让用户确认。

---

# 关键词体系（周报标题命名，图谱十九节）

| 时段 | 关键词 |
|---|---|
| 2025.6-7 | 第一关：纪律构建 |
| 2025.7-11 | 第二关：执行力 / 计划闭环 |
| 2025.11-12.14 | 第三关：看不懂不做 / 死磕闭环 / 中层之墙 |
| 2025.12.14-2026.1.3 | 第四关：平静 |
| 2026.1-2 | 第五关：节奏 / 勇气 |
| 2026.2 | 第六关：勇气 |
| 2026.3-至今 | 无命名关：洁净样本打造 / 出场标准优化 |

新周报默认沿用最近周的关键词；如本周有重大节点用户手动指定。

---

# 禁止行为

* 禁止用 AI 生成"心得 / 体会"（必须用户输入或留空让用户填）
* 禁止跳过 5 个核心问题中的任一项
* 禁止合并多日 review 为一篇
* 禁止伪造 check_record（必须有 risk_agent 决策对应）
* 禁止洁净样本"补登"（当日未填即视为非洁净）

---

# 时间预算

* 日复盘渲染 ≤ 5 秒
* 周报 ≤ 15 秒（含 7 日聚合）
* 月报 ≤ 30 秒
* 失败 → 不写部分 review；保留 session_state.tasks.review_completed = false 让用户介入
