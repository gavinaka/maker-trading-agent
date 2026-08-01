# Coinglass Collector SOP

## 目标
在同一张 BTC 1H 四面板中采集价格 / CVD / 持仓量（OI）/ 资金费率，并把它们绑定到同一价格 pivot。

## 数据源（图谱 II 节实际 URL）
* 主页：https://www.coinglass.com/tv/zh/Bybit_BTCUSDT（CVD + 资金费率 + 持仓量合一图）
* 资金费率明细：https://www.coinglass.com/FundingRate（备用，逐交易所对比）
* 持仓量明细：https://www.coinglass.com/BitcoinOpenInterest（备用）

## 通道约束
* vNext 证据通道：只认当次 `capture_coinglass.js` 产生的完整四面板截图及其当次 run 绑定记录。
* 资金费率或 OI 分页只能做诊断性交叉核对，不能替代同一 pivot 四面板。
* 无截图 API、搜索摘要、旧 JSON 或其它时段记录不得标记为本轮有效 Coinglass 证据。

---

## 通道 A 执行流

### Step 0：主图（必须，价格 + 三指标合一）
1. `navigate` → `https://www.coinglass.com/tv/zh/Bybit_BTCUSDT`
2. 等待 K 线 + CVD + 资金费率 + 持仓量四面板渲染（~10s）
3. 截图 → `coinglass_main_btc.png`
4. 从主图同时读取价格、CVD、OI 和资金费率，写同一 capture/pivot 绑定记录。
5. 主图未完整渲染、周期不是 1H、symbol 不是 Bybit BTCUSDT 或任一面板不可读，本源无效；分页不得把它降级修成 valid。

### Step 1：资金费率（可选诊断交叉核对）
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

### Step 2：持仓量（OI，可选诊断交叉核对）
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

### Step 3：CVD 分页（可选诊断交叉核对）
1. `navigate` → `https://www.coinglass.com/today` 或 BTC 详情页 → CVD 板块
2. 截图 → `coinglass_cvd.png`
3. 抽取 CVD 方向 → `coinglass_cvd.json`

---

## 无截图 API 边界

* 免费 API 端点只允许用于人工排障，不得进入 vNext 证据快照。
* 无同一 1H pivot 四面板 PNG 时必须 `valid:false`，不存在“无截图但 valid”旁路。

---

## 失败处理

* Cloudflare 拦截 → 标 `valid:false, error:"Cloudflare"`
* API 限流 → 等待 30s 重试 1 次
* 数据为 0 / null → 视同失败

---

## 注意

### 4 维读取口径（2026-05-31 修正）
* **周期固定 1H**；主图 `coinglass_main_btc` 四面板（价格 / CVD / 资金费率 / OI）一并读。
* **唯一锚点先来自 1H 价格**：下跌主导腿选启动该腿的 1H 摆动高点，上涨主导腿选启动该腿的 1H 摆动低点。只有价格趋势线被决定性突破且结构翻转才重置锚点；腿内小反抽/回撤不重置锚点。
* CVD、价格、OI 和资金费率全部从这一个价格时间锚读到最新值，禁止各维各取自己的局部高/低点，也禁止用末端 2–3 根微动重置 pivot。
* 不用「24h 变化%」、「近 N 根累积」或用户手绘线代替这一机械时间锚。
* **资金费率双轨**（趋势 + 正负，2026-05-31 据 5 样本校验改）：除趋势外再读零轴水平 `positive(>+0.01%) / negative(<-0.01%) / near_zero`，作为 C01–C81 第四维与强弱修正；不得单变量翻向。
  * 呈现：「资金费率{上升/横盘/下降}（为正值/为负值/低于正常值）」。
* 详细合成、反证与 C01–C81 规则见当前 reasoning phase 内的 `scoring/orderflow_methodology.md` 和 `scoring/scoring_contract.json`。
