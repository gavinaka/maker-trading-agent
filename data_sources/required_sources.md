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
🟥 **盘口解读核心源**。一张截图同屏四变量（CVD / 价格 / 持仓量OI / 资金费率），盘口四维状态判定以此为准（见 `agents/footprint_agent.md` 统一读取法）。

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
> ⚠️ 硬要求：由 `capture_all.js`／`capture_delta.js` 统一自动采集，必须勾选页面「重要快讯」，同时存在当日 `blockbeats.png` + `blockbeats.json`，且 JSON 中 `"important_only": true`；禁止文字替代或退回未筛选快讯

### 用途
- 行业重大新闻
- 宏观消息
- 突发事件

### 硬性要求
必须截图。
禁止：
- AI总结替代截图
- 伪造新闻
- 使用历史新闻替代
- 使用未勾选「重要快讯」的全量资讯

---

# 数据源4

## CME FedWatch
https://www.cmegroup.com/cn-s/markets/interest-rates/cme-fedwatch-tool.html

> Collector SOP: `data_sources/collectors/fedwatch.md`

### 用途
- 美联储利率预期
- 流动性方向判断

### 输出要求
- 使用文字总结
- 判断：
  - 利多
  - 利空
  - 中性
  - 中性偏多
  - 中性偏空
- 浏览器截图失败时可使用**当日权威网络数据**替代：优先 CME Group 官方，其次 Federal Reserve 官方，再次为明确引用 CME 且标注时点的主流金融数据源。关键数字至少双源核验，并写入 `fedwatch.json` 留存来源、时间与失败原因；这属于 FedWatch 渲染层例外，不属于用历史数据兜底。

---

# 数据源5

## TradingView（BTCUSDT · Binance）
> Collector SOP: `data_sources/collectors/tradingview.md`
> 🟥 硬要求（2026-06-14 订正·宪法级）：必须 **日线 / 4H / 1H / 15m 四档截图齐**，缺任一档 = 五源未齐 = 硬停。

### 角色
🟥 **盘面(技术面)解读核心源**。盘面30分技术评分 + 趋势确认 + 日内支撑压力来自本源（非 Exocharts）。

### 用途
- 盘面(30)技术评分：支撑/压力区间、流动性掠夺、SMA20、量价、斐波/趋势线（日线层 + 小时层）
- 趋势确认（多头/空头/震荡）
- 日内支撑/压力（用户手绘线 + VRVP 成交量分布）
- 15m：Maker 入场位置最终把关（通道边缘挂单 + VRVP POC 避让）

### 输出要求
- 四档分别记录（日/4H/1H/15m）
- 盘面两层结论：日线级别 + 小时级别，各以「中性/利多/利空」收口

---

# 数据缺失规则
任意核心数据缺失，必须标注“待补充”，不得强行生成交易计划。
🟥 **五源缺一不可**（BlockBeats / Exocharts / Coinglass / FedWatch / TradingView，TV 须四档齐）：任一缺失立即硬停，不得用昨日/上份兜底、不得推演占位、不得跳过缺源。唯一例外：FedWatch 截图渲染失败但已按权威网络回退规则取得、双源核验并留存当日真实数据时，视为该源有效。
