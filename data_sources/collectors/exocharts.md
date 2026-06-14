# Exocharts Collector SOP

> 🟥 **源角色（2026-06-14 用户校准·宪法级）**：exocharts **不是盘口主源**。盘口四变量（CVD/价格/OI/资金费率）解读核心 = **coinglass 截图**。exocharts 仅作 **印证 + 更细颗粒度（footprint 足迹）的数据参照**，确保 coinglass 判断准确。与 coinglass 冲突时以 coinglass 为准复核，exocharts 不单方覆盖。

## 目标
采集 BTC / ETH 永续合约的 footprint 足迹（印证·细颗粒）+ CVD/价格/结构（交叉核对，核心读数取 coinglass）→ `inbox/<YYYY-MM-DD>/exocharts_<symbol>_<tf>.{png,json}`

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
       },
       "footprint_signals": {
         "absorption": "buy_absorbed | sell_absorbed | none",
         "imbalance": "stacked_bid | stacked_ask | scattered | none",
         "poc": { "shift": "up | down | flat", "price_vs_poc": "far | near" }
       }
     }
     ```

   ### footprint_signals 采集规则（2026-06-14 迭代 · exocharts 微观订单流）
   * **仅当 footprint 足迹档位可见时填写**（exocharts 切到 footprint/订单流视图、能看到逐价位主动买卖 delta）。看不到档位 → **整块写 `"footprint_signals": null`**，绝不臆造。
   * `absorption`：某价位大额主动买但价不涨/反跌=`buy_absorbed`（隐性派发）；大额主动卖但价不跌/反涨=`sell_absorbed`（隐性吸筹）；无明显吸收=`none`。
   * `imbalance`：对角线买:卖 ≥3:1 连续 ≥3 档=`stacked_bid`；卖:买 ≥3:1 连续 ≥3 档=`stacked_ask`；失衡零散无堆叠=`scattered`；无失衡=`none`。
   * `poc`：成交量最大价位相对前段上移/下移/持平=`shift`；现价远离 POC=`far`，贴近=`near`。
   * 这三项是 footprint_agent 的**印证因子**（只调强度、不翻向），权威逻辑见 `scoring/orderflow_methodology.md` 第八节。
6. 写入 manifest 主条目（指向 BTCUSDT 1h 为主，其余作 files 列表附加）

---

## 通道 C 执行流

用户截图 + 手填 JSON → 放入 inbox → 通知

---

## 失败处理

* 登录墙 → 用户介入
* SPA 加载超时（> 60s）→ 重试 1 次 → 仍失败标 `valid:false`
* 结构判断不确定 → `recent_structure: "uncertain"`，不允许猜测
* **footprint 档位不可见 / 不确定 → `footprint_signals: null`，禁止猜测吸收/失衡/POC**

---

## 注意

* `cvd_direction` / `footprint_signals.*` 等枚举值必须使用规定值，禁止自由文本
* 若 1h / 4h / 1d 出现冲突方向，全部记录到 raw_summary，由 scoring_agent 综合判断
* **足迹信号是印证因子（只调强度、不翻向），缺失时降级不阻塞**——无 footprint 视图时整块置 null，按四维正常评分（见 `scoring/orderflow_methodology.md` 第八节）
