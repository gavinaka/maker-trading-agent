# 数据时效规则

## 核心原则

数据有"保鲜期"。

* 过期数据等同于缺失数据
* 禁止使用过期数据做开仓决策
* 时效失败 → 强制重采集

---

# 评分数据（盘口 + 盘面）

来源：盘口(70)=Coinglass（核心）/ Exocharts（印证）；盘面(30)=TradingView（日/4H/1H/15m 四档·核心）
> 🟥 2026-06-14 订正：盘面源为 TradingView（旧文漏列）；四档缺一=五源未齐=硬停。

| 采集时间 | 状态 | 允许动作 |
|---|---|---|
| ≤ 4 小时 | 新鲜 | 可用于开仓决策 |
| 4 - 6 小时 | 警告 | 仅允许观望/防守，不允许新开仓 |
| > 6 小时 | 过期 | 强制重采集；`score_state.current_score` 当前值失效 |

---

# 新闻数据

来源：BlockBeats

* 当日（自然日）采集才有效
* 跨日 → 失效，必须重采

---

# 宏观数据

来源：CME FedWatch

* 当日采集即可
* 变化频率低
* 重大美联储事件日（FOMC / SEP 发布）必须当日重采

---

# 强制规则

## Phase 02 评分前置检查

`workflow.md` Phase 02 评分前，必须：

1. 读 `data_sources/inbox/<today>/_manifest.json`
2. 检查每源 `freshness_minutes` 字段
3. 任一源不满足时效 → 触发 `data_collection_agent` 重采集
4. 重采集失败 ≥ 3 次 → 锁定 `session_state.tasks.*`，等待用户介入

---

## 主账户日报 / Maker 计划生成前置

`output_agent` 生成报告前必须：

1. 读 manifest
2. 任一源失效 → 报告对应字段直接标 "待补充（数据过期）"
3. 禁止用 `score_state.historical_reference` 中的历史评分替代

---

# 时间基准

* 所有时间戳使用 ISO 8601 + 时区（+08:00）
* `captured_at`：采集完成时刻（写入 inbox 时）
* `freshness_minutes`：当前时刻 - `captured_at`，由读取方动态计算
* 禁止在 manifest 中预先写入 `freshness_minutes`（避免错误缓存）

---

# 异常处理

数据源在时效内但内容异常（空值/解析失败）：

* 视同失效
* 标记 `valid: false`
* 触发重采集
