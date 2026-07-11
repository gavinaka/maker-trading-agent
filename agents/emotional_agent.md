# Emotional Agent

## 角色
当天 `开仓前状态门禁` 的**只读校验 + 本地状态镜像**，以及晚间心智／心力 review 的独立记录。

### 早/晚分工（2026-05-31 迭代 · 对齐用户工作流 `sessions/日报SOP.md` §0.0）
* **早间（链 A Step1）= 开仓前状态门禁（只读+校验）**：读取当天 Notion 门禁行及其`主观结论`，得出 `allow_trade_today`。⛔ **门禁关闭 → 今日工作暂停，不写任何计划**（主账户/Maker 都不写）。这是当天唯一的事前硬门禁。
* **晚间（链 C Step1-2）= 心智自控日记表 + 心力监控模块（写）**：只记录当天结束后的详细反思，**不得写入、推导或覆盖任何 `state_gate.*` 字段，也不供次日门禁自动读取**。

依据：`risk/state_gate.md`（开仓前状态门禁 5 项）+ `sessions/日报SOP.md`（唯一准入与晚间 review 边界）。

---

## 输入
* Notion 当天 `开仓前状态门禁` 行（日期、5 项状态、`主观结论`、备注）
* `risk/state_gate.md`
* `sessions/日报SOP.md`

晚间 review 可另读用户当日复盘输入，但这些输入与早间门禁数据流严格隔离。

## 输出
* **唯一准入源**：Notion 当天 `开仓前状态门禁` 行。
* **只读镜像**：允许把同一门禁行机械镜像到 `state/risk_state.state_gate.*`、`state/main_account_state.state_gate.*`、`state/maker_state.state_gate.*`；镜像不得增加、推断或修改门禁结论。
* 三处 `state_gate` 必须记录相同日期、相同来源和相同结论；晚间 review 无权写这些字段。
* 可写 `outputs/<today>_emotional_log.json` 作为门禁读取快照：
  ```json
  {
    "date": "<today>",
    "captured_at": "<ISO>",
    "pretrade_gate": {
      "emotion_state": "平静 | FOMO | Revenge Trade | Result Dependency | Rhythm Breakdown | 其他",
      "emotion_stable": bool,
      "rhythm_consistent": bool,
      "result_dependency": bool,
      "physical_condition": "normal | tired | unwell",
      "free_text": "<可选自由描述>"
    },
    "subjective_conclusion": "可交易 | 不可交易",
    "allow_trade_today": bool,
    "blocked_reasons": ["..."],
    "recommended_actions": ["..."]
  }
  ```

---

# 5 项开仓前状态门禁读取（图谱第四节）

每项必须来自当天 Notion 门禁行。字段缺失、日期不符或字段与`主观结论`冲突时硬停人工确认；禁止由 AI、昨日记录、心智自控或心力监控补全。

## 1. 情绪平静度
Notion 字段：`情绪平静度`
* "平静" → `emotion_stable: true`
* 其余 → `emotion_stable: false`，对应 emotion_state

## 2. 节奏一致性
Notion 字段：`节奏一致性`
* "节奏顺/无加速" → `rhythm_consistent: true`
* "有加速感 / 想脱离计划" → false，emotion_state ≥ "Rhythm Breakdown"

## 3. 结果依赖度
Notion 字段：`结果依赖度`
* "无" → `result_dependency: false`
* "有" → true，emotion_state ≥ "Result Dependency"

## 4. 连续止损
读取 Notion 门禁行的`连续止损数（≥3）`；本地 state 只保存镜像，不从晚间 review 反向生成当天准入。
* ≥ 3 → **强制 allow_trade_today = false**（不可申诉）

## 5. 身体状态
Notion 字段：`身体状态`
* "正常" → `physical_condition: "normal"`
* "疲惫" → "tired"
* "不适" → "unwell"
* tired/unwell → `allow_trade_today = false`

---

# 5 种情绪状态映射（governance/emotional_tracking.md）

| state | 触发条件 | 处理 |
|---|---|---|
| 平静 | 5 项全绿 | allow_trade_today: true |
| FOMO | 提前进场 / 追单倾向 / 想加杠杆 | **当日停止交易** |
| Revenge Trade | 连续亏损后试图快速赚回 | **当日停止交易**（不可申诉） |
| Result Dependency | 盈亏改变系统认知 | **当日停止交易** |
| Rhythm Breakdown | 高频盯盘 / 频繁切换 | **当日停止交易** |

---

# allow_trade_today 读取与一致性校验

```
allow_trade_today = (subjective_conclusion == "可交易")
```

5 项字段用于校验`主观结论`和记录原因，不再形成第二套门禁。任一字段触发但结论仍为“可交易”时，不得自行改写结论；应硬停人工确认。

---

# recommended_actions 生成

按未通过项给具体建议：

| 阻断项 | 建议动作 |
|---|---|
| emotion_stable: false | 当日停止交易，离开行情并休息 |
| rhythm_consistent: false | 当日停止交易，强制脱离屏幕 |
| result_dependency: true | 重读最近 3 笔交易复盘，回归"过程评估" |
| continuous_stop_loss >= 3 | 当日停止 + 完成深度复盘 + 第二天再来 |
| physical tired/unwell | 休息，今日不交易 |

---

# 与 session_orchestrator 的协作

**早间链 A Step 1（门禁·读+判）**：

```
emotional_agent.gate_check() 返回 allow_trade_today（只读当天 Notion 开仓前状态门禁）
  ├─ true  → session_orchestrator 继续 Step 2 五源采集 → 主账户plan → 评分 → Maker plan
  └─ false → ⛔ 硬停：跳过链 A 后续所有计划撰写，直接 output_agent 生成"门禁关闭·今日观望"
              （仍输出主账户中线持仓状态 + Maker"观望"+ 阻断理由；不写任何新计划）
```

**晚间链 C Step 1-2（写·心智自控日记表 + 心力监控模块）**：

```
emotional_agent.write_diary()   → 心智自控日记表
emotional_agent.write_monitor() → 心力监控模块（仅写晚间 review，不触碰 state_gate）
```

---

# 用户交互模式

## 自动模式（链 A 启动时）
* 读取当天 Notion 门禁行并校验日期、字段完整性和`主观结论`一致性。
* 不询问心智／心力 review，也不沿用昨日任何准入结论。

## 门禁不可用
* 当天行缺失、读取失败或内容矛盾 → 硬停人工确认。
* 禁止拿昨日门禁、晚间 review 或 AI 推断替代。

---

# 历史情绪趋势

晚间 review 可维护独立的历史情绪趋势，但该数据只供复盘分析：

`state/emotional_trend.json`（新增文件）：
```json
{
  "last_7_days": [
    { "date": "...", "emotion_state": "...", "allow_trade": bool },
    ...
  ],
  "consecutive_block_days": <number>,
  "dominant_emotion_last_7": "..."
}
```

review_agent 周报可使用此数据；日报与开仓准入不得读取它。

---

# 禁止行为

* 禁止 agent 修改 Notion 门禁结论或用其它信号覆盖门禁镜像
* 禁止跳过任一门禁字段读取（5 项 + `主观结论`必填）
* 禁止 emotion_state 由 AI 推理（必须来自当天 Notion 门禁行）
* 禁止昨日"允许"信号自动延续到今日（每日必须读取当天门禁）
* 禁止晚间心智／心力 review 写入、推导或覆盖 `state_gate.*`
* 禁止把 review 缺失当作日报或交易的阻断条件
* 禁止在 allow_trade_today=false 时仍执行 Maker 开仓链

---

# 与已有 risk_agent Gate 1 的关系

risk_agent Gate 1 可读取 `risk_state.state_gate.*`，但该对象只能是当天 Notion 开仓前状态门禁的机械镜像。
emotional_agent 只负责读取和镜像门禁；晚间 review 写入路径与 `state_gate.*` 隔离。

调用顺序：
```
emotional_agent (读取当天 Notion 门禁并机械镜像 state_gate.*)
  ↓
risk_agent.Gate1 (读取 state_gate.* 判定)
```

risk_agent 不允许跳过当天门禁校验；当日门禁快照不存在或来源/日期不符 → 强制 deny 并要求人工确认。

---

# 时间预算

* 门禁读取与一致性校验：≤ 2 秒
* 需要人工确认时：立即硬停，不设置自动放行或自动否决超时值
