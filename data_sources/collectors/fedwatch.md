# CME FedWatch Collector SOP

## 目标
采集美联储利率预期分布 → `inbox/<YYYY-MM-DD>/fedwatch.{png,json}`

## 数据源
https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html

## 通道约束
* 主通道：**A**（Chrome MCP）
* 备选：**B**（CME 有部分公开 JSON 端点）
* 兜底：**C**

---

## 通道 A 执行流

1. `tabs_context_mcp` → 拿 tab
2. `navigate` → CME FedWatch 页面
3. 等待 JavaScript 计算完成（图表渲染需 5-10s）
4. 截图 → `fedwatch.png`
5. 抽取下次 FOMC 利率预期表 → `fedwatch.json`：
   ```json
   {
     "captured_at": "<ISO>",
     "next_fomc_date": "<YYYY-MM-DD>",
     "current_target_rate_bp": <number>,
     "probabilities": {
       "cut_50bp": <pct>,
       "cut_25bp": <pct>,
       "hold":     <pct>,
       "hike_25bp": <pct>,
       "hike_50bp": <pct>
     },
     "dominant_outcome": "cut_25bp | hold | hike_25bp | ...",
     "liquidity_bias": "宽松预期较强 | 宽松预期温和 | 中性 | 紧缩预期温和 | 紧缩预期较强"
   }
   ```

---

## liquidity_bias 推导规则（仅宏观预期背景）

`liquidity_bias` 是为兼容既有采集结构保留的字段。它只描述利率路径所隐含的
宏观流动性预期，**不是 BTC 价格方向、交易方向或下单信号**：

* `cut_*` 占比 ≥ 60% → **宽松预期较强**
* `cut_*` 占比 ≥ 40% → **宽松预期温和**
* `hold` 占比 ≥ 60% → **中性**
* `hike_*` 占比 ≥ 40% → **紧缩预期温和**
* `hike_*` 占比 ≥ 60% → **紧缩预期较强**

判断时必须同时保留两个维度：

1. 当前概率分布是“存量水平”；
2. `1d`、`1w`、`1m` 变化是“边际重定价”。

不同窗口相互冲突时必须保留冲突，不得选取单一窗口强行统一结论。FedWatch
只能提供宏观背景和 FOMC 事件风险窗口；不得直接生成 Maker 或主账户方向，
不得写入订单流分、盘面分，也不得推翻其他数据源已经形成的方向判断。

---

## 失败处理

* 页面图表未渲染完成（probabilities 全为 0）→ 等 15s 重试 1 次
* 重试仍为浏览器错误页、空白页或 iframe 未渲染 → 启用固定权威网络回退：
  1. 优先检索 CME Group 官方 FedWatch 页面/API/官方发布；
  2. 其次检索 Federal Reserve 官方资料；
  3. 再次使用明确引用 CME FedWatch 且标注数据时点的主流金融数据源；
  4. 关键概率至少双源交叉核验；
  5. 写入 `fedwatch.json`，包含来源 URL、采集时间、下次 FOMC 日期、概率分布、1日/1周/1月变化、`capture_mode:"authoritative_web_fallback"`、`screenshot_valid:false` 和失败原因。
* CME 改版导致选择器失效但权威回退数据完整 → 源有效；权威数据也不可得 → 标 `valid:false` 并硬停。

---

## 注意

* 变化频率低：当日采集 1 次即可
* FOMC 公布日 / SEP 发布日：必须当日重采
* 不允许用前日数据替代
* 不允许把搜索摘要、无日期转载或模型估算当作权威回退数据
