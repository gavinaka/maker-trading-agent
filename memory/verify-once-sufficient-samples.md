---
name: verify-once-sufficient-samples
description: 锁模板/逻辑时样本不足就一次性随机抽2年内最多20个补足，一次锁死；禁止半验证上线后反复改skill浪费用户token。
metadata:
  node_type: memory
  type: feedback
  originSessionId: eb688ba7-9790-4a84-8300-1b7ffa6709e8
---

验证或锁定任何模板/格式/逻辑（对齐 Notion、校准判断口径等）时，**样本不足就在同一次里把样本抽够**：随机抽查 **2 年时间内最多 20 个** Notion 样本补充数据源，一次性核到 100% 把握再落地。

**Why（2026-06-01 用户明确·带情绪）**：用户原话"不要再浪费我的 token 去不断修改了，我不想做一个每天都在修复 skill 的用户"。半验证就上线 → 之后被用户发现偏差 → 反复回炉改 skill = 持续耗 token、耗用户耐心。

**How to apply**：
- 落地新规则/模板前先自问"样本够不够支撑 100% 把握"。不够 → **主动**随机抽到 20 个（跨最多 2 年），别等用户指出才补。
- 抽样要随机、跨时间分布（不要只抽最近几天）。
- 一次核全：字段名/顺序/含义/边界情况全覆盖，避免遗留"下次再修"。
- 宁可一次多花 token 抽样核全，也不要小步快跑反复 patch。
- 对齐 Notion 模板本身是宪法级第一优先，见 [[report-template-alignment]]。

关联 [[report-template-alignment]]、[[score70-must-place-maker]]。
