# 会话节奏规则（图谱一节 + 十七节）

> 定义每日时段触发的任务、时间窗口、并发约束。
> 由 `agents/session_orchestrator.md` 调度执行。

---

## 每日时段表（GMT+8 北京时间）

| 时段 | 任务 | 触发链 | 责任 |
|---|---|---|---|
| 00:00 | Daily Reset（归档昨日 session + 创建今日 inbox） | — | session_orchestrator |
| 09:00 - 11:00 | 早间盘前任务 | 链 A | session_orchestrator |
| **11:00** | **早间评分点** | 链 A Step 3 | scoring_agent |
| 09:00 - 12:00 | 早间 Maker 执行窗口 | — | 用户 |
| 14:00 - 18:00 | 午盘观察期 | — | 用户（减少新开仓） |
| 19:00 - 22:00 | 晚间 Maker 执行窗口 | — | 用户 |
| **20:00** | **晚间评分点** | 链 B Step 3 | scoring_agent |
| 20:00 - 20:30 | Maker 晚间新增计划生成 | 链 B | session_orchestrator |
| **23:00** | **当日 review 截止** | 链 C Step 4 | session_orchestrator |
| 周日 22:00 | 周报触发 | 链 C 加强 | review_agent |
| 月末 23:00 | 月报触发 | 链 C 加强 | review_agent |

---

## 时段允许漂移

| 时段 | 允许漂移 |
|---|---|
| 评分点（11:00 / 20:00） | ±30 分钟 |
| 早间链 A 启动 | ±60 分钟（09:00 提前 / 11:00 延后） |
| 晚间链 B 启动 | ±15 分钟（保持新数据新鲜） |
| Daily Reset | ±10 分钟（凌晨稳定窗口） |
| Review 截止 | 不允许漂移（23:00 严格） |

超出漂移上限 → session_orchestrator 写 timeout 警告但不强制中止。

---

## 任务依赖图

> 链路顺序 = 用户工作流序（权威 `sessions/日报SOP.md` §0.0；2026-05-31 迭代对齐）。

```
00:00 Daily Reset
  ↓
09:00-11:00 链 A（早间 · 严格按用户工作流序）
  ├─ Step 0 prereqs：notion-positions 校准持仓 + data_collection_agent 采集五源 + news_agent
  ├─ Step 1 门禁：emotional_agent 读「开仓前门禁/心力监控」
  │           └─ ⛔ 关闭/不可交易 → 硬停：不写任何计划，output 只出"门禁关闭·观望"
  ├─ Step 2 主账户 plan：基本面(news)>盘面结构>盘口 → 中线计划（**不依赖评分**）
  ├─ Step 3 评分：footprint_agent → scoring_agent (morning 11:00，盘口70+盘面30)
  ├─ Step 4 Maker plan：risk_agent.precheck + 评分≥70门槛 → Maker 上午计划（盘口>盘面>基本面）
  ├─ Step 5 「不能做」回填（当天 Maker 收口）+ 有开仓补「交易 Check」
  └─ Step 6 output_agent → 渲染 主账户日报(Step2) + Maker 上午计划(Step4)

19:00-20:30 链 B（晚间 Maker 新增计划）
  ├─ Step 1 data_collection_agent（只刷盘口）
  ├─ Step 2 footprint_agent
  ├─ Step 3 scoring_agent (evening 20:00 评分点)
  ├─ Step 4 risk_agent.precheck
  └─ Step 5 output_agent → Maker 晚间新增（「不能做」最后回填）

~23:00 链 C（晚间反思·复盘四件套，按序）
  ├─ Step 1 emotional_agent → 心智自控日记表
  ├─ Step 2 emotional_agent → 心力监控模块（写入，供次日早间链 A 门禁读取）
  ├─ Step 3 50 笔结晶/洁净样本 check（clean sample 进度更新）
  ├─ Step 4 review_agent → 交易 review（reviews/<today>.md）
  ├─ Step 5 penalty_agent → 违规审计
  ├─ Step 6 周日额外：review_agent.weekly_report()
  ├─ Step 7 月末额外：review_agent.monthly_report()
  └─ Step 8 写 session_log

任意时刻 链 D（数据失效重采集）
  ├─ 触发：任意 agent 报告 manifest 过期
  └─ 子链：data_collection_agent → 下游 agent 重跑
```

---

## 并发约束

* **同时刻只能有一个链运行**（防止 state 写冲突）
* 链 A 进行中若到 11:00 评分点 → 评分链合并到链 A 末尾，不并行
* 链 C **强制等待**当日链 A/B 全部完成
* 链 D 可中断 A/B（数据失效优先），但**不可中断 C**

---

## Daily Reset 详细流程（00:00）

```
1. 归档昨日：
   state/session_state.json → state/archive/session_<yesterday>.json

2. 重置 session_state.json：
   - current_day = today
   - tasks.* = false（全部任务标记重置）
   - last_task_times.* = null
   - active_agents 保持
   - context_memory 保留（last_trade_event 等由 review_agent 维护）

3. 创建当日 inbox 目录：
   data_sources/inbox/<today>/

4. 检查是否已过 09:00：
   是 → 自动触发链 A（晚启动模式）
   否 → 等待 09:00
```

---

## 时段任务字段映射

```json
"session_state.tasks": {
  "main_account_report_generated":  // 链 A Step 6 后
  "maker_daily_plan_generated":     // 链 A Step 6 后
  "score_updated_morning":          // 链 A Step 3 后
  "score_updated_evening":          // 链 B Step 3 后
  "risk_checks_completed":          // 实际开仓时由 risk_agent 写
  "review_completed":               // 链 C Step 4 后
  "data_collection_done":           // 链 A Step 0 后 / 链 B Step 1 后
  "emotional_check_done":           // 链 A Step 1 门禁读取后（写入在链 C Step 1-2）
}
```

---

## 异常时段处理

### 用户外出 / 无法操作
* 链 A 启动 → emotional_agent 等待用户回答 → 超时 5 分钟则 allow_trade_today = false
* 链 A 自动跑完到 output_agent → 输出"今日无交易资格"日报
* 链 B/C 同上流程

### 用户跨时区
* 系统始终使用 GMT+8（北京时间）
* 用户在其他时区交易需要心算时差
* 不允许修改系统时区

### 节假日 / 周末
* Maker 不交易（OKX 通常不停）
* 周末仍执行 review_agent 日复盘
* 周日 22:00 必须执行周报

---

## 强制规则

* **每日两次评分**（图谱第三节）：11:00 + 20:00
* **每日两次更新节奏**（图谱第一节）：早间 + 晚间
* **复盘必填**（图谱十七节）：每日 23:00 之前，包括未开单日
* **周报固定**：每周日 22:00
* **月报固定**：每月末 23:00

---

## 与 token_policy 的关系

`governance/token_policy.md` 定义每日 token 预算。
session_orchestrator 在启动每条链前检查剩余预算：
* 链 A：高优先级（必跑）
* 链 B：高优先级（必跑）
* 链 C：高优先级（必跑）
* 链 D：中优先级（条件触发）

→ Token 严重不足时只保 A/C，B 可降级（不再生成晚间新增）。

---

## 禁止行为

* 禁止跳过评分点（即使无交易也要评分）
* 禁止跳过 review（图谱十七节硬规则）
* 禁止链 C 在 A/B 未完成时启动
* 禁止"补做"昨日链（昨日就是昨日，过期作废）
* 禁止用户手动修改 last_task_times（必须经 agent 写入）
