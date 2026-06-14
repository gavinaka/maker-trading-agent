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
> ⚠️ 硬要求：必须截图，禁止文字替代

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
🟥 **五源缺一不可**（BlockBeats / Exocharts / Coinglass / FedWatch / TradingView，TV 须四档齐）：任一缺失立即硬停，不得用昨日/上份兜底、不得推演占位、不得跳过缺源。
