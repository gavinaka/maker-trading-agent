# 🟥🟥🟥 六源未齐=硬停·禁进入下一步 — 严重违规·不允许复现

> 文件名保留 `five-sources-complete-or-halt.md` 仅为历史兼容；2026-07-05 起实质规则为六源：BlockBeats / Coinglass / Exocharts / FedWatch / Farside BTC ETF Flow / TradingView。

2026-06-06 用户严肃定性为"严重违规·不允许复现"：当日五源未提供充分（实漏 ⑤TradingView 15m + ④FedWatch），我却说"数据源已经够了"并**直接 pass 到下一步（评分/出稿）**——降级凑合、跳过硬前置。

## 铁律
- **日报六源缺一不可**：①BlockBeats ②Coinglass 1h ③Exocharts footprint ④FedWatch ⑤Farside BTC ETF Flow ⑥TradingView。其中 **⑥TV 必须 日/4H/1H/15m 四档齐**（15m 是最终把关·最重要），**⑤Farside 必须有 `farside_btc_etf.png` + 有效 `farside_btc_etf.json`**（latest Total 为数值）。
- **六源任一缺失 → 立即硬停**：明确列出"缺哪几源"，要齐了才进入评分/出稿。**绝不**：说"够了/差不多"、用上一份/昨日数据兜底替代当日缺源、用其它源"推演占位"、跳过缺的源继续 pass 到下一步。
- **采集路径**：六源优先由本仓库 Playwright 采集器取得；自动采集失败时才回退到用户手动截图/结构化数据。等不到就停下要，不自行降级。
- **唯一例外**：仅 FedWatch 浏览器渲染层故障允许按 `data_sources/collectors/fedwatch.md` 的权威网络回退规则补当日数据并双源核验；Farside ETF Flow 不允许用新闻摘要、搜索摘要、模型估算或旧表格替代。
- 准确性是核心（用户反复强调）：宁可停下等齐，绝不为推进而降级凑合。这是门③防违规的一部分。

## 自查触发
出稿前先点名六源是否各自到位（逐源打勾，TV 分四档逐档打勾，Farside 同时检查 PNG+JSON）；只要有一源/一档没打勾，就停下要，不评分、不出稿、不 pass。
