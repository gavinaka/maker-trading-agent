# vNext 数据时效与完整性规则

## 核心原则

- 每个报告只认当前 `date + slot + run_id + capture_id` 绑定的不可变 evidence snapshot。
- 过期、缺失、无效、跨 run、跨 slot、哈希不符或无法回源核验的数据一律等同于缺失。
- 六源必须在同一轮 evidence stage 全部通过；禁止使用旧截图、历史 JSON、前一 slot、外部报告或部分有效源拼接当前报告。

## 六源时效语义

- **BlockBeats**：本轮采集必须覆盖 capture time 前 12 小时内页面可见的全部“重要快讯”，并按当前优先级确定 top 3。
- **Coinglass**：本轮完整 BTC 1H 四面板截图与结构化记录必须绑定同一 capture 和同一价格 pivot。
- **Exocharts**：本轮必须重新确认 `Bybit BTCUSD / D / Tick 120 / Bid-Ask Profile / Imbalance / Candle None / FPBS / vWap` 后截图；旧登录态可以复用，旧图与旧控件结论不能复用。
- **FedWatch 逻辑插槽**：每个 slot 必须先重新导航 CME 官方页面。CME 真实概率工具
  渲染成功时，只认本轮真实截图且禁止调用 Kalshi；`Data as of ... CT` 只原样展示，
  不得与主机时钟比较后判未来、陈旧或硬停。只有同 run 的 sealed CME closed-code
  技术故障可触发一次 Kalshi `KXFEDDECISION` Plan C；其时效由本轮 public API
  retrieval、同事件 current 与 1d/1w/30d 合格锚点、raw/normalized/provenance
  全部进入不可变快照共同证明。旧 API 响应或缺失锚点不得回填。
- **Farside**：本轮重新打开并截图；业务行允许是最近完整美股交易日，但 `captured_at` 必须属于本轮。全横线占位行不是 0 流量，必须跳过。
- **TradingView**：本轮 1D/4H/1H/15m 四档截图全部存在并绑定同一 capture；SMA20、结构与用户手绘成交量分布可读性必须按本轮重判。

## Evidence stage 结果

1. controller 只验证当前 run 的 capture manifest、不可变 snapshot、文件记录、时间、身份与哈希。
2. 六源任一缺失、过期、无效、内容异常或跨边界，整个 evidence stage 失败；不得生成部分报告，也不得把对应字段写成“待补充”后继续。
3. 失败只允许使用当前 evidence stage 合同规定的同输入局部纠正预算；预算耗尽进入 `needs_review`。
4. Evidence 失败不得启动 reasoning、decision、report 或 delivery，也不得为修报告而重跑整轮。
5. 后续阶段失败不得触发重采；每阶段只纠正自身制品。

## 时间与异常

- 所有时间戳使用带时区的 ISO 8601；`captured_at` 是本轮采集完成时刻。
- 时效由 controller 在读取时根据密封记录计算，禁止在 manifest 中缓存可漂移的 `freshness_minutes`。
- 网站无法访问或 access block 只有在被 CME collector 归入合同闭集并密封后才可进入
  Plan C；页面改版、selector/schema drift、空值、语义不明、概率/合计不自洽、会议
  日期冲突或任一 Plan C 完整性失败仍标记该源 `valid:false`，按 evidence stage 失败。
- 禁止为了保持输出完整而降级时效、伪造最新状态、无限重试或切换到未纳入 control-plane hash 的临时采集路径。
