# Maker Trading Agent

## 角色与唯一交付

本工作区是独立的 **Maker Trading Agent**。它在早、午、晚各完成一次完整的六源证据、认证推理、Maker 风控和决策流程；唯一面向用户的交付是 Telegram Maker 策略消息。

不得生成、导出或发布 Word、Notion、PDF、HTML 日报。它们不是本 Agent 的交付门禁。

## 隔离边界

- `../Trading-System`、`../Trading-System-vNext`、`../交易机会触发（预警）` 和其它桌面 Agent 一律只读；不得修改其代码、配置、调度、Notion、运行状态或凭据。
- 本仓库由 `Trading-System-vNext` 已提交快照 `00069a618de237d44beb6f67621b123105f70c58` 初始化；该快照是新 Agent 的策略内核基线。升级内核只能整体地、经用户批准后更新，不得跨仓库补丁式同步。
- 原仓库未提交改动不是本 Agent 的方法论来源，也没有被复制进来。
- Telegram 只是一条单向通知通道，不下单、不创建、撤销或修改交易所订单，也不读取真实持仓。

## 反漂移宪法

1. 每个时段必须重新获得完整有效的六源证据；不得复用前一时段的评分、概率、风险或结论。
2. 推理与决策继续使用既有 typed evidence / reasoning / decision 合同。评分、计划时置信度、梯度入场、全成交组合风险、止损、反证、失效和 `cannot_do` 都保留。
3. Telegram 投影只接受 `CertifiedReportProjectionInput`；不得读取或解析 Markdown、Word、Notion、自由文本报告或模型回答以重建策略。
4. 投影层不得调用模型、网络、文件或外部工具来补全策略语义。字段未被认证时，构建失败并且不发送。
5. `qualified_candidate` 仅表示通过认证的 Maker 候选计划；是否有真实执行授权必须单独展示。影子运行不得被表述为可执行或已下单。
6. `rejected_submitted_candidate`、`directional_thesis_only` 与 `non_directional_observation` 必须明确推送“**不做**”。证据或门禁失败必须写“本时段未产生策略”，不得伪装成“不做”。
7. 推送正文与 `evidence_snapshot_sha256`、`reasoning_sha256`、`decision_sha256`、`methodology_sha256` 绑定；重试只允许发送同一 `message_sha256`。

## Telegram 安全

- 仅从环境变量读取 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`；禁止读取、打印、写入或提交 `.env`、token、chat ID 或完整 HTTP 响应。
- 默认仅 `telegram-preview`，不会发送任何消息。`telegram-send` 需要显式 `--send`，且当前 Agent 的展示合同已经由用户确认。
- 只可调用 Telegram `sendMessage`，禁用入站命令、键盘按钮、网页预览与任何交易所 API。

## 定时投递

- 本机任务计划只调用 `runtime_vnext.maker_schedule`；它只读取本仓库当前日期、当前 slot、已封存的 evidence / reasoning / decision 三阶段和已封存的 Maker 认证证书。
- 缺少同日认证决策、决策处于 `needs_review` / `retired`、投影失败或凭据缺失时，任务必须以非零状态硬停，且不得发送 Telegram 文本；“不做”只能来自认证的 Maker 决策。
- 时间固定为 Windows 本地 Asia/Shanghai：早 `09:00`、午 `16:30`、晚 `20:30`。任务以当前交互式用户运行、限制为单实例、5 分钟超时；它是精确定点投递器，不启动 Codex CLI、常驻服务或其它 Agent。每个时段的完整分析必须先在本 Agent 内完成并封存；来不及完成时不发送。

## 验证

- 每次改动 Telegram 投影、中文字段或投递器，至少运行 `py -m unittest -v tests.test_vnext_maker_telegram`。
- 任何策略内核或合同改动还必须运行相关 vNext 语义测试；不得把测试通过表述为交易正确性或实际收益证明。
- 不得在未经用户明确批准时创建 Windows 任务计划、启动常驻服务或发送 Telegram 测试消息。
