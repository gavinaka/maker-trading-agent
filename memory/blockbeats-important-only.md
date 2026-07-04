# BlockBeats 基本面仅采集重要快讯

## 永久规则

- 适用范围：Trading-System 后续全部早报、午报和晚报。
- BlockBeats 页面采集前必须勾选「重要快讯」，只允许提取筛选后的资讯。
- `blockbeats.png` 必须保留已勾选状态作为视觉证据；`blockbeats.json` 必须写入 `"important_only": true`。
- 未找到筛选项、无法勾选、勾选后状态丢失或 JSON 字段不为 `true`，均视为 BlockBeats 核心源无效并硬停；禁止用未筛选的全量快讯降级继续。
- 通过筛选后仍执行原有效性门：当天日期、至少 3 条当日重要快讯、有效最新时间。
- 该要求只改变 BlockBeats 的资讯筛选范围；其余五源采集、基本面优先级、分析、评分、模板、Word、Notion 与交付逻辑全部不变。

## 机械实现

- 权威采集器：`tools/browser_capture/capture_blockbeats.js`。
- 采集器关闭可能遮挡筛选项的 OneSignal 提示，定位包含「重要快讯」的复选框并确认其保持选中。
- 有效性表达式必须包含 `importantOnly`；采集失败返回非零状态，使 `capture_all.js`／`capture_delta.js` 按核心源失败处理。

## 来源

- 2026-07-02 用户明确要求：基本面采集仅采集「重要快讯」，其他不变，并要求后续所有报告永久沿用。
