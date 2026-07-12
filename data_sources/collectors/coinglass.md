# Coinglass Collector SOP

## 目标
采集资金费率 / 持仓量（OI）/ CVD 辅助 → `inbox/<YYYY-MM-DD>/coinglass_<metric>.{png,json}`

## 数据源（图谱 II 节实际 URL）
* 主页：https://www.coinglass.com/tv/zh/Bybit_BTCUSDT（CVD + 资金费率 + 持仓量合一图）
* 资金费率明细：https://www.coinglass.com/FundingRate（备用，逐交易所对比）
* 持仓量明细：https://www.coinglass.com/BitcoinOpenInterest（备用）

## 通道约束
* 主通道：**A**（Chrome MCP）
* 备选：**B**（部分免费 API 端点可用，但优先 A 以确保数据一致性）
* 兜底：**C**

---

## 通道 A 执行流

### Step 0：主图（推荐，三指标合一）
1. `navigate` → `https://www.coinglass.com/tv/zh/Bybit_BTCUSDT`
2. 等待 K 线 + CVD + 资金费率 + 持仓量四面板渲染（~10s）
3. 截图 → `coinglass_main_btc.png`
4. 从主图直接读取三指标，写 `coinglass_main_btc.json`（合一记录，三 metric 同时戳）
5. 若主图采集成功 → Step 1/2/3 可跳过；失败再降级到分页

### Step 1：资金费率（备用，逐交易所对比）
1. `navigate` → `https://www.coinglass.com/FundingRate`
2. 等待表格加载（`read_page` 确认 BTC 行可见）
3. 截图 → `coinglass_funding.png`
4. 抽取关键值 → `coinglass_funding.json`：
   ```json
   {
     "captured_at": "<ISO>",
     "btc": {
       "binance_funding_pct": <number>,
       "okx_funding_pct": <number>,
       "weighted_avg_pct": <number>,
       "direction": "positive | negative | neutral"
     },
     "eth": { ... }
   }
   ```

### Step 2：持仓量（OI）
1. `navigate` → `https://www.coinglass.com/BitcoinOpenInterest`
2. 截图 → `coinglass_oi.png`
3. 抽取 → `coinglass_oi.json`：
   ```json
   {
     "captured_at": "<ISO>",
     "btc_total_oi_usd": <number>,
     "change_24h_pct": <number>,
     "trend": "up | down | sideways"
   }
   ```

### Step 3：CVD 辅助（合约市场）
1. `navigate` → `https://www.coinglass.com/today` 或 BTC 详情页 → CVD 板块
2. 截图 → `coinglass_cvd.png`
3. 抽取 CVD 方向 → `coinglass_cvd.json`

---

## 通道 B 执行流（备选）

* 已知端点：`https://fapi.coinglass.com/api/...`（免费层级，无 key 也可）
* 仅在通道 A 失败时启用
* 不适用于截图要求（无 png 文件 → 标记 `valid: true, note: "B通道无截图"`）
* 优先级：永远低于 A

---

## 失败处理

* Cloudflare 拦截 → 标 `valid:false, error:"Cloudflare"`
* API 限流 → 等待 30s 重试 1 次
* 数据为 0 / null → 视同失败

---

## 注意

### 4 维读取口径（2026-05-31 修正）
* **周期固定 1H**；主图 `coinglass_main_btc` 四面板（价格 / CVD / 资金费率 / OI）一并读。
* **趋势(上升/横盘/下降)适用全部 4 维（CVD/价格/OI/资金费率）**：起始点取该面板**最近一个阶段性高点或低点**，连线到最新值按斜率判 `up | down | sideways`。
  * 不再用「24h 变化%」或「近 N 根累积」绝对阈值；趋势方向判断，不要求精确数值。
  * 起始点优先用截图上用户手绘的趋势线。
* **资金费率双轨**（趋势 + 正负，2026-05-31 据 5 样本校验改）：除趋势外再读零轴水平 `positive(>+0.01%) / negative(<-0.01%) / near_zero`，作为 C01–C81 第四维与强弱修正；不得单变量翻向。
  * 呈现：「资金费率{上升/横盘/下降}（为正值/为负值/低于正常值）」。
* 详细规则见 `agents/footprint_agent.md` §「统一读取法」。
