# Exocharts Collector SOP

## 目标
采集 BTC / ETH 永续合约的 CVD、价格行为、结构 → `inbox/<YYYY-MM-DD>/exocharts_<symbol>_<tf>.{png,json}`

## 文件命名约定（必须遵守）
* `<symbol>`：小写，`btc` 或 `eth`（文件名层级；JSON 内 symbol 字段仍写 `BTCUSDT`）
* `<tf>`：`1h` / `4h` / `1d` / `15m`
* 例：`exocharts_btc_1h.png` / `exocharts_btc_1h.json`

## 数据源
https://exocharts.com/web/

## 通道约束
* 主通道：**A**（Chrome MCP）—— Exocharts 是 SPA，有登录墙，WebFetch 不可用
* 兜底：**C**（用户截图投递）
* 禁止：**B**

---

## 通道 A 执行流

1. `tabs_context_mcp` → 复用本会话 tab
2. `navigate` → `https://exocharts.com/web/`
3. 若未登录，停止并写 `valid:false, error:"未登录"`（不自动登录，遵守 `user_privacy`）
4. 对每个标的 × 周期组合采集：
   * BTCUSDT 1h / BTCUSDT 4h / BTCUSDT 1d
   * ETHUSDT 1h（可选）
5. 每个组合：
   * 切换图表到对应 symbol + timeframe
   * 等待 CVD 指标加载完成（`read_page` 确认 CVD 面板可见）
   * 截图保存为 `exocharts_<symbol>_<tf>.png`
   * 抽取最近若干根 K 线的关键值，写 `exocharts_<symbol>_<tf>.json`：
     ```json
     {
       "symbol": "BTCUSDT",
       "timeframe": "1h",
       "captured_at": "<ISO>",
       "last_close": <number>,
       "cvd_direction": "up | down | sideways",
       "price_direction": "up | down | sideways",
       "recent_structure": "higher_high | lower_low | range | breakout_up | breakout_down",
       "key_levels": {
         "support": [<number>, ...],
         "resistance": [<number>, ...]
       }
     }
     ```
6. 写入 manifest 主条目（指向 BTCUSDT 1h 为主，其余作 files 列表附加）

---

## 通道 C 执行流

用户截图 + 手填 JSON → 放入 inbox → 通知

---

## 失败处理

* 登录墙 → 用户介入
* SPA 加载超时（> 60s）→ 重试 1 次 → 仍失败标 `valid:false`
* 结构判断不确定 → `recent_structure: "uncertain"`，不允许猜测

---

## 注意

* `cvd_direction` 等枚举值必须使用规定值，禁止自由文本
* 若 1h / 4h / 1d 出现冲突方向，全部记录到 raw_summary，由 scoring_agent 综合判断
