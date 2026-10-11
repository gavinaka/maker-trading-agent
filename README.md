# Maker Trading Agent

独立的早／午／晚 Maker 策略 Agent。它保留冻结策略内核的完整证据、推理、评分、风险与决策门禁，唯一用户交付是 Telegram Maker 消息。

## 不变的策略内核

- 初始基线：`Trading-System-vNext` 已提交快照 `00069a618de237d44beb6f67621b123105f70c58`，见 [`KERNEL_LOCK.json`](KERNEL_LOCK.json)。
- 不复制原工作树未提交改动；不写回任何原有 Agent。
- 每个时段重新完成六源证据与认证推理；不复用前一时段的策略判断。
- 完整推理与审计仍保留在本 Agent 的密封制品中；Telegram 只是确定性阅读视图。

## Telegram 交付

- `runtime_vnext.maker_telegram` 只接受 `CertifiedReportProjectionInput`，不读取 Markdown、Word、Notion 或自由文本来重建策略。
- 输出层不用模型。中文字段、顺序和状态映射固定；认证字段缺失即失败而不是猜测。
- `qualified_candidate` 按 10 个 2026 年 Notion 开仓计划中收敛出的手工顺序显示：执行概率／胜率自估、计划区间与仓位、入场梯度、止盈止损、全组合风险、两层防守、取消条件、反证和失效；其它认证状态明确写 **不做**。
- `prepare-maker-delivery` 在完整原有认证门禁通过后仅封存 Maker 证书，不渲染报告；`telegram-send --send` 和定时投递器只会发送该证书逐次复验后得到的同一条消息。token 和 chat ID 只从环境变量读取。
- 投递按 `message_sha256` 去重；网络结果不确定时标记为未知并硬停，避免重复推送。

详见 [`docs/maker_telegram_delivery.md`](docs/maker_telegram_delivery.md) 和 [`AGENTS.md`](AGENTS.md)。

## 尚未启用的事项

`tools/install_maker_telegram_tasks.ps1` 安装三个独立的本机任务：早 `09:00`、午 `16:30`、晚 `20:30`（Asia/Shanghai 本机时间）。任务不是分析引擎：它只发送同日、同 slot、已经过完整深度门禁并封存证书的认证决策；缺少或变更时非零硬停且不会把故障伪装成“不做”。

首次真实发送必须同时满足：同日认证决策已存在，`TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID` 可由该任务读取，且 Telegram 返回可验证的 `message_id`。凭据不写入本仓库，也不会从其它 Agent 复制。
