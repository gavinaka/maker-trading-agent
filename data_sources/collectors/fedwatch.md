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
     "liquidity_bias": "利多 | 利空 | 中性 | 中性偏多 | 中性偏空"
   }
   ```

---

## liquidity_bias 推导规则

* `cut_*` 占比 ≥ 60% → **利多**（流动性预期改善）
* `cut_*` 占比 ≥ 40% → **中性偏多**
* `hold` 占比 ≥ 60% → **中性**
* `hike_*` 占比 ≥ 40% → **中性偏空**
* `hike_*` 占比 ≥ 60% → **利空**

枚举值必须使用 `constitution/terminology.md` 基本面判断标准库。

---

## 失败处理

* 页面图表未渲染完成（probabilities 全为 0）→ 等 15s 重试 1 次
* CME 改版导致选择器失效 → 标 `valid:false, error:"页面结构变化"`，触发用户介入

---

## 注意

* 变化频率低：当日采集 1 次即可
* FOMC 公布日 / SEP 发布日：必须当日重采
* 不允许用前日数据替代
