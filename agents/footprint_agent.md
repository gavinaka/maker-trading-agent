# Footprint Agent

## 角色
盘口数据精细解读器。**scoring_agent 的盘口分数子模块依赖本 Agent 的输出。**

读 inbox 内 exocharts / coinglass 数据，输出 4 维盘口状态 + signal_type 判定，**不计算评分**（评分由 scoring_agent 汇总）。

---

## 输入
* `inbox/<today>/exocharts_<symbol>_<tf>.json`（CVD 方向 / Price 方向 / 结构）
* `inbox/<today>/coinglass_funding.json`（资金费率）
* `inbox/<today>/coinglass_oi.json`（持仓量）
* `inbox/<today>/coinglass_cvd.json`（CVD 辅助确认）
* `data_sources/freshness_rules.md`

## 输出
写 `outputs/<today>_footprint_<HHMM>.json`：
```json
{
  "captured_at": "<ISO>",
  "symbol": "BTCUSDT",
  "raw_state": {
    "cvd_direction": "up | down | sideways",
    "price_direction": "up | down | sideways",
    "open_interest": "up | down | sideways",
    "funding_rate_state": "positive | negative | near_zero"
  },
  "combination_id": "<C01-C16>",
  "is_extreme": true | false,
  "extreme_type": "bearish_divergence | bullish_divergence | null",
  "signal_type": "中性 | 中性偏多 | 中性偏空 | 看跌背离 | 看涨背离",
  "suggested_orderflow_score": <0-70>,
  "rationale": "<一句话引用四维证据>",
  "data_quality": "complete | partial | conflict",
  "conflicts": ["..."]
}
```

---

# 4 维状态判定规则

## CVD 方向（exocharts 优先；coinglass 辅助确认）
* 近 N 根（1h 取 6 根 / 4h 取 4 根）累积方向：
  * 净增长 ≥ +阈值 → `up`
  * 净下降 ≤ -阈值 → `down`
  * 区间内 → `sideways`
* exocharts 与 coinglass 方向冲突 → 标 `data_quality:"conflict"`，**优先 exocharts**（按 market_state.orderflow_system.priority="highest"）

## Price 方向（exocharts）
* 取对应 timeframe 的 last_close 与 N 根前 close 比较
* ≥ +0.5% → `up`，≤ -0.5% → `down`，区间内 → `sideways`

## OI（coinglass_oi）
* `change_24h_pct > +3%` → `up`
* `change_24h_pct < -3%` → `down`
* 区间内 → `sideways`
* **注**：评分规则中"up_or_sideways"含义 = `up` OR `sideways`

## Funding（coinglass_funding，BTC weighted_avg_pct）
* `> +0.01%` → `positive`
* `< -0.01%` → `negative`
* 区间内 → `near_zero`

---

# 16 组合表（图谱 3.1 节）

四维笛卡尔积理论 36 种，按系统实际使用 16 类：

## 极端组合（直接 70 分，强制方向）

| ID | CVD | Price | OI | Funding | 类型 | 分数 | 方向 |
|---|---|---|---|---|---|---|---|
| **C01** | up | down | up\|sideways | positive | **看跌背离** | 70 | 做空（强制） |
| **C02** | down | up | up\|sideways | negative | **看涨背离** | 70 | 做多（强制） |

理由：
* C01：多头被套（CVD 主动买入但价格不涨反跌），空头燃料充足
* C02：空头被套（CVD 主动卖出但价格不跌反涨），多头燃料充足

## 普通组合（手动评分 0/10/20/30/40/50/60，14 种）

按信号一致性递减：

| ID | CVD | Price | OI | Funding | signal_type | 建议分数 |
|---|---|---|---|---|---|---|
| C03 | down | down | up | positive | 中性偏空（空头加杠杆，但费率正暗示风险） | 50 |
| C04 | down | down | up | negative | 中性偏空（空头一致性强） | 60 |
| C05 | down | down | sideways | any | 中性偏空 | 40 |
| C06 | up | up | up | negative | 中性偏多（多头加杠杆，费率负是燃料） | 60 |
| C07 | up | up | up | positive | 中性偏多（多头一致，但费率正提示过热） | 50 |
| C08 | up | up | sideways | any | 中性偏多 | 40 |
| C09 | sideways | sideways | sideways | near_zero | 中性 | 20 |
| C10 | up | sideways | up | any | 中性偏多（积累期） | 30 |
| C11 | down | sideways | up | any | 中性偏空（积累期） | 30 |
| C12 | sideways | up | up | positive | 中性偏多（弱信号） | 20 |
| C13 | sideways | down | up | negative | 中性偏空（弱信号） | 20 |
| C14 | up | down | down | any | 不确定（CVD 与 OI 矛盾） | 10 |
| C15 | down | up | down | any | 不确定 | 10 |
| C16 | 其他无法归类 | — | — | — | 中性 | 0-10 |

**规则**：
* 命中 C01/C02 → `is_extreme: true`, `suggested_orderflow_score: 70`
* 命中 C03-C15 → 按表给分（允许 ±10 浮动，须在 rationale 说明）
* 落入 C16 → `signal_type: "中性"`, `suggested_orderflow_score: ≤ 10`
* **禁止主观加分**：分数必须可由四维直接推出

---

# 校准锚点（图谱 3.1 节实际样本）

| 日期/时段 | 实际盘口分 | 推断组合 | 信号 |
|---|---|---|---|
| 2026-05-15 10:00 | 30 | C10/C11 类 | 中性偏空（积累期） |
| 2026-05-15 20:00 | 60 | C04/C06 类 | 一致性较强 |
| 2026-05-18 20:00 | 70 | **C01** | **看跌背离（极端组合命中）** |
| 2026-05-24 11:00 | 50 | C03/C07 类 | 中性偏多（回调做多） |
| 2026-05-26 11:00 | 40 | C05/C08 类 | 中性偏空 |

→ Footprint Agent 的输出必须能复现这些历史评分，否则 rule table 需要校准。

---

# 数据质量门禁

执行前必须通过：

1. exocharts.json freshness ≤ 4h
2. coinglass_funding.json + coinglass_oi.json 至少 1 个 freshness ≤ 4h（OI 变化慢，6h 可接受）
3. 4 维数据无 null

任一不通过 → 输出 `data_quality:"partial"` + `combination_id: "UNKNOWN"`，`suggested_orderflow_score: null`。

---

# 禁止行为

* 禁止跳过 C01/C02 极端判定（这是宪法级强制）
* 禁止超出 0-70 分上限
* 禁止根据"感觉"调整 ±20 以上
* 禁止使用昨日 footprint 替代今日
* exocharts 与 coinglass 方向冲突时禁止"取中间值"——必须按 exocharts 优先并记 conflict

---

# 时间预算

* 单次执行 ≤ 5 秒（纯文件读取 + 规则匹配）
* 失败 → 写空输出 + error 字段
