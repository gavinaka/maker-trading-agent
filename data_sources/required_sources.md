# 必须数据源

# 核心原则
所有交易计划必须基于实时数据。
禁止：
- 使用历史缓存
- 使用猜测
- 使用推理补全
- 使用缺失数据强行输出

---

# 数据源1

## ExoCharts
https://exocharts.com/web/

> Collector SOP: `data_sources/collectors/exocharts.md`

### 角色（2026-06-14 用户校准·宪法级）
🟥 **不是盘口主源**。盘口四变量解读核心 = Coinglass 截图（见数据源2）。ExoCharts 仅作 **印证 + 更细颗粒度（footprint 足迹）的数据参照**，确保 Coinglass 判断准确。与 Coinglass 冲突时以 Coinglass 为准复核，ExoCharts 不单方覆盖。

### 用途
- footprint 足迹信号（吸收/失衡/POC）= 更细颗粒度印证（见 `scoring/orderflow_methodology.md` 第八节）
- CVD / 价格行为结构 / 技术结构的**交叉印证**（核心读数仍取 Coinglass）

### 输出要求
- 使用文字记录
- 作印证用：
  - footprint 足迹信号（无档位则置 null·禁臆造）
  - CVD/价格/结构（仅与 Coinglass 交叉核对，不覆盖核心读数）

---

# 数据源2

## Coinglass
* 主图（三指标合一）：https://www.coinglass.com/tv/zh/Bybit_BTCUSDT
* 资金费率明细（备用）：https://www.coinglass.com/FundingRate
* 持仓量明细（备用）：https://www.coinglass.com/BitcoinOpenInterest

> Collector SOP: `data_sources/collectors/coinglass.md`

### 角色（2026-06-14 用户校准·宪法级）
🟥 **盘口解读核心源**。一张截图同屏四变量（CVD / 价格 / 持仓量OI / 资金费率），四维必须按 `scoring/orderflow_methodology.md` 用同一 BTC 1H 价格 pivot 读取；禁止各面板各取自己的局部极值。

### 用途
- CVD（核心读数）
- 价格行为
- 持仓量OI
- 资金费率

### 输出要求
- 判断 CVD 方向（核心）
- 判断价格方向
- 判断持仓变化
- 判断资金费率状态（趋势 + 正负双轨）

---

# 数据源3

## BlockBeats
https://www.theblockbeats.info/newsflash

> Collector SOP: `data_sources/collectors/blockbeats.md`
> ⚠️ vNext 硬要求：只由 control-plane hash 绑定的 `capture_all.js` 统一采集，必须勾选页面「重要快讯」，同时存在本轮 `blockbeats.png` + `blockbeats.json`，且 JSON 中 `"important_only": true`；禁止模型选择其它入口、文字替代或退回未筛选快讯

### 用途
- 行业重大新闻
- 宏观消息
- 突发事件
- vNext canonical BlockBeats `observation.metrics` 只允许 `tier`、`event_window_hours`、`selected_event_count`、`selected_event_sha256` 四个字段，用于事件事实、时间窗与影响层级；不得在该 metrics 内写价格兑现。
- 价格是否已兑现只由 BlockBeats + TradingView 共同支持的 `fundamental_price_realization` 跨源 typed claim 拥有；BlockBeats 单源不得直接生成兑现状态或交易方向。

### 硬性要求
必须截图。
禁止：
- AI总结替代截图
- 伪造新闻
- 使用历史新闻替代
- 使用未勾选「重要快讯」的全量资讯

---

# 数据源4

## FOMC 利率预期（内部兼容 key：FedWatch）
https://www.cmegroup.com/cn-s/markets/interest-rates/cme-fedwatch-tool.html

> Collector SOP: `data_sources/collectors/fedwatch.md`

### 用途
- 美联储利率预期
- 流动性方向判断

### 输出要求
- CME 官方 UI 是唯一 primary。CME 有效时只转录本轮真实概率工具中的当前分布、
  下次 FOMC 日期及 1日/1周/1月边际变化，Kalshi 调用次数必须为 0。
- 仅当本轮 CME attempt 以合同闭集代码证明网站技术不可用时，允许恰好一次
  A5-R1e Plan C：Kalshi public API `KXFEDDECISION`。它是独立事件合约市场，
  非 CME 方法等价，必须保留 `other_unlisted` 与 `>25bp` 聚合桶，并使用同一
  bid/ask midpoint + bounded-simplex 口径计算 current 与三个历史窗口。
- 只输出宏观预期背景与事件窗口，不直接生成 Maker 或主账户方向，不计入盘口/盘面分。
- CME 路径必须有真实截图；Plan C 路径必须有同 run 的 sealed CME failure、Kalshi raw、
  normalized JSON 与 provider provenance。禁止付费 CME API、Federal Reserve、媒体、
  搜索摘要、其它 series 或模型估算替代。
- Plan C 样本只能进入 `observation`，不得增加 current clean、trailing clean 或切换资格。

---

# 数据源5

## Farside BTC ETF Flow
https://farside.co.uk/btc/

> Collector SOP: `data_sources/collectors/farside_btc_etf.md`

### 用途
- 美国 BTC 现货 ETF 日度净流入/净流出确认。
- Farside canonical `observation.metrics` 只允许 `latest_complete_date`、`latest_total_usd_m`、`flow_direction` 三个字段；价格关系不属于本源 metrics，只能由下游 `etf_confirmation` typed claim 拥有。
- 已认证的Coinglass同锚价格方向×ETF流向使用以下确定性九格表，不得自由改写：

| 同锚价格方向 | `inflow` | `outflow` | `flat` |
|---|---|---|---|
| `up` | `confirm` | `weaken` | `neutral` |
| `down` | `weaken` | `confirm` | `neutral` |
| `flat` | `neutral` | `neutral` | `neutral` |

- 定位是策略辅助验证，不替代 Coinglass/Exocharts 盘口判断，也不替代 TradingView 盘面评分。

### 输出要求
- `farside_btc_etf.png`：页面截图，须能看出 `Bitcoin ETF Flow (US$m)` 表格。
- `farside_btc_etf.json`：结构化解析，须包含 `source=farside_btc_etf`、`url=https://farside.co.uk/btc/`、`unit=US$m`、`latest.date`、数值型 `latest.total_usd_m`、`latest.direction`、`rows` 与 `validity`。
- `validity.title_match/table_found/has_total_column/latest_daily_row/latest_total_is_number` 必须全部为 true；否则该源无效。
- Collector JSON 可以保留采集审计字段；进入reasoning的canonical `observation.metrics`必须投影为且只投影为上述三个业务字段，禁止把`price_relation`、自由文本解释或其它派生判断塞回本源metrics。

---

# 数据源6

## TradingView（BTCUSDT · Binance）
> Collector SOP: `data_sources/collectors/tradingview.md`
> 🟥 硬要求（2026-06-14 订正·宪法级）：必须 **日线 / 4H / 1H / 15m 四档截图齐**，缺任一档 = 六源未齐 = 硬停。

### 角色
🟥 **盘面(技术面)解读核心源**。盘面30分技术评分 + 趋势确认 + 日内支撑压力来自本源（非 Exocharts）。

### 用途
- 盘面(30)技术评分：支撑/压力区间、流动性掠夺、SMA20、量价、斐波/趋势线（日线层 + 小时层）
- 趋势确认（多头/空头/震荡）
- 日内支撑/压力（用户手绘线 + 可读的用户手绘成交量分布区域）
- 15m：Maker 入场位置最终把关（通道边缘挂单 + 可读手绘区域避让）

### 输出要求
- 四档分别记录（日/4H/1H/15m）
- 盘面两层结论：日线级别 + 小时级别，各以「中性/利多/利空」收口
- 当前 profile 模式固定为 `user_drawn_manual_only`：平台内置 VRVP 隐藏且永不取值；自动 POC/VAH/VAL/HVN/LVN 禁止。手绘区域不可读时只把 profile 维度标为 `insufficient`（`zones=[]`、原因必填、流动性猎杀分0），四周期结构仍属于有效 TradingView 证据；Coinglass 清算图不得替代或翻向。

---

# 数据缺失规则
🟥 **六源缺一不可**（BlockBeats / Coinglass / Exocharts / FedWatch 逻辑插槽 / Farside BTC ETF Flow / TradingView，TV 须四档齐）：任一缺失、过期、无效或跨 run/slot 立即让整个 evidence stage 失败，不得用昨日/上份兜底、不得写“待补充”后生成部分报告、不得推演占位、不得跳过缺源。FedWatch 插槽只有 `rate_expectation_provider_contract.json` 规定的 CME primary → closed technical failure → Kalshi Plan C 例外；没有泛化网络、媒体、搜索或模型回退。
