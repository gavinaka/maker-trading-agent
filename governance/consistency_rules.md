# Consistency Governance Rules

## Core Principle
系统一致性高于单笔盈亏。
允许：
* 错过
* 等待
* 观望

不允许：
* 随机交易
* 情绪化交易
* 破坏系统规则

核心理念："错过不是错误，乱做才是。"

---

# Rule 01 — Score Threshold
只有满足以下条件才允许开仓：
* 总评分 ≥ 70
* 状态门禁通过
* 风控检核完成

否则强制观望。

---

# Rule 02 — Orderflow Priority
盘口优先级高于主观判断。
评分结构：
* 盘口评分：70%
* 盘面评分：30%

任何主观观点不得覆盖盘口信号。

---

# Rule 03 — Extreme Signal Execution
以下属于系统级信号：

## 看跌背离
条件：
* CVD上升
* 价格下降
* 持仓上升或横盘
* 资金费率为正

执行：→ 强制做空

## 看涨背离
条件：
* CVD下降
* 价格上升
* 持仓上升或横盘
* 资金费率为负

执行：→ 强制做多

---

# Rule 04 — 当天 Maker「不能做」映射（2026-05-31 订正：与主账户无关，互不干扰）
「不能做」= 当天 Maker 市场推导（盘口>盘面>基本面=禁追最拥挤一边），写完日报最后回填。
映射规则（Maker 内部）：
* 当天 Maker 不能做多 → 仅做空（高空/反弹空）
* 当天 Maker 不能做空 → 仅做多（低多）
* 当天 Maker 不能追多空 → 观望

❌ 旧框架"主账户方向限制约束 Maker"已废弃（误把两账户耦合）。

---

# Rule 05 — Stoploss Integrity
禁止：
* 临时移动止损
* 擅自扩大风险
* 情绪化补仓

允许：
* 根据浮盈防守系统移动止损
* 根据计划执行动态防守

---

# Rule 06 — Risk Limitation
单笔最大亏损 ≤ 3%
连续止损 ≥ 3 → 当日禁止交易

---

# Rule 07 — Clean Sample Priority
当前核心目标：完成50笔洁净样本。
规则：
* 必须100%系统执行
* 违规交易不得计入样本

---

# Rule 08 — Data Integrity
每日必须获取：
* Exocharts
* Coinglass
* BlockBeats
* CME FedWatch

任意数据缺失：
→ 标记待补充
→ AI禁止推测

---

# Rule 09 — News Rule
BlockBeats新闻：
* 必须截图
* 禁止文字替代
* 禁止AI生成

---

# Rule 10 — Trading Philosophy
系统目标：长期稳定执行，不是短期暴利。
系统一致性高于结果。
