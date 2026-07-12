---
name: notion-publish-checklist
description: Notion 日报出稿宪法级机械化自检门——push 后必跑 verifier（结构门+语义配色门），禁靠记忆逐项核。
metadata:
  node_type: memory
  type: process-gate
  originSessionId: 455d12d8-37e5-491a-80a9-e19da8aa9eaf
---

# Notion 出稿稳定性门（机械化·不靠记忆）

**Why**：2026-06-03 用户连续纠错（漏配图→漏块类型→漏字体颜色），原因是「反应式补丁」。要求**深度修稳定性**：用脚本机械比对，过不了就不算完成。

> 🟥 **活跃结构金标=`daily-publish-payload-v4`**：手工报告内联标签 + 自然交易结论 + 三图固定位置；前台禁止系统摘要、callout、divider、泛化 Maker 标题和审计元叙事，完整推理保留在后附/Word/运行证据。旧 `v2/v3` 只用于历史页面兼容复验。review 分支仅供历史页面兼容复验，不得创建新页面。
> 🟥🟥 **配色权威 ≠ 金标颜色**（2026-06-03 用户拍板·关键修正）。金标自身配色不一致（同一个「中性偏空」早间金标涂红、晚间金标涂橙），**绑死金标颜色会把语义涂错**（典型：解读结论「中性偏空」被机械对成红＝看着像利空＝"渲染不到位"）。改为：**配色按【情绪词→颜色】确定性唯一规则**，早晚统一一套，由 `outputs/report_colors.py` 逐 run 校验。

## 唯一色规则（用户书面约定·长期标准·见 report_colors.py；**2026-06-12 用户迭代：中性偏多→绿、中性偏空→红、其余不变**）
- **红 red**：利空 / 空头趋势 / **中性偏空（2026-06-12 起）** / 日内压力(值) / 止损 / 不能做「（追）做X」/ Maker 空头方向(反弹空·高空·做空)
- **黄 yellow**：中性 / 震荡结构 / 基本面理由段 / 策略正文 / 解读标签(纯中性)
- **绿 green**：利多 / 利好 / 多头趋势 / **中性偏多（2026-06-12 起）** / 日内支撑(值) / 止盈 / 价格(已/未/部分)兑现 / Maker 多头方向(低多·反弹多)
- **紫 purple**：注意事项 / 取消价
- 纯 bold 无色：CVD 四维行、防守层第一/二层；default：门禁 quote、技术面/盘口/盘面/策略/防守计划/BTC策略标题、持仓校准
- 🔑 **颜色跟情绪词走、不跟金标块位置走**（这是对旧记忆的反转）。~~**「中性偏空」恒黄**（基本面 label + 解读 label 都黄·非红非橙）~~【❌已订正 2026-06-12：用户迭代为**中性偏空→红、中性偏多→绿**，2026-06-03"中性偏空恒黄"口径废止；SENTIMENT 表已同步】；日内支撑/压力的「标签」run 默认色、只有「数值」run 上色（支撑绿/压力红）。

## 唯一正确流程（每次早/晚 Notion 出稿都照走）
1. **Daily payload 先机械派生**：新日报只允许 `py outputs/daily_payload_builder.py outputs/<date>_<slot>_combined.md` 生成 `daily-publish-payload-v4`；`combined.md` 是正文唯一真相源。Notion 只投影手工金标前台语法，完整审计推理仍在 `③ 后附` 和证据层。禁止手写 `children` JSON、复制日期专用 `_notion_push_*` / `_prepare_*`，禁止补写 combined 不存在的字段，更禁止为了视觉门压缩或删减推理。
2. **任何写入前先过时效+lint+派生签名**：`assert_source_freshness(...)`（Coinglass/Exo/TV四档≤4h；BlockBeats/FedWatch当日）→`run_report_lint(...)`→`publish_report.py` 重新从 combined 派生并校验 `payload_source.kind=combined_md_to_notion_payload`；失败即重采/重评分/重出稿。
3. **事务式 staging 发布**：snapshot全部旧同名前缀页→唯一staging标题建新页→上传三图→落库检查→改最终标题。准备阶段失败只归档staging、旧页保留。
4. **改最终标题后立即跑结构+配色双门**（脚本默认对照 6/2 金标）：
   ```
   $env:NOTION_TOKEN=...; py outputs/notion_verify_against_yesterday.py <今日page_id> morning|midday|evening
   ```
   - 门⓪ 标题：子页标题抹日期后须**逐字对齐金标格式**（防漏后缀漂移，如「🌙…晚间日报**（20:00 评分点）**」、「🌅…早间日报（11:00 评分点）」、「🌇…午间日报（15:30 评分点）」）。标题含 emoji，打印前用 `encode('gbk','ignore')` 剔除否则 PS 崩。
   - 门① 结构：`v3` 块类型序列 + 固定短标签 + 图片数/位置；历史 `v2` 才对照 6/2 金标。
   - 门①a 视觉密度：heading 长度为硬门；正文/quote/总文本密度只记录 WARN，只有接近 Notion API 单块上限或结构异常才硬停，禁止以缩短分析消除 WARN。
   - 门①b 语义配色（morning/midday/evening）：`report_colors.audit_page` 逐 run 按情绪词唯一规则校验。
   - **`[PASS]`（标题 + 结构对齐 + 配色符合规则）且进程退出码0才算完成**；`[FAIL]`/异常必须退出非零并回滚staging。标题漂移直接 `PATCH /v1/pages/{id}` 改 title property。
4. **门①通过后才提交替换**：归档snapshot中的全部旧页→检查同前缀恰好一个存活页且为新page id。清旧失败保留已验证新页并硬停，禁止回滚新页造成全失。
5. **配色错配可一键自动修**（按规范色就地 PATCH，免重建整页）：
   ```
   py outputs/report_colors.py <今日page_id> --fix
   ```
   单独审计（只看不改）：`py outputs/report_colors.py <page_id>`。

## 工具
- `outputs/report_colors.py`：唯一色规则 + 语义配色审计/自动修复；`expected_color(text)` 供 push 脚本 import；含 Notion SSL `UNEXPECTED_EOF` 重试（偶发·重跑即过）。
- `outputs/daily_payload_builder.py <combined>`：日报 Notion payload 唯一生成器；从 locked combined 与 source binding 机械派生 `v3` 的 31/32 个正文块、三张 BlockBeats 图和 `payload_source` 签名；历史 `v2` 仅复验。
- `outputs/notion_verify_against_yesterday.py <today> <morning|evening|review>`：结构门 + 调 report_colors 配色门。**禁 print emoji**（PS GBK 崩，用 [PASS]/[FAIL]）。
- 事务式替换唯一入口：`outputs/notion_push_lib.py::replace_page_transactional(...)`；禁止各日报脚本自行“先归档旧页再建页”。

见 [[basemian-needs-news-cards]]、[[report-template-alignment]]、[[push-report-to-ai-agent-plan]]、[[stability-contract]]。
