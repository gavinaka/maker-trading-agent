# FOMC 利率预期 Collector SOP（CME primary + A5-R1e Plan C）

## 目标与身份

内部兼容 source key 继续使用 `FedWatch`，17 单元 reasoning micro-DAG 中仍只有
`source.fedwatch` 一项。这个 key 表示“FOMC 利率预期逻辑插槽”，不保证物理 provider
永远是 CME。真实 provider、方法类别和 fallback lineage 必须由
`data_sources/rate_expectation_provider_contract.json` 与本轮哈希绑定 provenance 决定。

Plan C 只是 **CME 网站技术不可用时的备用方案**，不是并行数据源、交叉挑选器或
第七源。CME 页面有效时，Kalshi 调用次数必须为 0。

## Provider 顺序

### Primary：CME FedWatch 官方 UI

1. 每个 slot 重新 `page.goto` CME 官方页面。
2. 等待真实 iframe 与 `Target Rate Probabilities` 完整渲染；固定 sleep 不能替代就绪条件。
3. 截取真实工具为 `fedwatch.png`。
4. 写入本轮 `cme_fedwatch_result.json` 与 `rate_expectation_provenance.json`。
5. 选择结果必须为 `selection_mode=cme_primary`、`provider_id=cme_fedwatch_ui`。

页面显示的 `Data as of ... CT` 只作原样转录。不得把它与主机 UTC、北京时间、文件
mtime 比较后判为未来、陈旧、触发重采或硬停。本时段时效权威仍是本轮重新导航、
真实工具渲染成功以及截图进入当前不可变快照。

### Plan C：Kalshi public market-data API

仅当 CME attempt 已写入同一 capture run 的密封失败记录，且 `defect_code` 属于下列
闭集时，状态机才可调用 Kalshi **一次**：

- `cme_tool_content_load_error`
- `cme_probability_tool_unrendered`
- `cme_navigation_transport_failure`
- `cme_access_blocked`

Plan C 固定为：

- `provider_id=kalshi_public_market_data_api`
- `series_ticker=KXFEDDECISION`
- public、无认证 market-data API；不得自动换到其它 series、媒体、搜索摘要或模型估算
- `method_class=independent_event_contract_market`
- `method_equivalence=non_equivalent`
- `sample_source_class=kalshi_plan_c_observation`

必须密封以下制品：

- `cme_fedwatch_result.json`：eligible CME 技术失败及本轮身份
- `kalshi_feddecision_raw.json`：原始 series / event / market / 60 分钟 candle 响应及条款哈希
- `fedwatch.json`：authority-owned Decimal normalizer 的确定性结果
- `rate_expectation_provenance.json`：selected provider、fallback code 与全部制品 lineage

Kalshi 是结构化 API 证据，Plan C **不伪造 CME 截图或本地“假网页”**。reasoning 中仍只
生成一份 source=`FedWatch` observation，但 kind 必须是 `structured_observation` 并绑定
`fedwatch.json`；CME primary 仍使用真实 PNG 的 `visual_judgment`。

## Kalshi 概率口径

当前值与 1日 / 1周 / 1月（固定 30 日）历史值必须使用完全相同的口径：

1. 每个事件桶以同一时点的 `yes_bid` / `yes_ask` 为区间证据；
2. 点估计初值固定为 midpoint，`last_price` 只可作审计，不能替代主口径；
3. 使用 `kalshi_bounded_simplex_other_unlisted_v1` 在 bid/ask 边界内确定性投影；
4. 必须保留 `other_unlisted`，五个 listed bucket 与它合计为 100%；
5. `cut_gt_25bp` / `hike_gt_25bp` 必须保留聚合尾桶，严禁改写为 50bp；
6. 历史窗口使用同一 event、同一 market mapping、同一 midpoint 与 normalizer；缺任一
   bucket、bid/ask、合格 candle 或锚点即 hard stop，不得以当前值回填或把缺失当 0；
7. `change_1d|change_1w|change_1m` 只能由 current 减对应历史分布机械计算。

Kalshi event contract 只保证最多一个 listed bucket 结算 Yes，不能假定五桶穷尽所有
可能结果。因此禁止把五桶简单除以其总和后称作无条件 FOMC 概率。

## 绝对禁止 fallback 的情形

- CME 已有效、但 Kalshi 数值不同或更符合交易叙事；
- CME 概率可见但合计、会议日期、档位含义或转录不一致；
- 页面结构变化、selector drift 或无法归入闭合集的错误；
- CME failure record 缺失、hash/run identity 不符或 code 不在 allowlist；
- 旧 Kalshi 文件存在但本轮未合法触发；
- CME primary 已成功后又调用 Kalshi。

这些情形必须 hard stop；不得从两组数据中择优。

## 业务边界与报告

- 该插槽只定义宏观概率环境与 FOMC 事件窗口；不直接决定 Main/Maker 方向，不计入
  orderflow/chart 分，不得成为 conviction adjustment，也不得单变量翻转计划。
- CME 报告显示 `FedWatch（CME官方页面）`。
- Plan C 报告显示 `FOMC利率概率（Kalshi KXFEDDECISION 备用观察源）`，并明确
  “独立事件合约市场、非 CME 方法等价、仅作宏观背景、本样本 observation-only”。
- Plan C 即使五阶段一次通过、零 failure/retry/orphan，也不得计入 current clean、
  trailing clean 或 production-switch 资格。

## 失败与停止

任一 provider 的结构、身份、条款 SHA、市场映射、bid/ask、历史窗口、哈希绑定或
provenance 验证失败，整个 evidence stage 失败。禁止输出“待补充”后继续，禁止复用
昨日/上一 slot，禁止无限重试，禁止扩展到未批准的 Plan B。
