# BlockBeats Collector SOP

## 目标

实时采集抓取前 12 小时内的 BlockBeats「重要快讯」，保留截图、12 小时候选池与结构化 top3，供日报基本面独立判断。

## 数据源

https://www.theblockbeats.info/newsflash

## 唯一路径（硬性）

* 统一入口：`node tools/browser_capture/capture_all.js`
* 子采集器：`tools/browser_capture/capture_blockbeats.js`
* 禁止：Chrome MCP、WebFetch/搜索摘要、历史快讯、AI 生成内容
* 依据：2026-06-28 用户拍板 BlockBeats 与其余四源走同一自动采集路径，同时保留“必须截图”要求。

## 执行流

1. `capture_all.js` 首项调用 `capture_blockbeats.js`。
2. Playwright/Chrome 打开 BlockBeats 快讯页。
3. 关闭可能遮挡筛选项的通知提示，勾选「重要快讯」，并确认复选框保持选中。
4. 保存：
   * `data_sources/inbox/<YYYY-MM-DD>/blockbeats.png`
   * `data_sources/inbox/<YYYY-MM-DD>/blockbeats.json`
5. JSON 写入 `"important_only": true`、`"capture_window_hours": 12`、`"window_covered": true`、`candidate_rows`、`selected_rows` 和兼容字段 `rows`。
6. `candidate_rows` 保留抓取前 12 小时内所有可加载重要快讯；`selected_rows`/`rows` 只保留按基本面影响优先级筛出的 3 条。
7. 有效性门：`important_only=true`、`capture_window_hours=12`、`window_covered=true`、至少 3 条 12 小时候选、正好 3 条 selected top3、`rows` 等于 `selected_rows`、最新快讯时间格式有效；失败退出码 2，由 `capture_all.js`／`capture_delta.js` 按五源缺失硬停。

## 失败处理

* 站点 403/404、加载超时、「重要快讯」未选中或状态丢失、12 小时窗口未覆盖、候选少于 3 条、top3 缺失或截图失败 → 视同缺源并硬停。
* 严禁只有文字没有截图。
* 严禁退回未筛选的全量快讯。
* 严禁使用历史新闻或模型推理补齐。
