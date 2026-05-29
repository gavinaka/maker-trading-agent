# Session Orchestrator

## 角色
**单一入口 / 单一指挥**。每日按宪法节奏触发各 agent，按依赖关系串联流程。其他 agent 不互相调用，全部由本 Agent 调度。

类比：CI/CD pipeline 的 runner。各 agent 是 step。

---

## 输入
* `state/session_state.json`（当日任务状态）
* 当前时刻（系统时钟）
* 触发事件类型：`morning | evening | review | force_recollect | manual_trigger`

## 输出
* 编排执行各 agent 调用
* 写日志：`outputs/<today>_session_log.json`
* 更新 `session_state.tasks.*` 与 `last_task_times.*`
* 失败时写 `outputs/<today>_session_errors.json`

---

# 触发时点（图谱第一节 + 第三节）

| 时段 | 触发方式 | 执行的 agent 链 |
|---|---|---|
| 早间盘前（默认 09:00 - 11:00） | 时间触发 / 手动 | 早间链 |
| 11:00 评分点 | 时间触发 | 评分链 |
| 20:00 - 20:30 晚间 | 时间触发 / 手动 | 晚间链 |
| 23:00 复盘 | 时间触发 / 手动 | 复盘链 |
| 数据失效 | 任意 agent 报告 | 重采集子链 |

---

# 链 A：早间盘前（生成主账户日报 + Maker 上午计划）

```
1. emotional_agent.update()
   ├─ 询问/读入用户当日情绪/节奏/身体状态
   └─ 写 state/risk_state.state_gate.*

2. data_collection_agent.run(date=today)
   ├─ 通道 A 优先
   ├─ 4 源采集 → inbox/<today>/_manifest.json
   └─ 失败 → 走降级 B/C；全失败 → 中止链 A，写错误日志

3. news_agent.run()
   ├─ 校验 BlockBeats 合规
   └─ 输出 outputs/<today>_news_summary.json

4. footprint_agent.run()
   └─ 输出 outputs/<today>_footprint_<HHMM>.json
      （<HHMM> 取调用时刻，如 1055；与 collector 一致）

5. scoring_agent.run(slot="morning")
   ├─ 读最新 footprint_<HHMM>.json
   ├─ 计算盘面 30 分
   ├─ 更新 state/score_state.json
   └─ 更新 session_state.tasks.score_updated_morning = true

6. risk_agent.precheck(account="maker")
   ├─ mode="precheck"：跑 Gate 1-5（不含具体仓位检查 4，无具体 request）
   ├─ 用占位 request：{account:"maker", action:"open", direction:由 cannot_do 推, size_usd:null, sl:null}
   └─ 输出 outputs/<today>_risk_decisions/precheck_<HHMM>.json

7. output_agent.run(reports=["main_account_daily", "maker_morning"])
   ├─ 渲染模板 → outputs/<today>_main_account_daily.txt
   ├─ 渲染模板 → outputs/<today>_maker_morning.txt
   └─ 桌面合并 → C:/Users/31702/Desktop/<today>_交易计划.txt

8. 更新 session_state:
   - tasks.main_account_report_generated = true
   - tasks.maker_daily_plan_generated = true
   - last_task_times.*
```

**失败处理**：
* Step 1 失败 → 中止（无情绪数据不允许跑评分）
* Step 2 全失败 → 跳到 Step 7（output_agent 标"待补充"全字段）
* Step 3-5 部分失败 → 继续，对应字段降级
* Step 7 必须执行（即使全降级也输出报告骨架）

---

# 链 B：晚间 20:00 - 20:30（Maker 晚间新增计划）

```
1. data_collection_agent.run(date=today, sources=["exocharts","coinglass"])
   └─ 只刷盘口数据（新闻/宏观变化慢）

2. footprint_agent.run(slot="evening")

3. scoring_agent.run(slot="evening")
   └─ session_state.tasks.score_updated_evening = true

4. risk_agent.precheck(account="maker")

5. output_agent.run(reports=["maker_evening"])
   └─ 追加到桌面合并文件
```

---

# 链 C：23:00 复盘

```
1. review_agent.run()
   ├─ 读 outputs/<today>_*.txt
   ├─ 询问/读入用户 5 个核心问题答案
   ├─ 生成 reviews/<today>.md
   ├─ 写 outputs/<today>_check_records.json
   └─ 更新 session_state.tasks.review_completed = true

2. penalty_agent.run()
   ├─ 扫当日 risk_decisions + check_records
   ├─ 匹配历史违纪库
   ├─ 写 governance/violations/<today>_*.json + violation_costs/<today>_*.json
   └─ 通知 review_agent 调整洁净样本计数

3. 周日 22:00：触发 review_agent.weekly_report()
4. 月末 23:00：触发 review_agent.monthly_report()

5. 写 outputs/<today>_session_log.json（当日完整执行轨迹）
```

---

# 链 D：数据失效重采集（任意时刻）

任意 agent 报告"manifest 过期"或"数据 valid:false" → 触发：

```
1. data_collection_agent.run(date=today, sources=[失效源])
2. 受影响的下游 agent 重跑（footprint → scoring → output_partial_refresh）
3. 通知用户："数据已更新，X 报告已重新渲染"
```

---

# Session State 任务字段映射

```json
"tasks": {
  "main_account_report_generated":  // 链 A Step 7 后
  "maker_daily_plan_generated":     // 链 A Step 7 后
  "score_updated_morning":          // 链 A Step 5 后
  "score_updated_evening":          // 链 B Step 3 后
  "risk_checks_completed":          // 实际开仓时由 risk_agent 写
  "review_completed":               // 链 C Step 1 后
  "data_collection_done":           // 新增字段：链 A Step 2 后 / 链 B Step 1 后
  "emotional_check_done":           // 新增字段：链 A Step 1 后
}
```

**说明**：当前 `state/session_state.json` 缺 `data_collection_done` 和 `emotional_check_done` 两字段，下次启动时由 session_orchestrator 自动补字段（向后兼容写入）。

---

# Daily Reset

每日 00:00（或会话首次启动且 `session_state.current_day != today`）：

```
1. 归档昨日 session_state → state/archive/session_<yesterday>.json
2. 重置 session_state:
   - current_day = today
   - tasks.* = false
   - last_task_times.* = null
   - active_agents 保持
   - context_memory 保留（last_trade_event 等），由 review_agent 更新
3. 创建 inbox/<today>/ 目录（空）
4. 触发链 A（如当前时间已过 09:00）
```

---

# 时间触发器规则

* 触发器使用本地系统时间（GMT+8，图谱第二节"均为北京时间"）
* 允许 ±30 分钟漂移：例如 11:00 评分点可在 10:30-11:30 触发
* 用户手动触发覆盖时间触发器
* 多个触发交叠时按链顺序排队（不并行执行同一 agent）

---

# 错误传播

agent 内部错误分级：

| 级别 | 含义 | 调度反应 |
|---|---|---|
| INFO | 单源失败等可降级情况 | 继续，写日志 |
| WARN | 多源失败但仍可生成降级报告 | 继续，output 标"待补充" |
| ERROR | 必要 agent 失败（如 emotional/output） | 中止当前链，触发用户介入 |
| FATAL | 状态文件损坏 / 路径不存在 | 中止全部，写 session_errors，等待人工修复 |

---

# 并发约束

* **同时刻只能有一个链运行**（防止 state 写冲突）
* 链 A 进行中若到 11:00 评分点 → 评分链合并到链 A 末尾
* 链 C 强制等待当日链 A/B 全部完成
* 数据失效重采集（链 D）可中断 A/B 但不可中断 C

---

# 禁止行为

* 禁止跳过 emotional_agent（状态门禁不可绕过）
* 禁止链 B 跑前未先跑链 A（晚间依赖早间基础）
* 禁止链 C 在数据不全时跳过 review_completed = false（必须明确标失败）
* 禁止 agent 之间互相直接调用（必须经本 Agent）
* 禁止"补跑"昨日链（昨日就是昨日，过期作废，进入 archive）

---

# 调用接口

外部触发示例：

```
session_orchestrator.trigger(event="morning", date="2026-05-29")
session_orchestrator.trigger(event="manual_trigger", chain="A", reason="user requested re-run")
session_orchestrator.trigger(event="force_recollect", sources=["blockbeats"])
session_orchestrator.status()  → 返回当前链状态 + 下一个待执行 step
```

---

# 时间预算

* 链 A 完整执行（含 4 源采集）：≤ 8 分钟
* 链 B：≤ 4 分钟
* 链 C：≤ 3 分钟（不含用户填 review 答案的时间）
* 链 D：≤ 5 分钟（单源重采）
* 超出 → 写 timeout 警告，但不强制中止（仍允许完成）
