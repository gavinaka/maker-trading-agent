# 洁净样本规则（图谱二十节）

> 当前系统核心目标（2026.3 至今）：**完成 50 笔 100% 按系统执行的 Maker 交易**
> 进度截至 2026.4 末：22%（约 11 笔）。**动态真值见 Notion『系统50笔』库**（本文数字为历史快照、不保证实时）

---

## 核心定义

**洁净样本 = 100% 按系统执行的 Maker 交易**

---

## 判定条件（必须全部满足）

| # | 条件 | 数据来源 |
|---|---|---|
| 1 | `account == "maker"` | `check_records[].account` |
| 2 | `executed_by_plan == true` | `check_records[].executed_by_plan` |
| 3 | `emotional_action == false` | `check_records[].emotional_action` |
| 4 | 风控检核 7 项全 true | `check_records[].risk_checklist.*` |
| 5 | `plan_quality ∈ ["高", "中"]` | `check_records[].plan_quality` |
| 6 | `penalty_agent` 未标违规 | `governance/violations/<日期>_*.json` 无匹配 |

任一不满足 → 该笔交易**不计入洁净样本**。

---

## 计数规则

```
当前洁净累计 N = count(check_records WHERE 6 条件全 true)
进度百分比 = N / 50 × 100%
```

写入：`state/maker_state.json.clean_sample_system.current_progress_pct`

由 `review_agent` 在每次日复盘 + penalty_agent 判定后更新。

---

## 数据用途（图谱二十节）

完成 50 笔洁净样本后，用于评估：
1. **系统胜率基准**（统计学有效）
2. **系统盈亏比基准**
3. **执行一致性证据**
4. **是否进入下一阶段的判定依据**

---

## 进度里程碑

| 进度 | 笔数 | 状态 | 动作 |
|---|---:|---|---|
| 0-20% | 0-10 | 起步期 | 严格执行，禁止主观调整 |
| 20-40% | 10-20 | 积累期 | 每周复盘洁净率 |
| 40-60% | 20-30 | 中段 | 月报增加"洁净样本质量"段 |
| 60-80% | 30-40 | 冲刺期 | 严防最后阶段松懈 |
| 80-100% | 40-50 | 收官期 | 准备阶段性总结 |
| **100%** | **50** | **完成** | **触发阶段性大复盘 + 系统统计 + 进入下一阶段** |

---

## 违规对洁净样本的影响

* **轻度违规**：当笔不计入洁净样本，**但不污染历史样本**
* **中度违规**：同上 + 当周不允许"补样本"
* **重度违规**：同上 + **重启计数？**（待用户决定）
* **系统级违规**：必须用户介入，可能触发"洁净样本归零重来"

→ 详见 `agents/penalty_agent.md` 违规等级与处理。

---

## 与 review_agent 的协作

```
review_agent.run()
  ├─ 读今日 check_records（用户当日复盘录入）
  ├─ 对每笔 maker 交易：
  │    ├─ 判定 6 个洁净条件
  │    └─ 写 check_records[].clean_sample_eligible = true | false
  ├─ 触发 penalty_agent 审计
  │    └─ 违规笔 → eligible 强制 false
  └─ 重算 current_progress_pct，更新 state/maker_state.json
```

---

## 与 penalty_agent 的协作

```
penalty_agent.run()
  ├─ 扫今日 risk_decisions + check_records
  ├─ 模式匹配（V001-V014）
  ├─ 写 governance/violations/<today>_NNN.json
  ├─ 写 governance/violation_costs/<today>_NNN.json
  └─ 通知 review_agent：本日有违规，对应 check_records 不计入洁净样本
```

---

## 强制原则

* **违规交易不得计入样本**（图谱二十节核心规则）
* **样本完成后用于评估系统胜率/盈亏比基准**
* **不允许"补做"**（昨日漏判的洁净样本不可追溯添加）
* **不允许调整 6 个判定条件**（除非系统级迭代）

---

## 历史数据校准（图谱二十节）

* 2026.4 末：22%（11 笔）
* 进度由用户在 Notion 系统数据库"50 笔交易（洁净进度样本）"维护
* 本系统 review_agent 接管后从该值继续累加

---

## 数据库设计

`outputs/<YYYY-MM-DD>_check_records.json` 中每条 check_record 都含：
```json
{
  ...
  "clean_sample_eligible": true | false,
  "clean_sample_failure_reasons": ["..."]
}
```

`state/maker_state.json` 维护：
```json
"clean_sample_system": {
  "enabled": true,
  "target_clean_trades": 50,
  "current_progress_pct": 22,
  "current_clean_count": 11,
  "last_clean_trade_date": "YYYY-MM-DD",
  "count_violation_trade": false
}
```

→ `current_clean_count` 为本系统新增字段；与 Notion 同步时以本字段为准。
