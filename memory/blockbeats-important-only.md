# BlockBeats 基本面 12 小时重要快讯采集

## 永久规则

- 适用范围：Trading-System 后续全部早报、午报和晚报。
- BlockBeats 页面采集前必须勾选「重要快讯」，只允许提取筛选后的资讯。
- 无论早报、午报、晚报、delta 或单源重采，任何 BlockBeats 抓取行为都必须覆盖抓取前 12 小时内所有可加载「重要快讯」。
- `blockbeats.png` 必须保留已勾选状态作为视觉证据；`blockbeats.json` 必须写入 `"important_only": true`。
- `blockbeats.json` 必须写入 `"capture_window_hours": 12`、`"window_covered": true`、`candidate_rows`（12 小时候选池）、`selected_rows`（影响最大的 3 条）和 `rows`（必须等于 selected top3，供下游兼容）。
- 未找到筛选项、无法勾选、勾选后状态丢失、JSON 字段不合规、12 小时候选不足 3 条、窗口未覆盖、selected top3 缺失或 `rows` 与 `selected_rows` 不一致，均视为 BlockBeats 核心源无效并硬停；禁止用未筛选快讯、只看最新几条、当天全量替代 12 小时窗口或历史新闻降级继续。
- 筛选 top3 的优先级必须分桶执行，不得只靠关键词加分：宏观政策 > 监管政策 > BTC ETF/资金流 > 加密市场结构 > 交易所/链上安全/鲸鱼 > ETH/项目技术 > 非 BTC 二级行业叙事 > Meme/其他；Tier1 可主导基本面方向，Tier2 只能确认或微调。
- GDP、PPI/生产者价格指数属于宏观数据；`利率`不得裸子串匹配，只有政策利率、基准利率、联邦基金利率或明确的利率决定/决议/工具/路径/预期等宏观语义才能触发。企业 `毛利率`、产品 `收益率` 本身不得触发宏观桶。
- GDP 英文缩写还必须具有国家/地区、季度、实际值、修正或预期等宏观语境；同名代币、Token、Labs 或项目不得触发。`国内生产总值`按宏观全称处理。
- `流动性`必须有 Fed/FOMC/美元指数或美元走势/美债/央行/明确政策利率语义等宏观语境才能算宏观，单纯“万美元/亿美元”金额单位不得触发宏观；`需求`必须与 BTC ETF、IBIT、GBTC、Farside、净流入/净流出等共现才能算 ETF/资金流。
- SEC/CFTC/司法部等监管主体必须绑定 BTC/ETH、加密/数字资产、MiCA、明确加密交易平台等专属语境；裸“交易所/巨鲸”不能证明这是加密监管事件。
- 地缘事件按标题局部谓词标记 `ASSERTED / NEGATED / CONDITIONAL / PRODUCT / EFFECT`；只有已发生的主行动可触发 Tier1。正文只能认证或以同主体、同目标反证；否认伤亡/武器/法律属性不得抹掉行动，计划/押注/预测、产品题材及银行/大学/公司/个人等非国家主体不得误升。纯地缘事件保持兼容桶，但 `category/reasons` 使用`地缘政治`。
- Meme、个人投资复盘、AI/存储/芯片等非 BTC 叙事没有 BTC/ETF/宏观/监管直接语境时，只能留在 `candidate_rows`，不得挤占 `selected_rows` top3。
- “美股/AI/芯片”等行业词与明确 Tier1 宏观、监管或地缘事实共现时，明确 Tier1 事实优先；个人复盘与投机仓位标题仍维持降级边界。
- 分桶排序后必须先按确定性事件身份去重再取 top3。同一 PPI 发布族按标题 `period-PPI` 局部 span 绑定国家与 `year-month`；右侧影响对象不能反向充当发布国家，已被其他宾语消费的 publisher cue 不能借用。正文只证明实际值或提供反证，不得补身份或借用 CPI/PCE/GDP/PMI/ISM、预测、前值及同名实体。候选引用状态区分 `current / next_period / other_period / unrelated`，后续回指只继承最近 referent；更正、来源属地、待公布与预测仅在绑定当前候选时否决。比较值、历史同期与基数不等于当前预测或报告期。原始成员全部保留；预告、跨身份或信息不完整时不得模糊合并。
- 产出时只分析和制卡这 3 条影响最大的新闻，但③后附必须说明它们来自 12 小时候选池筛选，而不是少读。

## 机械实现

- 权威采集器：`tools/browser_capture/capture_blockbeats.js`。
- 采集器关闭可能遮挡筛选项的 OneSignal 提示，定位包含「重要快讯」的复选框并确认其保持选中。
- 采集器滚动/点击「查看更多」直到覆盖抓取前 12 小时窗口；机械层保留候选池，按 `priority_bucket/bucket_rank`、`score`、时间排序，再对可确定识别的同发布事件族去重，给出 3 个独立事件。
- 有效性表达式必须包含 `importantOnly`、`capture_window_hours=12`、`window_covered=true`、`candidate_rows>=3`、`selected_rows=3`、`rows==selected_rows`；采集失败返回非零状态，使 `capture_all.js`／`capture_delta.js` 按核心源失败处理。

## 来源

- 2026-07-02 用户明确要求：基本面采集仅采集「重要快讯」，其他不变，并要求后续所有报告永久沿用。
- 2026-07-04 用户补充：任何 BlockBeats 抓取都必须覆盖抓取前 12 小时全部数据，再按既有维度优先级筛出 3 条影响最大的新闻进入分析推理和最终产出。
