# TradingView Collector SOP

> 🟥 **源角色（2026-06-14 订正·宪法级）**：TradingView 是 **盘面(技术面)解读核心源**，第 5 必抓源、缺一不可。盘面30分技术评分 + 趋势确认 + 日内支撑压力 + Maker 入场把关全部来自本源（**非 Exocharts**）。

## 目标
采集 BTCUSDT（Binance）**日线 / 4H / 1H / 15m 四档**截图 → `inbox/<YYYY-MM-DD>/tradingview_btc_<tf>.{png,json}`，供 scoring_agent 盘面(30)评分与 Maker 入场把关。

## 文件命名约定（必须遵守）
* `<tf>`：`1d` / `4h` / `1h` / `15m`
* 例：`tradingview_btc_1d.png` / `tradingview_btc_1d.json`
* 🟥 **四档缺一 = 五源未齐 = 硬停**（见 `data_sources/required_sources.md` 数据缺失规则）。

## 数据源
TradingView · BTCUSDT · 交易所 Binance（与日内极值/手绘线口径一致）

## 通道约束
* 主通道：**C**（用户截图投递）—— TradingView 登录/绘图态在用户本地，已知 navigate 被拒（见 `sessions/日报SOP.md`），不尝试自动抓。
* 禁止：A / B（不 navigate、不 WebFetch）。

---

## 通道 C 执行流

1. 等用户提供四档截图（日/4H/1H/15m），每档含：
   * VRVP（成交量分布）+ POC
   * 用户手绘支撑/压力水平线
   * 通道线（上升/下降通道）
   * 交易宪法（图右 5 条，仅 15m 档常带）
2. 每档抽取关键值，写 `tradingview_btc_<tf>.json`：
   ```json
   {
     "symbol": "BTCUSDT",
     "exchange": "Binance",
     "timeframe": "1d | 4h | 1h | 15m",
     "captured_at": "<ISO>",
     "last_close": <number>,
     "trend": "up | down | range",
     "structure": "higher_high | lower_low | range | breakout_up | breakout_down | uncertain",
     "sma20_relation": "above | below | retest_confirm | none",
     "support": [<number>, ...],
     "resistance": [<number>, ...],
     "fib_or_trendline": "near_0.618 | near_0.786 | near_trendline | none",
     "vrvp_poc": <number>,
     "price_vs_poc": "far | near",
     "channel_position": "upper_edge | mid | lower_edge | none",
     "volume_price": "放量上涨 | 放量下跌 | 缩量震荡 | 背离 | none",
     "level_conclusion": "中性 | 利多 | 利空"
   }
   ```
3. 写 manifest 主条目（指向日线为主，其余作 files 列表附加）。

### 各档用途分流
* **日线 1d** → 盘面日线级别结论 + 趋势确认（大方向）
* **4H / 1H** → 盘面小时级别结论 + 支撑压力 + SMA20/斐波（结构精度）
* **15m** → Maker 入场位置最终把关：通道边缘挂单（≠追价）+ VRVP POC 密集区避让（见 `governance/workflow.md` Phase 01.5）

---

## 盘面(30)取数对照（scoring_agent Phase 4 / chart_scoring.md）

| 盘面指标 | 满分 | 取自字段 | 主用档 |
|---|---|---|---|
| 支撑/压力区间接近度 | 10 | support/resistance + 现价 | 4H/1H |
| 多空流动性掠夺 | 10 | structure（sweep/扫损/诱多空） | 1H/15m |
| SMA20 突破/回踩 | 5 | sma20_relation | 1H |
| 量价关系 | 3 | volume_price | 日线/1H |
| 斐波/趋势线接近度 | 2 | fib_or_trendline | 4H/1H |

---

## 失败处理
* 缺任一档（日/4H/1H/15m）→ `valid:false` + `missing_timeframes:[...]` → **五源未齐硬停**，不评分。
* 结构/趋势判断不确定 → 对应字段 `uncertain` / `none`，不允许猜测。

---

## 注意
* 枚举值必须用规定值，禁止自由文本。
* **核心读数取用户手绘线/VRVP**：日内支撑压力以用户图上手绘线为准，不臆造价位（精确数字·禁模糊位）。
* TradingView 头部 O/H/L/C 是光标悬停那根（可能别的日期），非现价；日内高低必扫整段 K 线 wick、跨源核验。
* 四档若出现冲突方向，全部记录，由 scoring_agent + footprint 综合（盘面辅助、盘口优先）。
