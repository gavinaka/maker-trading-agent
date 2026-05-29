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

* 资金费率方向阈值：
  * `> +0.01%` → positive
  * `< -0.01%` → negative
  * 区间内 → neutral
* OI 24h 变化阈值：
  * `> +3%` → up
  * `< -3%` → down
  * 区间内 → sideways
