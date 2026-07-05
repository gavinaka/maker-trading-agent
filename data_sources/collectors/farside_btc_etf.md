# Farside BTC ETF Flow Collector

## 入口

- URL: https://farside.co.uk/btc/
- 脚本: `tools/browser_capture/capture_farside_btc_etf.js`
- 输出目录: `data_sources/inbox/<YYYY-MM-DD>/`

## 输出

- `farside_btc_etf.png`: `Bitcoin ETF Flow (US$m)` 页面截图。
- `farside_btc_etf.json`: 结构化解析结果，至少包含：
  - `source=farside_btc_etf`
  - `url=https://farside.co.uk/btc/`
  - `unit=US$m`
  - `latest.date`
  - 数值型 `latest.total_usd_m`
  - `latest.direction` (`inflow` / `outflow` / `flat`)
  - `previous`
  - `recent_5d_net_usd_m`
  - `rows`
  - `validity`

## 有效性门

以下任一失败均视为该源缺失，按六源硬停：

- PNG 或 JSON 缺失、为空或非当日采集文件。
- 页面标题不匹配 `Bitcoin ETF Flow (US$m)`。
- 表格未找到 `Total` 列。
- `latest` 日度行缺失。
- `latest.total_usd_m` 不是数值。
- `latest.direction` 与 `latest.total_usd_m` 正负不一致。

## 报告口径

- 价格下跌 + ETF 净流出 = 现货侧一致看空；流出扩大 = 强一致。
- 价格上涨 + ETF 净流入 = 现货侧一致看多；流入扩大 = 强一致。
- 价格方向与 ETF 流向背离 = 行情健康度下降，反弹或下跌缺少现货侧确认。
- 本源只做策略辅助验证，不替代 Coinglass/Exocharts 盘口评分，也不替代 TradingView 盘面评分。
