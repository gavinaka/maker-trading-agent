# 日复盘结构定义（图谱十七节）

> 本文件定义日复盘的**结构规范**（不是模板渲染本身）。
> 模板渲染见 `templates/review_daily.md`。
> Schema 见 `schemas/review_schema.json` → `daily_review`。
> Agent 见 `agents/review_agent.md`。

---

## 核心原则（图谱十七节）

1. **每日 23:00 前完成**
2. **每日必填**——即使未开单也要填
3. **强调过程质量评估**——不依赖结果
4. **追踪左右侧入场风格的演变**
5. **记录情绪状态与生活影响**

---

## 5 个核心问题（图谱十七节）

| # | 问题 | 关键产出 |
|---|---|---|
| 1 | 执行日内交易：计划完成度 | 完成度 % + 早晚计划对照 |
| 2 | 交易循环完成情况 | 已开单/未开单/笔数 + 笔详情 |
| 3 | 左侧交易向右侧交易权重偏移 | 左/右计数 + 7 日趋势 |
| 4 | 心力控制 | 工作生活影响（1-5）+ 情绪事件 |
| 5 | 中线之扁 | 中线持仓状态总结 |

加：**总结**（当日核心体会，1-3 句，禁止 AI 生成）

---

## 与其他模块的关系

```
日复盘
  ├─ 由 review_agent 触发（链 C 第 1 步）
  ├─ 读 outputs/<today>_*.txt + check_records + emotional_log
  ├─ 写 reviews/<YYYY-MM-DD>.md
  └─ 触发 penalty_agent（链 C 第 2 步）
        ├─ 扫描违规
        └─ 更新洁净样本计数
```

---

## 数据依赖

| 问题 | 主要数据来源 |
|---|---|
| Q1 计划完成度 | `outputs/<today>_maker_morning.md` + `_maker_evening.md` |
| Q2 交易循环 | `outputs/<today>_check_records.json` |
| Q3 左右侧 | check_records[].entry_type 计数 + 历史 6 日 reviews |
| Q4 心力 | `outputs/<today>_emotional_log.json` |
| Q5 中线 | `state/main_account_state.json.position_status` + `mid_term_structure` |
| 总结 | 用户输入 |

---

## 写作要求

* **数字必须精确**——浮盈浮亏要有具体数值
* **禁止口号化**——禁止"继续努力"/"加油"等空话
* **必须基于今日具体事件**——禁止抽象结论
* **未开单也必须 5 项全填**——状态门禁触发数、心力评估等
* **连续观望 ≥ 5 天**——总结段必须分析原因
* **状态门禁触发 ≥ 1 次**——必须在备注解释

---

## 历史轨迹

review_agent 维护：
* `reviews/<YYYY-MM-DD>.md` 单日
* 周日时 review_agent 聚合本周 7 日 → `reviews/<YYYY-Www>_weekly.md`
* 月末时 review_agent 聚合本月所有日 → `reviews/<YYYY-MM>_monthly.md`

---

## 演化历史（图谱十九节相关）

| 时期 | 格式特点 |
|---|---|
| 2025.6-9 早期 | ChatGPT 生成分析报告 + 个人 5-6 条经验教训；五维度评分表 |
| 2025.10-12 中期 | 简化为"四个核心问题"格式；完全个人书写；引入"第二/三关"心理关卡命名 |
| **2026.1-至今 标准化** | **五个核心问题**（图谱十七节）；标准词汇库；与 check_records 数据库联动 |
