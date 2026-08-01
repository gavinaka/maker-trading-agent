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
  - `latest.date`（最近完整发布行，而非页面最上方占位行）
  - `latest.funds`（至少一个基金必须为已发布数值）
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
- 页面最上方行若全部基金仍为 `-`，该行是未发布占位行，禁止解释为零流入；应跳过并选择最近一个至少含一个基金数值的完整发布行。
- `latest.total_usd_m` 不是数值。
- `latest.funds` 没有任何已发布数值，或 `validity.latest_row_complete` 不为 `true`。
- `latest.direction` 与 `latest.total_usd_m` 正负不一致。

## 报告口径

- Collector原始JSON可保留审计字段，但进入reasoning的Farside canonical `observation.metrics`必须且只能包含 `latest_complete_date`、`latest_total_usd_m`、`flow_direction`；禁止写入 `price_relation` 或自由文本判断。
- `price_relation` 只由下游 `etf_confirmation` typed claim 按已认证的Coinglass同锚价格方向×ETF流向确定性生成：

| 同锚价格方向 | `inflow` | `outflow` | `flat` |
|---|---|---|---|
| `up` | `confirm` | `weaken` | `neutral` |
| `down` | `weaken` | `confirm` | `neutral` |
| `flat` | `neutral` | `neutral` | `neutral` |

- 本源只做策略辅助验证，不替代Coinglass/Exocharts盘口判断，也不替代TradingView盘面评分；ETF只可确认、削弱或保持中性，不可单变量翻向。
