---
name: stability-contract
description: 稳定性宪法·最高行为约束——禁飘逸/禁幻觉/禁违规，三道机械门把关，过不了不交付。
metadata:
  node_type: memory
  type: behavioral-contract
  priority: highest
  originSessionId: 455d12d8-37e5-491a-80a9-e19da8aa9eaf
---

# 🟥🟥🟥 稳定性宪法（最高行为约束·先于一切风格偏好）

2026-06-03 用户要求「深度优化稳定性·禁止飘逸·禁止幻觉·禁止违规」。根治手段=**机械门，不靠记忆/意志**。每次日报出稿走同一条确定性流水线，三道门全 PASS 才算完成、才回复用户。

## 一、禁飘逸（不自由发挥/不偏离模板与流程）
- 只做 SOP/模板/用户明确要求的事；**想偏离=先问，不擅自改格式/字段/流程**。
- 出稿严格按 **2026.6.2 冻结金标模板** 造（块类型/顺序/配色/配图位），不即兴换结构。
- **门 ①（防漂移）**：push 后必跑
  `py outputs/notion_verify_against_yesterday.py <今日id> morning|evening|review`
  → 对照 6/2 金标逐块比类型+颜色+图数+块数，**[PASS] 才算完成**。
- 🟥 **失败传播锁死（2026-06-27）**：门① PASS 必须同时满足“输出 `[PASS]` + 进程退出码0”；`[FAIL]`/异常必须退出非零，外层推送脚本必须传播并回滚 staging。曾发现 verifier 打印 FAIL 仍 exit0，导致外层可假报 `FROZEN GOLD VERIFY PASS`，已修复并以错误模式故障注入回归。
- 🟥 **事务式替换（2026-06-27）**：同名页必须“先建唯一 staging 新页→三图/落库/冻结门全过→再归档旧页→唯一存活检查”；禁先删旧后建新。准备失败回滚新页、旧页保留；清旧失败保留已验证新页并硬停，宁可重复不可全失。
- 每天最多重建页到 PASS，不带 `[FAIL]`/`MISMATCH` 交付（见 [[notion-publish-checklist]]）。

## 二、禁幻觉（数字/新闻/字段全部有据，不编不糊）
- **每个价格/百分比都必须是核过的确切数**：现价取最细图(15m/1H)确值、均价用防守层 R 反推、浮亏算到一位小数。禁 `71,2xx`/`XXXX`/独立 `~3%`/`xx刀`/占位（见 [[precise-numbers-no-fuzzy]]）。
- **新闻只用实时抓的 BlockBeats**，禁 AI 生成快讯；其余源截图/结构化读数不臆测。
- **发布前时效门（2026-07-05）**：任何 Notion 写入前动态算源文件年龄；Coinglass/Exocharts/TradingView 四档任一 >4h，报告不得作为可执行计划发布，必须重采六源、重评分、重出稿。BlockBeats/FedWatch/Farside 至少当日；Farside 表格最新行允许停留在最近一个美股交易日，但文件必须当日采集。禁止把历史快照晚推后继续当实时计划。
- **发布正文单源门（2026-07-05 根因修复）**：Daily Notion payload 必须由 `outputs/daily_payload_builder.py` 从 locked `combined.md` 与 source binding 机械派生；publish/deliver 证据必须包含 `notion_payload_source.status=passed` 且 `kind=combined_md_to_notion_payload`。任何手写 `children`、空块、补造 combined 不存在的 Maker/取消价/独立边界字段，或缺少 payload_source 的旧 payload，均不得发布或交付。
- 不确定就**显式标注"条目未记/未知"**，绝不用占位或编造填。
- **门 ②（防幻觉）**：push 前必跑
  `py outputs/report_lint.py outputs/{date}_morning_combined.md`
  → 抓模糊位/占位/臆造约数，**[PASS]（0 HARD）才能 push**；WARN 逐条人工确认是否核过。

## 三、禁违规（守宪法/守门禁/守独立成稿/守安全）
- **门禁硬前置**：关闭/主观不可交易→今日不写任何计划，只记观望+原因。
- **独立成稿**：判断字段(不能做/基本面/趋势/Maker方向)我从六源独立推，**禁参照用户手写判断**（见 [[independent-report-no-user-reference]]）；实际持仓/门禁/心力/TV手绘线可用作事实。
- **框架分流**：日内Maker=盘口>盘面>基本面；中线主账户=基本面>盘面>盘口。
- **台账即时订正**：发现旧条目错值→当场删除线+【❌已订正】，不只在新块补。
- **不 commit/不碰 git** 除非用户明确要求；token 只走 `$env:NOTION_TOKEN`，绝不硬编码进库。
- **门 ③（防违规）**：回复前自查清单——门禁已读？持仓已用 REST 校准(非沿用)？六源齐？评分门槛与挂单一致？字段对齐金标？数字 lint 过？三门皆 PASS？

## 出稿收尾固定口径
> 时效门→门② lint→staging 发布→落库门→门① verifier（输出+退出码）→归档旧页→唯一存活页→门③→写最终 context_log。全 PASS 才说"完成"；任一 FAIL 修复重跑，不交付半成品、不让日志停在中间态。

Word 产物另有视觉门：DOCX 必须经 LibreOffice 或 Word COM 实际导出并逐页看图；ZIP/XML 完整不等于视觉正确。2026-06-27 首次真实渲染抓到 `#`/`**`/POC 标题泄漏，已修通用 `render_from_combined.py` 并加回归测试。

见 [[notion-publish-checklist]] [[precise-numbers-no-fuzzy]] [[basemian-needs-news-cards]] [[report-template-alignment]] [[independent-report-no-user-reference]] [[daily-workflow-order]]。
