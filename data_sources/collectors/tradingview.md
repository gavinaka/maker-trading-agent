# TradingView Collector SOP

> 🟥 **源角色（2026-06-14 订正·宪法级）**：TradingView 是 **盘面(技术面)解读核心源**，六源中的第 6 源、缺一不可。盘面30分技术评分 + 趋势确认 + 日内支撑压力 + Maker 入场把关全部来自本源（**非 Exocharts**）。

## 目标
采集 BTCUSDT（Binance）**日线 / 4H / 1H / 15m 四档**截图，供盘面(30)评分与 Maker 入场把关。当前成交量分布来源固定为 `user_drawn_manual_only`：只允许读取用户手工绘制的区域，平台内置 VRVP 必须隐藏且永不取值。

## 文件命名约定（必须遵守）
* `<tf>`：`1d` / `4h` / `1h` / `15m`
* 例：`tradingview_btc_1d.png` / `tradingview_btc_1d.json`
* 🟥 **四档缺一 = 六源未齐 = 硬停**（见 `data_sources/required_sources.md` 数据缺失规则）。

## 数据源
TradingView · BTCUSDT · 交易所 Binance（与日内极值/手绘线口径一致）

## 通道约束
* 主通道：本机持久化登录态 + `tools/browser_capture/capture_tv.js`，保留用户手绘线与布局。
* 平台内置 VRVP：检测到可见时只允许一次控制内隐藏并复核；隐藏失败或状态未知不阻断四周期结构截图，但该轮成交量分布维度强制 `insufficient`。
* 禁止：读取平台内置 VRVP、自动 POC/VAH/VAL/HVN/LVN 数值，或用 Coinglass 清算图替代手绘区域。
* 每轮必须把四周期平台状态写入本轮 hash-bound `tradingview_profile_state.json` sidecar。只有当前轮 sidecar 完整、有效且与证据绑定时，才允许采用其中状态；sidecar 缺失、无效、写入失败或绑定不明时，统一按 `platform_indicator_state=unknown` 与 `status=insufficient` 处理，不得接纳上一轮文件。

---

## 采集执行流

1. 生成四档截图（日/4H/1H/15m），每档保留：
   * 用户手工绘制的 VRVP／成交量分布区域（若本轮确实可读）
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
     "volume_profile": {
       "source_mode": "user_drawn_manual_only",
       "status": "readable | insufficient",
       "platform_indicator_state": "hidden | absent | visible | unknown",
       "platform_vrvp_used": false,
       "automated_values_used": false,
       "zones": [
         {"lower_bound": <number>, "upper_bound": <number>, "timeframe": "1d | 4h | 1h | 15m", "role": "value_area | poc_zone | hvn_zone | lvn_zone"}
       ],
       "reason": "<insufficient时必填>"
     },
     "channel_position": "upper_edge | mid | lower_edge | none",
     "volume_price": "放量上涨 | 放量下跌 | 缩量震荡 | 背离 | none",
     "level_conclusion": "中性 | 利多 | 利空"
   }
   ```
3. 写 manifest 主条目（指向日线为主，其余作 files 列表附加）。

### 各档用途分流
* **日线 1d** → 盘面日线级别结论 + 趋势确认（大方向）
* **4H / 1H** → 盘面小时级别结论 + 支撑压力 + SMA20/斐波（结构精度）
* **15m** → Maker 入场位置最终把关：通道边缘挂单（≠追价）+ 可读的用户手绘区域避让；手绘区域不可读时不得补位置。

---

## 盘面(30)取数对照（reasoning phase 的 chart scoring）

| 盘面指标 | 满分 | 取自字段 | 主用档 |
|---|---|---|---|
| 支撑/压力区间接近度 | 10 | support/resistance + 现价 | 4H/1H |
| 多空流动性掠夺 | 10 | structure（sweep/扫损/诱多空） | 1H/15m |
| SMA20 突破/回踩 | 5 | sma20_relation | 1H |
| 量价关系 | 3 | volume_price | 日线/1H |
| 斐波/趋势线接近度 | 2 | fib_or_trendline | 4H/1H |

---

## 失败处理
* 缺任一档（日/4H/1H/15m）→ `valid:false` + `missing_timeframes:[...]` → **六源未齐硬停**，不评分。
* 结构/趋势判断不确定 → 对应字段 `uncertain` / `none`，不允许猜测。
* 手绘成交量分布可读 → `status=readable`、平台状态仅可 `hidden/absent`、至少一个上下界明确且角色为 `value_area/poc_zone/hvn_zone/lvn_zone` 的 profile 专属区间。普通手绘支撑/压力线只能进入 `chart_basis`，不得据此把 profile 标为 readable。
* 手绘成交量分布不可读、平台仍可见或状态未知 → `status=insufficient`、`zones=[]`、`reason` 必填、`chart.liquidity_hunt=0`；禁止输出 POC/VAH/VAL/HVN/LVN 数值和概率落点。四周期结构仍有效，不因此整源硬停。
* `absent` 只允许在采集器可靠确认对应平台控件确实不存在时使用；选择器漂移、标题不识别、页面未稳定或任何“不知道”都必须写 `unknown`，禁止 fail-open 为 `absent`。
* profile 为 `insufficient` 时，Coinglass 清算热力图必须保持 `neutral`，不得替代手绘区域、生成概率落点、加盘面分或翻方向。

---

## 注意
* 枚举值必须用规定值，禁止自由文本。
* **核心读数取用户手绘线/手绘成交量分布区域**：日内支撑压力以用户图上手绘线为准，不臆造价位。所有价格保持阿拉伯数字，区域用上下界表达，不压成平台自动单点。
* TradingView 头部 O/H/L/C 是光标悬停那根（可能别的日期），非现价；日内高低必扫整段 K 线 wick、跨源核验。
* 四档若出现冲突方向，全部记录；盘口与盘面按各自账户优先级独立综合，Exocharts 足迹只确认或削弱盘口强度，不覆盖 TradingView 结构。
