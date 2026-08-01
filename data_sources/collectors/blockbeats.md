# BlockBeats Collector SOP

## 目标

实时采集抓取前 12 小时内的 BlockBeats「重要快讯」，保留截图、12 小时候选池与结构化 top3，供日报基本面独立判断。

## 数据源

https://www.theblockbeats.info/newsflash

## 唯一路径（硬性）

* 统一入口：`node tools/browser_capture/capture_all.js`
* 子采集器：`tools/browser_capture/capture_blockbeats.js`
* 禁止：Chrome MCP、WebFetch/搜索摘要、历史快讯、AI 生成内容
* 依据：BlockBeats 与其余五个正式源走同一自动采集主路径，同时保留“必须截图”要求。

## 执行流

1. `capture_all.js` 首项调用 `capture_blockbeats.js`。
2. Playwright/Chrome 打开 BlockBeats 快讯页。
3. 关闭可能遮挡筛选项的通知提示，勾选「重要快讯」，并确认复选框保持选中。
4. 保存：
   * `data_sources/inbox/<YYYY-MM-DD>/blockbeats.png`
   * `data_sources/inbox/<YYYY-MM-DD>/blockbeats.json`
5. JSON 写入 `"important_only": true`、`"capture_window_hours": 12`、`"window_covered": true`、`candidate_rows`、`selected_rows` 和兼容字段 `rows`。
6. `candidate_rows` 保留抓取前 12 小时内所有可加载重要快讯；`selected_rows`/`rows` 只保留按基本面影响优先级筛出的 3 个独立事件。已确认属于同一国家/地区、同一 `year-month` 报告期的 PPI 年率、月率及含明确实际值的后续解读稿只占 1 个 Top3 位置；`六月/6月`等月份写法必须归一。标题按 `period-PPI` 局部 span 绑定国家与报告期，右侧影响对象不能充当发布国家，已被其他显式宾语消费的 publisher cue 不能借给 PPI。正文只证明已发布实际值或提供反证；候选按`current / next_period / other_period / unrelated`保存 referent，再校验前置模态、有效强发布 cue、后置角色/比较值、来源与更正。其他指标、预测、前值、同名实体、未解析相对年份或跨身份信息不得借数或模糊合并。最高优先级原文作为代表，其余原始成员保留在代表行的 `event_family.members` 中。
   * 排序先按 `analysis_priority.priority_bucket/bucket_rank`，再按 `score`，最后按时间。
   * `analysis_priority` 必须保留兼容字段 `tier/category/score/reasons`，并写入 `priority_bucket/bucket_rank/directness/directness_label`。
   * Meme、个人投资复盘、AI/存储/芯片等非 BTC 叙事只能留在候选池；无 BTC/ETF/宏观/监管直接语境时，不得挤占 selected top3。
   * 地缘标题先拆局部谓词并标记 `ASSERTED / NEGATED / CONDITIONAL / PRODUCT / EFFECT`；只有已发生的主行动可触发 Tier1。正文只可认证或以同主体、同目标反证；否认伤亡/武器/法律属性不得否认行动本身，计划/押注/产品与非国家主体不得误升。纯地缘事件的分类标签必须为`地缘政治`。
7. 有效性门：`important_only=true`、`capture_window_hours=12`、`window_covered=true`、至少 3 条 12 小时候选、正好 3 条 selected top3、`rows` 等于 `selected_rows`、最新快讯时间格式有效；失败退出码 2，由 vNext control-plane hash 绑定的 `capture_all.js` 按六源缺失硬停。

## 失败处理

* 站点 403/404、加载超时、「重要快讯」未选中或状态丢失、12 小时窗口未覆盖、候选少于 3 条、top3 缺失或截图失败 → 视同缺源并硬停。
* 严禁只有文字没有截图。
* 严禁退回未筛选的全量快讯。
* 严禁使用历史新闻或模型推理补齐。
