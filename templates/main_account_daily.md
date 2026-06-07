# 主账户日报模板（图谱第十节，严格格式）

> 本模板由 `agents/output_agent.md` 调用渲染。
> 词汇必须来自 `constitution/terminology.md`。
> 数据不全字段标 `[待补充 - <原因>]`，**禁止删除字段或省略段落**。

---

## 模板正文

```
{{YYYY-MM-DD}}

不能做：{{追多空 | 做多 | 做空}}

基本面：{{利多 | 利空 | 中性 | 中性偏多 | 中性偏空}}（{{原因}}）价格{{已兑现 | 未兑现 | 已兑现部分}}
{{重要新闻列表（含时间戳，来源 BlockBeats 截图）}}

技术面：
盘口（合约）：
CVD{{上升 | 下降 | 横盘}} 价格{{方向}} 资金费率{{状态}}（{{为正值 | 为负值 | 接近0值}}）持仓{{方向}}
解读：{{中性 | 中性偏多 | 中性偏空 | 看跌背离 | 看涨背离}}（{{原因}}）

盘面：
日线级别{{分析内容}} {{综合判断}}
小时级别{{分析内容}} {{综合判断}}

趋势确认：{{多头趋势 | 空头趋势 | 震荡结构}}（{{单边 | 中短线 | 短线}}）
日内支撑：{{价格区间}}    日内压力：{{价格区间}}

策略：
{{中线计划内容 | 迭代 | 保持不变}}
```

---

## 字段来源

| 字段 | 来源 |
|---|---|
| 不能做 | 当天 Maker 市场推导（禁追最拥挤一边），写完全文最后回填；**非主账户字段**（2026-05-31 订正） |
| 基本面 | `outputs/<today>_news_summary.json` → `aggregate_sentiment` + `aggregate_reason` |
| 价格兑现 | 用户输入 / 上日预测对照（review_agent 输出） |
| 重要新闻列表 | `outputs/<today>_news_summary.json` → `items[]`（仅引用 screenshot 文件名 + headline） |
| 盘口 4 项 | `outputs/<today>_footprint_<HHMM>.json` → `raw_state` 中文映射 |
| 解读 | 同上 → `signal_type` + `rationale` |
| 日线/小时分析 | `inbox/<today>/exocharts_btc_1d.json` + `exocharts_btc_1h.json` → `recent_structure` + `key_levels` |
| 趋势确认 | `state/main_account_state.json` → `trend_confirmation` |
| 日内支撑/压力 | `inbox/<today>/exocharts_btc_1h.json` → `key_levels.support` / `resistance` |
| 策略 | `state/main_account_state.json` → `position_status` + `mid_term_structure`；有迭代 → 描述迭代；无 → "保持不变" |

---

## 示例（历史快照 · 仅示意格式；持仓真值以 Notion 交易Check 为准）

```
2026-05-29

不能做：做多

基本面：中性（黑客事件与机构存入交易所 vs Coinbase 合规扩张相抵；通胀信号矛盾）价格未兑现
[重要新闻（含时间戳，来源BlockBeats截图）]
[10:39] 派盾：DxSale 遭攻击，BSC 上旧 LP 被抽取 730 万美元  → 截图: blockbeats_001.png
[10:11] Strategy 向 Coinbase Prime 存入 411.48 枚 BTC，价值 3030 万美元  → 截图: blockbeats_002.png
[09:47] Coinbase 推出全球加密合规网络 TRUSThub  → 截图: blockbeats_003.png

技术面：
盘口（合约）：
CVD[待补充] 价格[待补充] 资金费率[待补充] 持仓[待补充]
解读：[待补充 - Exocharts/Coinglass 数据待采集]

盘面：
日线级别[待补充] [待补充]
小时级别[待补充] [待补充]

趋势确认：空头趋势（中短线）
日内支撑：[待补充]    日内压力：[待补充]

策略：
持中线做空（5 层防守，已激活保本损 + 动态止损）
─ 持仓：BTCUSDT short / 均价 79,150 / 仓位 $500 / 5x / 50%
─ 中线计划：保持不变（active_plan=true, layer 5/5）
─ 日内：维持原计划，不新增仓位
```

---

## 渲染规则

1. **字段不可省**——所有 8 个段落（不能做 / 基本面 / 重要新闻 / 盘口 / 盘面 / 趋势确认 / 支撑压力 / 策略）必须出现
2. **词汇白名单**——严格使用 `constitution/terminology.md` 的标准词，不允许同义词替换
3. **禁止 AI 总结**——基本面原因必须基于 news_summary 的 aggregate_reason，不允许自由发挥
4. **新闻只引用截图文件名**——不复制新闻正文（避免代替截图）
5. **缺失字段格式**——`[待补充 - <一句话原因>]`，不允许留空或写"无数据"
