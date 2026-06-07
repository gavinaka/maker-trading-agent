# Agents 索引

> ⚠️ **参考设计层**：本目录的 10 个 Agent + `session_orchestrator` 自动机为**设计稿**，当前**未作为自动机运行**；每日实际运行 = `/daily-report` skill + `sessions/日报SOP.md` + 项目 `memory/` + Notion REST + `outputs/*.py`。真相源 = Notion 对应库。详见仓库 README「双层架构说明」。
>
> Trading-System 内 **10 个 Agent** 的总览 + 调用关系图。
> 所有 Agent 由 `session_orchestrator` 统一调度（agent 之间不互相直接调用）。

---

## 10 个 Agent 列表

| # | Agent | 角色 | 输入 | 输出 |
|---|---|---|---|---|
| 0 | **session_orchestrator** | 总调度，按时段/链触发其他 agent | session_state + 当前时刻 | 编排链 A/B/C/D 执行 |
| 1 | **emotional_agent** | 情绪 + 状态门禁（5 项）采集 | 用户自报 + risk_state | risk_state.state_gate.* + emotional_log |
| 2 | **data_collection_agent** | 4 数据源采集，A→B→C 通道降级 | session_state + collectors SOP | inbox/_manifest.json + 截图/JSON |
| 3 | **news_agent** | BlockBeats 强制截图校验 + sentiment | inbox/blockbeats_*.png/.txt | outputs/news_summary.json |
| 4 | **footprint_agent** | 盘口 16 组合表 + 4 维状态判定 | inbox/exocharts_*.json + coinglass_*.json | outputs/footprint_<HHMM>.json |
| 5 | **scoring_agent** | 盘口 70 + 盘面 30 = 总评分 | footprint 输出 + chart 数据 | state/score_state.json |
| 6 | **risk_agent** | 7 Gate 守门（含 5 项门禁 + 7 项检核） | request + state/* | outputs/risk_decisions/*.json |
| 7 | **output_agent** | 日报/计划渲染（图谱十/十一节模板） | state + manifest + footprint + news | outputs/*.md + 桌面 .txt |
| 8 | **review_agent** | 23:00 五问复盘 + 周/月报 + check_records | outputs/* + 用户输入 | reviews/*.md + check_records.json |
| 9 | **penalty_agent** | V001-V014 模式匹配 + 4 级处罚 | risk_decisions + check_records | governance/violations/*.json |

---

## 调用关系图

```
                        session_orchestrator
                                │
            ┌───────────────────┼───────────────────┐
            ↓                   ↓                   ↓
          链 A 早间           链 B 晚间            链 C 复盘
            │                   │                   │
            ↓                   ↓                   ↓
    1. emotional_agent    1. data_collection   1. review_agent
            │                   │                   │
            ↓                   ↓                   ↓
    2. data_collection    2. footprint         2. penalty_agent
            │                   │                   │
            ↓                   ↓                   ↓
    3. news_agent         3. scoring (evening)  3. weekly/monthly
            │                   │                  （周日/月末）
            ↓                   ↓
    4. footprint_agent    4. risk_agent.precheck
            │                   │
            ↓                   ↓
    5. scoring (morning)  5. output_agent
            │                   ↓
            ↓               maker_evening.md
    6. risk_agent.precheck
            │
            ↓
    7. output_agent
            ↓
   main_account_daily.md
   + maker_morning.md
   + 桌面合并 .txt
```

---

## 数据流（按时间顺序）

```
[早间 09:00-11:00]
  用户回答 5 项情绪 → emotional_log.json
                              ↓
  4 数据源采集 → inbox/_manifest.json + 截图/.json
                              ↓
  BlockBeats 截图校验 → news_summary.json
                              ↓
  16 组合表判定 → footprint_<HHMM>.json
                              ↓
  盘口 70 + 盘面 30 → score_state.json (current_score)
                              ↓
  7 Gate precheck → risk_decisions/precheck_<HHMM>.json
                              ↓
  模板渲染 → main_account_daily.md + maker_morning.md + 桌面 .txt

[晚间 20:00-20:30]
  增量采集（仅盘口）→ inbox/_manifest.json 更新
                              ↓
  scoring + risk precheck
                              ↓
  maker_evening.md → 桌面 .txt 追加

[23:00 复盘]
  五问 + check_records 录入 → reviews/<today>.md + check_records.json
                              ↓
  违规模式匹配 → governance/violations/<NNN>.json
                              ↓
  洁净样本计数 → maker_state.json.clean_sample_system 更新
```

---

## 状态文件读写权限

| state 文件 | 唯一写者 | 读者 |
|---|---|---|
| main_account_state.json | 用户 + emotional_agent（state_gate 子集） | output_agent / risk_agent / review_agent |
| maker_state.json | emotional_agent（state_gate 子集）+ review_agent（clean_sample） | output_agent / risk_agent |
| market_state.json | 用户（手动维护）| 各 agent 参考 |
| score_state.json | **scoring_agent**（唯一） | output_agent / risk_agent |
| session_state.json | **session_orchestrator** + 部分 agent（tasks 段） | 全 agent |
| risk_state.json | emotional_agent（state_gate canonical）+ risk_agent（alerts） | 全 agent |

**Canonical 规则**：`risk_state.state_gate.*` 是 5 项状态门禁的唯一权威；其他 state 中的 state_gate 是冗余副本，emotional_agent 保证一致。

---

## 输出文件路径速查

```
outputs/<YYYY-MM-DD>_main_account_daily.md    ← output_agent
outputs/<YYYY-MM-DD>_maker_morning.md          ← output_agent
outputs/<YYYY-MM-DD>_maker_evening.md          ← output_agent
outputs/<YYYY-MM-DD>_news_summary.json         ← news_agent
outputs/<YYYY-MM-DD>_footprint_<HHMM>.json     ← footprint_agent
outputs/<YYYY-MM-DD>_emotional_log.json        ← emotional_agent
outputs/<YYYY-MM-DD>_risk_decisions/<HHMMSS>_<mode>.json  ← risk_agent
outputs/<YYYY-MM-DD>_check_records.json        ← review_agent
outputs/<YYYY-MM-DD>_session_log.json          ← session_orchestrator

reviews/<YYYY-MM-DD>.md                        ← review_agent (日)
reviews/<YYYY-Www>_weekly.md                   ← review_agent (周)
reviews/<YYYY-MM>_monthly.md                   ← review_agent (月)

data_sources/inbox/<YYYY-MM-DD>/_manifest.json ← data_collection_agent
data_sources/inbox/<YYYY-MM-DD>/*.png + *.json ← collectors per SOP

governance/violations/<YYYY-MM-DD>_<NNN>.json     ← penalty_agent
governance/violation_costs/<YYYY-MM-DD>_<NNN>.json ← penalty_agent

C:/Users/31702/Desktop/<YYYY-MM-DD>_交易计划.txt    ← output_agent (桌面合并)
```

---

## 调用模式

### 触发方式
* **时间触发**：00:00 Reset / 09:00 链 A / 20:00 链 B / 23:00 链 C / 周日 22:00 周报 / 月末 23:00 月报
* **手动触发**：用户在对话中说"跑早间"/"重采集 BlockBeats"等
* **失效触发**：链 D 由数据失效自动触发

### 接口
```
session_orchestrator.trigger(
  event="morning" | "evening" | "review" | "force_recollect" | "manual_trigger",
  date="YYYY-MM-DD",
  ...
)
```

详见 `agents/session_orchestrator.md`。

---

## 各 Agent 的禁止行为汇总

| Agent | 关键禁止 |
|---|---|
| session_orchestrator | 禁止跨链并行；禁止跳过 emotional_agent |
| emotional_agent | 禁止 AI 自动判定情绪；禁止跳过 5 项采集 |
| data_collection_agent | 禁止伪造数据；禁止 BlockBeats 走通道 B |
| news_agent | 禁止文字替代截图；禁止 AI 总结 |
| footprint_agent | 禁止跳过 C01/C02 极端组合判定 |
| scoring_agent | 禁止使用过期数据；禁止主观加分 |
| risk_agent | 禁止酌情通过 Gate；禁止 user override |
| output_agent | 禁止省略模板字段；禁止 AI 生成基本面/总结 |
| review_agent | 禁止 AI 写"总结"；禁止 5 问漏答 |
| penalty_agent | 禁止"睁一只眼"；禁止合并多笔违规 |

---

## 文件大小一览

```bash
$ wc -l agents/*.md
data_collection_agent.md
emotional_agent.md
footprint_agent.md
news_agent.md
output_agent.md
penalty_agent.md
review_agent.md
risk_agent.md
scoring_agent.md
session_orchestrator.md
```

---

## 快速跑通指引

1. **检查 state 文件齐全**：6 个 JSON 文件应在 `state/` 下
2. **检查 inbox 当日目录**：`data_sources/inbox/<today>/` 应存在
3. **启动 session_orchestrator**：触发 `event="morning"`
4. **查看产出**：`outputs/<today>_*.md` + 桌面 `<today>_交易计划.txt`

更详细见顶层 `README.md`。
