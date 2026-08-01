# FOMC 利率预期数据规则

## 单一逻辑插槽

工作流内部兼容名为 `FedWatch`，用途仅为美联储利率预期分布、边际重定价与 FOMC
事件窗口。它不能直接决定交易方向、下单动作、orderflow/chart 分或 Maker 置信度调整。

物理 provider 必须按以下优先级机械选择：

1. `cme_fedwatch_ui`：CME 官方 FedWatch 页面，唯一 primary；
2. `kalshi_public_market_data_api`：仅在 CME 网站出现已密封、闭合集技术故障时启用的
   A5-R1e Plan C。

机器可读真相源为 `rate_expectation_provider_contract.json`；本文件不扩展 provider、
fallback code 或概率算法。

## CME primary

- 每个 slot 重新导航、等待真实 `Target Rate Probabilities` 渲染并截取 `fedwatch.png`。
- 页面 `Data as of ... CT` 可转录，但不得与主机时钟比较后判未来或过期。
- CME 有效时禁止请求、读取或混入 Kalshi。

## Plan C

- 只接受 `KXFEDDECISION` public API；不使用付费 CME API、Federal Reserve 概率替代、
  媒体、搜索摘要、转载或模型估算。
- 只允许闭合的 CME technical failure 触发一次；语义不确定、schema drift、概率冲突、
  会议日期不明或“另一组数据更合意”均不得触发。
- 当前与历史均使用 yes bid/ask midpoint + bounded simplex，并显式保留
  `other_unlisted`；`>25bp` 不得改写为 50bp。
- Plan C 是独立事件合约市场推断，非 CME Fed Funds futures / FedWatch 方法等价。
- Plan C evidence 可供完整 shadow 流程使用，但 sample 永远先记 `observation`，不增加
  clean streak 或生产切换资格。

## 必需业务字段

进入 reasoning 的唯一业务 metrics 为：

- `data_as_of`
- `next_fomc_date`
- `current_probabilities`
- `change_1d`
- `change_1w`
- `change_1m`

概率键必须符合当前 scoring contract。Plan C 的四个分布/变化 map 必须包含相同键，
其中包括 `cut_gt_25bp`、`cut_25bp`、`hold`、`hike_25bp`、`hike_gt_25bp` 与
`other_unlisted`；current 合计 100%，每个 delta 窗口净和为 0。

## 完整性原则

- 原始响应、normalized artifact、CME attempt 与 provider provenance 必须属于同一
  capture run 并全部 hash/bytes 绑定。
- 任何字段缺失、跨 run、条款变化、未知 bucket、历史 anchor 缺失或 normalized 无法
  从 raw 独立重放，都按源无效并 hard stop。
- 宁可缺失，不得补值、猜值、条件归一化冒充无条件概率或隐藏来源差异。
