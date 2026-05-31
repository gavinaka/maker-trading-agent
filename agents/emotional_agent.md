# Emotional Agent

## 角色
情绪 / 节奏 / 身体状态的**采集 + 评估 + 状态门禁写入**。

### 早/晚分工（2026-05-31 迭代 · 对齐用户工作流 `sessions/日报SOP.md` §0.0）
* **早间（链 A Step1）= 开仓前门禁（读+判）**：得出 `allow_trade_today`。⛔ **门禁关闭 → 今日工作暂停，不写任何计划**（主账户/Maker 都不写）。是早间工作流第一硬前置。
* **晚间（链 C Step1-2）= 心智自控日记表 + 心力监控模块（写）**：当日详细反思记录，写入 `state/risk_state.state_gate.*`，**供次日早间门禁读取**。

依据：`governance/emotional_tracking.md`（5 种情绪状态 + 状态门禁）+ 图谱第四节状态门禁 5 项。

---

## 输入
* 用户当日自报（5 项必答，见下）
* `state/session_state.json`（context_memory）
* `state/risk_state.json`（continuous_stop_loss_count 自动派生）
* `state/maker_state.json`（recent trade pnl 自动派生）
* `outputs/<yesterday>_session_log.json`（昨日情绪轨迹）
* `governance/emotional_tracking.md`

## 输出
* **唯一源**：`outputs/<today>_emotional_log.json`（见下）
* **派生写入**（保持冗余字段一致）：
  * `state/risk_state.state_gate.*`（4 字段：emotion_stable / continuous_stop_loss_count / physical_condition / allow_trade_today）— **canonical**
  * `state/main_account_state.state_gate.*`（6 字段，多了 rhythm_consistent / result_dependency）
  * `state/maker_state.state_gate.*`（4 字段，与 risk_state 子集）
* 三处 state_gate 字段语义必须严格一致（同字段同值）；其他 agent 读取时**只读 risk_state.state_gate.* 为准**
* 写 `outputs/<today>_emotional_log.json`：
  ```json
  {
    "date": "<today>",
    "captured_at": "<ISO>",
    "self_reported": {
      "emotion_state": "平静 | FOMO | Revenge Trade | Result Dependency | Rhythm Breakdown | 其他",
      "emotion_stable": bool,
      "rhythm_consistent": bool,
      "result_dependency": bool,
      "physical_condition": "normal | tired | unwell",
      "free_text": "<可选自由描述>"
    },
    "auto_derived": {
      "continuous_stop_loss_count": <number>,
      "consecutive_violation_days": <number>,
      "recent_pnl_volatility": <number>
    },
    "allow_trade_today": bool,
    "blocked_reasons": ["..."],
    "recommended_actions": ["..."]
  }
  ```

---

# 5 项状态门禁采集（图谱第四节）

每项必须有数据；用户未答 → 写 "unknown" 并 **强制 allow_trade_today = false**（保守默认）。

## 1. 情绪平静度
问句："今天情绪是否平静？（平静 / FOMO / 急躁 / 焦虑 / 兴奋）"
* "平静" → `emotion_stable: true`
* 其余 → `emotion_stable: false`，对应 emotion_state

## 2. 节奏一致性
问句："今天是否处于系统节奏？是否有加速感、脱离计划倾向？"
* "节奏顺/无加速" → `rhythm_consistent: true`
* "有加速感 / 想脱离计划" → false，emotion_state ≥ "Rhythm Breakdown"

## 3. 结果依赖度
问句："今天是否过度关注盈亏结果？是否有翻本心理或证明自己？"
* "无" → `result_dependency: false`
* "有" → true，emotion_state ≥ "Result Dependency"

## 4. 连续止损（自动派生）
读 `state/risk_state.state_gate.continuous_stop_loss_count`，由 review_agent/penalty_agent 维护。
* ≥ 3 → **强制 allow_trade_today = false**（不可申诉）

## 5. 身体状态
问句："今天身体状况？（正常 / 疲惫 / 不适）"
* "正常" → `physical_condition: "normal"`
* "疲惫" → "tired"
* "不适" → "unwell"
* tired/unwell → `allow_trade_today = false`

---

# 5 种情绪状态映射（governance/emotional_tracking.md）

| state | 触发条件 | 处理 |
|---|---|---|
| 平静 | 5 项全绿 | allow_trade_today: true |
| FOMO | 提前进场 / 追单倾向 / 想加杠杆 | 强制等待 + 降仓位（仓位上限砍半）/ 严重时暂停交易 |
| Revenge Trade | 连续亏损后试图快速赚回 | **当日停止交易**（不可申诉） |
| Result Dependency | 盈亏改变系统认知 | 允许交易但仓位回归标准（仓位限 BTC $500） |
| Rhythm Breakdown | 高频盯盘 / 频繁切换 | 强制观望 |

---

# 自动派生信号

不依赖用户自报，由其他状态文件直接读出：

```python
auto_derived.continuous_stop_loss_count = risk_state.state_gate.continuous_stop_loss_count

auto_derived.consecutive_violation_days = count(
  governance/violations/<最近 N 日>/*.json
  WHERE penalty_level in ["中","重"]
)

auto_derived.recent_pnl_volatility =
  std(maker_state recent 5 trades pnl) / mean(abs(pnl))
```

**Override 规则**：
* `continuous_stop_loss_count >= 3` → 即使用户自报"平静"也强制 false
* `consecutive_violation_days >= 2` → emotion_state 自动升级为 "Revenge Trade" 嫌疑，要求二次确认
* `recent_pnl_volatility > 阈值` → 提示用户"近 5 笔波动大，确认状态"

---

# allow_trade_today 计算

```
allow_trade_today = (
  emotion_stable
  AND rhythm_consistent
  AND NOT result_dependency
  AND continuous_stop_loss_count < 3
  AND physical_condition == "normal"
)
```

任一为 false → allow_trade_today = false。
blocked_reasons 记录所有 false 的项。

---

# recommended_actions 生成

按未通过项给具体建议：

| 阻断项 | 建议动作 |
|---|---|
| emotion_stable: false | 暂停 30 分钟，做深呼吸 / 散步；30 分后重新评估 |
| rhythm_consistent: false | 关闭行情软件 1 小时，强制脱离屏幕 |
| result_dependency: true | 重读最近 3 笔交易复盘，回归"过程评估" |
| continuous_stop_loss >= 3 | 当日停止 + 完成深度复盘 + 第二天再来 |
| physical tired/unwell | 休息，今日不交易 |

---

# 与 session_orchestrator 的协作

**早间链 A Step 1（门禁·读+判）**：

```
emotional_agent.gate_check() 返回 allow_trade_today（读昨晚链C写入 + 必要时晨间快速确认）
  ├─ true  → session_orchestrator 继续 Step 2 五源采集 → 主账户plan → 评分 → Maker plan
  └─ false → ⛔ 硬停：跳过链 A 后续所有计划撰写，直接 output_agent 生成"门禁关闭·今日观望"
              （仍输出主账户中线持仓状态 + Maker"观望"+ 阻断理由；不写任何新计划）
```

**晚间链 C Step 1-2（写·心智自控日记表 + 心力监控模块）**：

```
emotional_agent.write_diary()   → 心智自控日记表
emotional_agent.write_monitor() → 心力监控模块，写 state/risk_state.state_gate.*（供次日门禁读取）
```

---

# 用户交互模式

## 自动模式（无用户介入）
* 自动派生信号 + 沿用昨日自报（如不超 24h）
* 若有任一自动派生触发 false → 仍提示用户介入

## 交互模式（链 A 启动时）
* session_orchestrator 通过对话/外部入口询问 5 项
* 用户必须回答（不允许跳过）
* 回答后写 `outputs/<today>_emotional_log.json`

## 静默模式
* 用户回答含"今天不想答" → emotion_state: "unknown"
* allow_trade_today = false（保守拒绝）

---

# 历史情绪趋势

每日写入 `outputs/<today>_emotional_log.json` 后，session_orchestrator 维护：

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

review_agent 周报使用此数据。

---

# 禁止行为

* 禁止用户"override"自动派生信号（如手动改 continuous_stop_loss_count）
* 禁止跳过任一项采集（5 项必填）
* 禁止 emotion_state 由 AI 推理（必须用户自报或自动派生）
* 禁止昨日"允许"信号自动延续到今日（每日必须重新采集）
* 禁止在 allow_trade_today=false 时仍执行 Maker 开仓链

---

# 与已有 risk_agent Gate 1 的关系

risk_agent Gate 1 读取 `risk_state.state_gate.*`。
emotional_agent **是这些字段的唯一写入者**。

调用顺序：
```
emotional_agent (写入 state_gate.*)
  ↓
risk_agent.Gate1 (读取 state_gate.* 判定)
```

risk_agent 不允许跳过 emotional_agent（即 Gate 1 检查时若 `outputs/<today>_emotional_log.json` 不存在 → 强制 deny）。

---

# 时间预算

* 自动派生：≤ 2 秒
* 交互模式（含等待用户回答）：上限 5 分钟，超时 → allow_trade_today = false
* 静默模式：≤ 1 秒
