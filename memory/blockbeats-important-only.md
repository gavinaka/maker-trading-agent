# BlockBeats 基本面 12 小时重要快讯采集

## 永久规则

- 适用范围：Trading-System 后续全部早报、午报和晚报。
- BlockBeats 页面采集前必须勾选「重要快讯」，只允许提取筛选后的资讯。
- 无论早报、午报、晚报、delta 或单源重采，任何 BlockBeats 抓取行为都必须覆盖抓取前 12 小时内所有可加载「重要快讯」。
- `blockbeats.png` 必须保留已勾选状态作为视觉证据；`blockbeats.json` 必须写入 `"important_only": true`。
- `blockbeats.json` 必须写入 `"capture_window_hours": 12`、`"window_covered": true`、`candidate_rows`（12 小时候选池）、`selected_rows`（影响最大的 3 条）和 `rows`（必须等于 selected top3，供下游兼容）。
- 未找到筛选项、无法勾选、勾选后状态丢失、JSON 字段不合规、12 小时候选不足 3 条、窗口未覆盖、selected top3 缺失或 `rows` 与 `selected_rows` 不一致，均视为 BlockBeats 核心源无效并硬停；禁止用未筛选快讯、只看最新几条、当天全量替代 12 小时窗口或历史新闻降级继续。
- 筛选 top3 的优先级必须分桶执行，不得只靠关键词加分：宏观政策 > 监管政策 > BTC ETF/资金流 > 加密市场结构 > 交易所/链上安全/鲸鱼 > ETH/项目技术 > 非 BTC 二级行业叙事 > Meme/其他；Tier1 可主导基本面方向，Tier2 只能确认或微调。
- `流动性`必须有 Fed/FOMC/美元指数或美元走势/美债/央行/利率等宏观语境才能算宏观，单纯“万美元/亿美元”金额单位不得触发宏观；`需求`必须与 BTC ETF、IBIT、GBTC、Farside、净流入/净流出等共现才能算 ETF/资金流。
- Meme、个人投资复盘、AI/存储/芯片等非 BTC 叙事没有 BTC/ETF/宏观/监管直接语境时，只能留在 `candidate_rows`，不得挤占 `selected_rows` top3。
- 产出时只分析和制卡这 3 条影响最大的新闻，但③后附必须说明它们来自 12 小时候选池筛选，而不是少读。

## 机械实现

- 权威采集器：`tools/browser_capture/capture_blockbeats.js`。
- 采集器关闭可能遮挡筛选项的 OneSignal 提示，定位包含「重要快讯」的复选框并确认其保持选中。
- 采集器滚动/点击「查看更多」直到覆盖抓取前 12 小时窗口；机械层保留候选池并按确定性分桶优先级给出 top3。排序字段以 `priority_bucket/bucket_rank` 为第一优先级，`score` 为第二优先级，时间为第三优先级。
- 有效性表达式必须包含 `importantOnly`、`capture_window_hours=12`、`window_covered=true`、`candidate_rows>=3`、`selected_rows=3`、`rows==selected_rows`；采集失败返回非零状态，使 `capture_all.js`／`capture_delta.js` 按核心源失败处理。

## 来源

- 2026-07-02 用户明确要求：基本面采集仅采集「重要快讯」，其他不变，并要求后续所有报告永久沿用。
- 2026-07-04 用户补充：任何 BlockBeats 抓取都必须覆盖抓取前 12 小时全部数据，再按既有维度优先级筛出 3 条影响最大的新闻进入分析推理和最终产出。
