---
name: report-chinese-only-narrative
description: 日报【Notion 正文】(①正文+②Maker)叙事术语一律中译·不留英文;保留指标缩写/模板字段/专有名词;纯文字输出层·思考零改;已加 report_lint 正文英文术语门机械强制。
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5234787a-825a-4674-8e69-130bc98af7a8
---

2026-06-25 用户迭代:近期报告正文**多次中英混排英文术语**(深度检核属实——近3份正文英文 100+ 次:squeeze 27/SMA20 32/CVD 14/HTF 13/confluence/roll over/grab/air pocket/relief…)。用户要求**正文一律用中文形式·不要任何可中译的英文叙事术语**(「如流动性相关的情况」)。

🟥 **边界(用户 2026-06-25 拍板·AskUserQuestion 选项①「保留指标缩写+模板字段」)**:
- **叙事术语一律中译**(无争议):squeeze→逼空/挤升、squeeze-back→逼空反扑、roll over/rollover→见顶回落、confluence→汇合区/共振区、grab→猎取/扫取、retest→回踩、relief→缓解性反弹、air pocket→真空薄量区、deep-value→深度价值、risk-on→风险偏好、risk-off→避险、macro→宏观、HTF→高周期、HVN/LVN→高量/低量节点、fib→斐波那契、overshoot→过冲、continuation→续势/续跌、consolidation→整理、exhaustion→衰竭、capitulate→投降、whipsaw→双向扫损、edge→边缘、supply→供给、floor→底部支撑、VIEW→研判、late/trapped longs→高位/被套多头、short-covering→空头回补、premium→优质/溢价、straddle→骑跨、false break→假突破、mean-reversion→均值回归、violent→剧烈。
- **保留·不译**:①指标缩写(行业标准·部分在模板)=CVD/OI/SMA20/SMA200/POC/VAH/VAL/VRVP/Delta/VWAP/R、数字单位 K/M;②模板字段/账户名(用户 Notion 模板自带·译会违 [[report-template-alignment]] 宪法)=Maker/TP1/TP2/BTC/ETH/Binance/OKX;③专有名词(无中文形式·且新闻里不可预知)=交易所/源(Coinglass/Exocharts/Exo/TradingView/TV/CME/FedWatch/BlockBeats/Coinbase)、监管/科技(MiCA/FOMC/IAEA/ETF/AI/DRAM/NAND/GPU)、公司/ticker(MU/KOSPI/Strategy/Franklin…)、时间周期(1H/4H/15m/48H/24H)。

🟥 **范围=仅 Notion 正文(①正文+②Maker)**(用户选「仅Notion正文」):**③后附明细(本地 docx·不进 Notion)与方法论文档(scoring/*.md 等思考层参考)保留英文·不动**。

**Why:** 用户要中文形式的可读报告;英文叙事术语对其阅读/执行是噪声。指标缩写与模板字段是「硬通货」(行业读作缩写·且 Maker/TP1/CVD 在用户锁定的 Notion 模板里·译它们反而违模板对齐宪法)、专有名词无中文形式(且新闻专有名词不可预知)→保留。③后附是系统内部备份、方法论是思考层→不动(纯文字输出层迭代·逻辑/评分/六源/框架零改·同 [[fundamentals-brief-core-priority]] 只换文字不换思考)。

**How to apply:** 出稿写 ①②正文(combined.md 的 `## ①`~`## ③` 段 + push 脚本 blocks)时,叙事术语直接写中文、只在上列保留清单里留英文。🟥 **机械强制已落地=`outputs/report_lint.py` 新增「正文英文术语门」(2026-06-25)**:禁用清单式(只抓已知叙事英文·不误伤新闻专有名词与保留缩写)、仅扫 `## ①`~`## ③` 之间(③后附/稿首自查块豁免)、命中即 HARD FAIL;新叙事英文按需扩 `EN_JARGON` 清单。配 [[notion-publish-checklist]] 三门:push 前 lint(门②·含本门)→push→verifier(门①·只验结构/配色/元叙事·不验英文)。通用教训(同 [[fundamentals-brief-core-priority]]):**纯文档层铁律必同步加 lint 机械闸否则形同虚设**——本规则一来就配了门。
