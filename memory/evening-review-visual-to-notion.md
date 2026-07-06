---
name: evening-review-visual-to-notion
description: "晚间日报收工时必产出一份\"Notion 原生块独立审查报告\"(去系统逻辑·倒推)，并推进 Notion 当日日期页(与早/晚间日报同目录)。"
metadata:
  node_type: memory
  type: project
  originSessionId: aa7a5b16-01bf-4455-bb21-5d5c34ca0d59
---

用户 2026-06-02 拍板的长期工作流规则（晚间日报专属收尾步）：

**每次生成晚间日报后、收工的同时，必须额外产出一份《Notion 原生块独立审查报告》，并记入 Notion 当日日期页（与早/晚间日报同一子目录内）。**

## 审查报告要求
- **去除系统逻辑**：不引用用户的 70+30 评分 / ≥65必挂 / footprint 16组合等系统框架，纯用独立交易第一性原理评判。
- 🟥🟥 **倒推范围＝三段·缺一即口径违规（2026-06-20 随午报新增节点·由双段扩为三段；原双段锁死缘由见 2026-06-12）**：~~用早间→晚间的实际走势检验早间判断~~【❌已订正·旧口径只检当天早间，6/8 起前一晚间报告整套判断连续数日漏检·用户定性"重大问题"】→ ~~段一＝前晚报＋段二＝今早报（双段）~~【⬆️2026-06-20 扩为三段】→ **段一＝前一天晚报**（隔夜→今日走势检验）＋**段二＝当天早报**（早→午走势检验）＋**段三＝当天午报**（午→晚走势检验）；缺某节点稿时按实际存在的相邻报告顺次降为单/双段（午报缺退回双段·6/10 单段先例同理）。评分表/价格阶梯/关键发现三段都须覆盖。
- **产物边界（2026-07-06 订正）**：独立审查只产 Notion 原生块 payload/page，不再生成本地 HTML 仪表盘或截图；HTML 属历史遗留产物，后续不得作为必交付或中间步骤，避免 token 与视觉 QA 浪费。
- **维度**：方向判断 / 入场结构 / 风险框架 / 数据精度 / 内在一致性（各 0-100 + 综合等级），**三段（前晚报＋当天早报＋当天午报）分别打分**。

## 记入 Notion
- 位置：当日日期页 `2026.M.D`（与 🌅早报 / 🌇午报 / 🌙晚报 子页同级），新增子页 **`🔍 2026.M.D 晚间独立审查（倒推）`**。
- 内容用 Notion 原生块呈现：综合评分用 table、价格阶梯/倒推结论用 table、核心矛盾用 callout、关键发现用 paragraph；不得上传 HTML 截图。
- 🟥 **review contract 硬门（2026-07-06 根因修复）**：先写 `runtime_state/<date>/evening_independent_review.json`（`evening-independent-review-v2`），再用 `py outputs/review_payload_builder.py runtime_state/<date>/evening_independent_review.json` 生成 payload；发布前必须通过 `outputs/review_contract.py`，首个评分表固定为 `维度 / 前一晚报 / 当天早报 / 当天午报 / 综合`，行固定为 `方向判断 / 入场结构 / 风险框架 / 数据精度 / 内在一致性 / 综合`；`review-font-rendering-v1` 必须校验 `rich_text.annotations.color/bold`：评分表分数、价格阶梯三段标签/审查意见、六条发现、边界与结论均不得是默认无样式文本；`payload_source` 必须绑定 manifest、report hash 与 children signature。review 发布不得要求或验证日报 `source_specs`、不得触发日报 freshness/lint/source-binding 门、不得改动早/午/晚任何报告产物。`outputs/notion_verify_against_yesterday.py <page_id> review` 必须实际校验表格单元格、可见文本与字体颜色，禁止 `analysis_lock`、`combined`、`commit`、`payload`、`verifier`、`finalize-post-lock`、`Word-QA`、`context_log`、`锁后`、`回写`、`硬门` 等系统/执行流水线词出现在用户可见审查页。
- 仍守 push 硬规则：只写「AI agent（plan）」项目，建前 GET 日期页 children 防同名重复（见 [[push-report-to-ai-agent-plan]]）。

## 触发与归属
- 仅**晚报链 B 收工**触发（早报/午报不单独出审查；早报、午报均会在当晚的审查里被一并倒推评判，三段覆盖）。
- 属 daily-report skill §6 收尾固定步，已写入 SKILL.md。
- 禁止为独立审查额外生成 HTML、PNG 截图或 Word/PDF 视觉 QA 产物；Notion 原生块与冻结 verifier PASS 即为交付形态。
