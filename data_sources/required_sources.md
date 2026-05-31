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

### 用途
- CVD
- 价格行为结构
- 技术结构

### 输出要求
- 使用文字记录
- 判断：
  - CVD方向
  - 价格方向
  - 结构状态

---

# 数据源2

## Coinglass
* 主图（三指标合一）：https://www.coinglass.com/tv/zh/Bybit_BTCUSDT
* 资金费率明细（备用）：https://www.coinglass.com/FundingRate
* 持仓量明细（备用）：https://www.coinglass.com/BitcoinOpenInterest

> Collector SOP: `data_sources/collectors/coinglass.md`

### 用途
- 资金费率
- 持仓量
- CVD辅助确认

### 输出要求
- 判断资金费率状态
- 判断持仓变化
- 判断多空结构

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

# 数据缺失规则
任意核心数据缺失，必须标注“待补充”，不得强行生成交易计划。
