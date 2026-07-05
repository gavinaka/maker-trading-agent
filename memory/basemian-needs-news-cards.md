---
name: basemian-needs-news-cards
description: 日报「基本面」字段必须配 BlockBeats 快讯卡配图，且整页接近昨日 Notion 结构；字段含义和发布机械门必须通过。
metadata:
  node_type: memory
  type: feedback
  originSessionId: 455d12d8-37e5-491a-80a9-e19da8aa9eaf
---

用户两次强调：日报推 Notion 时**「基本面」字段必须带配图**——3 张 BlockBeats「快讯卡」插在基本面块正后方，存 `outputs/blockbeats/{date}_N_xxx.png`；任何抓取都先覆盖抓取前 12 小时全部「重要快讯」候选池，再选最能影响基本面方向的 3 条（政治/宏观/监管 Tier1 优先，ETF/资金流/机构与链上安全次之，行业代表只作补充）。

🟥**卡片样式 2026-06-21 改版（用户要求对齐手工报告＝BlockBeats 律动夜间真卡）**：唯一权威渲染器=`outputs/blockbeats_card.py`（`make_card(fname,time,title,body)`）；新日报只通过参数化入口 `py outputs/generate_cards.py <card_payload.json>` 调用它生成三张卡，禁止再新建日期专用 `_make_blockbeats_cards_{date}.py`。格式规格：深蓝黑底 `(18,25,38)`＋时间橙金加粗 `(240,173,78)`＋标题白色加粗同行紧跟时间 `(236,240,246)`＋正文浅灰 `(150,161,175)`·正文按 `\n` 分段留空行；msyhbd 标题 25/msyh 正文 21；**W=820 高度自适应**；**无左色条·无右上 Tier pill·无单独「BlockBeats 快讯」meta 行**。🪦旧样式（白底+左侧红/蓝/绿色条+time「BlockBeats 快讯」meta+右上 Tier pill）已废。用户口径=「只改背景格式+高宽，数据深度（含完整时间/来源串）全不变」——时间字段保留完整 provenance（如「FedWatch 数据 6/20 09:30CT / 期权 6/21 09:51」）不简化为短 HH:MM。

**整页格式只要求接近 100% 对齐昨日 Notion 早间页结构**；字段含义、交易参数、快讯卡位置、块型、配色和 verifier 仍是硬门。出稿前可复用固定骨架，避免为追求版式 100% 消耗推理 token。早间标准 28 块骨架：
1 `quote` 门禁/心力/总评分 → 2 `heading_2` 不能做 → 3 `heading_3` 基本面(中性偏空(…)价格X兑现，整行不拆) → 4-6 `image`×3 快讯卡 → 7 `heading_3` 技术面 → 8 `paragraph` 盘口（合约）→ 9 `paragraph` CVD四维 → 10 `heading_3` 解读 → 11 `paragraph` 盘面 → 12 `paragraph` 日线级别…利空 → 13 `paragraph` 小时级别…利空 → 14 `heading_3` 趋势确认 → 15 `heading_3` 日内支撑/压力(同一行) → 16 `heading_3` 策略 → 17 `paragraph` 策略正文 → 18 `divider` → 19 `heading_2` BTC（策略）：执行概率X 胜率X → 20 `paragraph` 反弹空/方向+入场区 → 21 `paragraph` 止盈 → 22 `paragraph` 止损 → 23 `heading_3` 防守计划 → 24-25 `paragraph` 第一/第二层 → 26 `paragraph` 注意事项 → 27 `paragraph` ⚠️取消价≠止损 → 28 `paragraph` 持仓校准。

**逐 run 字体颜色＝按情绪词确定性着色**（2026-06-03 用户再指「字体颜色没渲染」→ 拍板：配色跟情绪词走、不跟金标块位置走；权威=唯一色规则，机械校验，见 [[notion-publish-checklist]] 与 `outputs/report_colors.py`）。唯一色规则：**红**=利空/空头趋势/日内压力(值)/止损/「（追）做X」/Maker空头方向(反弹空·高空·做空)；**黄**=中性/**中性偏空**/中性偏多/震荡结构/基本面理由段/策略正文/**解读标签(中性系)**；**绿**=利多/利好/多头趋势/日内支撑(值)/止盈/价格(已/未/部分)兑现/Maker多头方向(低多·反弹多)；**紫**=注意事项/取消价；纯 bold 无色=CVD四维/防守层第一二层；门禁 quote+技术面/盘口/盘面/策略/防守计划/BTC策略标题+持仓校准=default。🔑 **「中性偏空」恒黄**（基本面 label + 解读 label 都黄·非红非橙；旧记忆"解读恒yellow/基本面中性偏空=red/颜色跟位置"已废）。出稿后跑 `py outputs/report_colors.py <page_id> --fix` 一键按规范色就地修，再跑 verifier 双门到 PASS。

**禁止**：用 callout 代替 quote 门禁行；run 不上色（必须按上面配色逐 run 染）；把不能做/技术面/解读/趋势/支撑压力/策略/防守计划写成 paragraph（必须 heading）；加「①日报正文/②Maker计划/③后附」包装标题（Notion 正文里没有，后附只进本地 docx）；基本面拆成多个带色 run（应整行 heading_3）。重建已存在的同名子页用 `PATCH /v1/pages/{id} {archived:true}` 归档旧页（不是 /v1/blocks/），再 create_page。

**Why**：用户不想每天纠格式、耗 token；基本面无图=信息不完整。**How to apply**：用固定骨架和发布 verifier 控制格式接近 100%，基本面块后必插快讯卡；不要每天重新读取旧页或旧 Word 做格式识别。见 [[report-template-alignment]] [[push-report-to-ai-agent-plan]] [[evening-review-visual-to-notion]]。
