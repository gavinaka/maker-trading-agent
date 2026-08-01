# Scoring Agent

> **legacy参考设计，非vNext生产authority**：下文70分叙述只保留旧设计背景。当前production盘口只允许0–60，61–69非法，70为未来原生结构化证明保留值且不可由配置单独启用；当前规则以`scoring/scoring_contract.json`与`runtime_vnext/`门为准。

## 角色
评分计算器。从 `inbox/<today>/_manifest.json` 读盘口/盘面数据，按 `scoring/*.md` 规则计算总评分，写入 `state/score_state.json`。

## 输入
* `inbox/<today>/_manifest.json`
* `inbox/<today>/exocharts_*.json`（盘口印证/footprint）
* `inbox/<today>/coinglass_*.json`（盘口核心读数）
* `inbox/<today>/tradingview_*.json`（盘面30核心源·日/4H/1H/15m 四档）
* `scoring/scoring_system.md`
* `scoring/orderflow_scoring.md`
* `scoring/chart_scoring.md`
* `scoring/score_thresholds.md`
* `data_sources/freshness_rules.md`

## 输出
* 更新 `state/score_state.json`：
  * `current_score.{total_score, orderflow_score, market_structure_score, result}`
  * `orderflow_analysis.{cvd_direction, price_direction, open_interest, funding_rate, signal_type, extreme_signal}`
  * `market_structure_analysis.*`
  * `last_update`
* 更新 `state/session_state.json`：
  * `tasks.score_updated_morning` 或 `score_updated_evening` = true
  * `last_task_times.morning_score_update` / `evening_score_update`
  * `context_memory.last_score_event`

---

# 执行流程

## Phase 1: 前置检查

1. 读 manifest
2. 校验（🟥 五源缺一不可，盘口+盘面各自核心源必须有效）：
   * `sources.coinglass.valid == true`（当前盘口0–60核心）
   * `sources.exocharts.valid == true`（盘口印证）
   * `sources.tradingview.valid == true`（盘面30核心·须日/4H/1H/15m 四档齐）
   * 各源 `freshness_minutes <= 240`（4小时新鲜，按 freshness_rules.md）
3. 任一不通过 → **中止评分**，写：
   ```
   score_state.current_score.result = "数据不全，无法评分"
   score_state.current_score.total_score = null
   ```
   退出。不允许沿用上次 score。

## Phase 2: 极端候选检查（优先级最高）

按 `scoring/score_thresholds.md` 极端候选；**2026-06-14 改：极端=候选，非机械必做 70**：

```
看跌背离候选：CVD up + Price down + OI up_or_sideways + Funding positive  → extreme_signal=true, signal="看跌背离", 推荐做空
看涨背离候选：CVD down + Price up + OI up_or_sideways + Funding negative  → extreme_signal=true, signal="看涨背离", 推荐做多

⚠️ 当前production `orderflow_score` 只能取0–60；61–69非法，70未来保留且不可由配置单独启用。取值必须由typed证据与门确定，禁止个人备注补分。
```

命中 → 标记 extreme_signal=true，**仍走 Phase 3 取 footprint 分（不跳过、不锁 70）**。

## Phase 3: 盘口评分（当前production上限60；schema名义容量70）

**本 Phase 委托给 footprint_agent 计算**。读取：
* `outputs/<today>_footprint_<HHMM>.json`（footprint_agent 输出）

直接取：
* `orderflow_score = footprint.suggested_orderflow_score`
* `signal_type = footprint.signal_type`
* `extreme_signal = footprint.is_extreme`

校验：
* `orderflow_score ∈ [0, 70]`
* `data_quality != "partial"`（否则中止）
* 命中极端候选 → 当前仍在0–60内由完整typed证据落值；不得由个人综合、备注或配置跳到70

完整 81 组合客观骨架 + 综合权衡引擎见 `scoring/orderflow_methodology.md`（旧 16 组合死查表废弃）。

## Phase 4: 盘面评分（满分 30）

按 `scoring/chart_scoring.md` 5 项分值表（图谱 3.2 节）：

| # | 指标 | 满分 | 评分依据 |
|---|---|---|---|
| 1 | 支撑/压力区间接近度 | **10** | 当前价距最近 S/R 距离；越近且未破 → 越高 |
| 2 | 多空流动性掠夺情况 | **10** | 近期是否出现 sweep；sweep 后反转入场 → 高分 |
| 3 | SMA20 突破/回踩 | **5** | 价格对 SMA20 的关系：突破并回踩确认 → 满分 |
| 4 | 量价关系 | **3** | 量能与价格方向一致 → 高 |
| 5 | 斐波/趋势线接近度 | **2** | 价格接近关键斐波位（0.618/0.786）或趋势线 → 高 |
| | **合计上限** | **30** | |

各项独立打分，求和 → `market_structure_score ∈ [0, 30]`。极致分档阈值见 [`scoring/chart_methodology.md`](../scoring/chart_methodology.md) 四节（每项 0→max 触发条件 + 校准锚）。

**说明**：
* 🟥 **两轴分离**：盘面30 = 机会质量/结构清晰度，**与方向/趋势无关**；方向由「结构性趋势」（道氏理论·见方法论三节）单独给，严禁把高盘面分读成看多/看空。
* 结构性趋势 = 道氏（HH+HL多头/LH+LL空头/否则震荡），逐周期独立、日报只报短线/中短线，仅作背景参考、不计入此项评分
* SMA20 项测「价格与 SMA20 的交互/远近」，非趋势强度：单边远离=0
* 早 11:00 / 晚 20:00 各自独立重评，禁沿用上一次
* 单项可为 0（指标不适用 / 无数据）
* 单项给分必须可追溯到 inbox 内 **TradingView 四档（日/4H/1H/15m）截图证据**（盘面=TradingView 核心源，非 exocharts；2026-06-14 订正）

---

## Phase 4.5: 校准锚点（图谱 3.1 节实际样本）

scoring_agent 输出必须能复现以下历史样本（误差 ±10 内）：

| 日期/时段 | 盘口 | 盘面 | 总分 | 结果 |
|---|---|---|---|---|
| 2026-05-15 10:00 | 30 | 21 | 51 | 观望 |
| 2026-05-15 20:00 | 60 | 15 | 75 | 可开仓 |
| 2026-05-18 20:00 | **70** | 15 | **85** | 极端组合：CVD 看跌背离 |
| 2026-05-24 11:00 | 50 | 20 | 70 | 刚达标，回调做多 |
| 2026-05-26 11:00 | 40 | 10 | 50 | 未达，观望 |

若给定相同四维数据与同期截图无法复现这些值 → 按 `scoring/orderflow_methodology.md`（81 骨架 + 综合权衡 + 真实校准锚）重新校准。

## Phase 5: 汇总

```
total_score = orderflow_score + market_structure_score
```

按 `scoring/score_thresholds.md` 区间映射 result（评分仅门槛①；最终开单还需门槛② 胜率≥60% 同时满足）：
* 0-49 → "强制观望"
* 50-64 → "默认观望"
* 65-84 → "评分达标 → 胜率≥60% 则挂标准 Maker 计划，胜率<60% 仍观望"
* 85-100 → "优先级最高 / 核心策略（仍受胜率≥60% 门槛约束）"

## Phase 6: 状态写回

原子更新 `state/score_state.json`：
* `current_score.{...}`
* `orderflow_analysis.{...}`
* `market_structure_analysis.{...}`
* `last_update = <ISO now>`

更新 `state/session_state.json`：
* 当前时段（11:00 ± 30min → morning，20:00 ± 30min → evening）对应任务标 true
* 时间戳写入 `last_task_times.*`
* `context_memory.last_score_event = "<today> <HH:MM> 评分<N> <result>"`

---

# 禁止行为

* 禁止使用过期数据强行评分
* 禁止"主观加分"
* 禁止保留上次评分（必须重算）
* 禁止跳过极端信号检查（这是宪法级规则）
* 禁止超出 0-70 / 0-30 的子分上限

---

# 异常处理

* 数据字段缺失 → 该子项 0 分，记 note，不猜
* exocharts 与 coinglass 方向冲突 → **以 coinglass 核心读数为准**（盘口四变量解读核心=coinglass 截图；exocharts 仅印证/更细颗粒参照），写 note 提示冲突。`orderflow_system.priority: highest` 指盘口系统整体优先级最高，非 exocharts 优先（2026-06-14 用户校准）
* signal_type 不确定 → "中性"
