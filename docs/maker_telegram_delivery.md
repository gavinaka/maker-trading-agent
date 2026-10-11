# Maker Telegram Delivery

`runtime_vnext.maker_telegram.render_maker_telegram` accepts only a certified typed projection input. It does not parse Markdown or ask a model to create Chinese wording. A missing certified field is a hard failure, not an invitation to guess.

展示合同为 `maker-handwritten-notion-telegram-v2`，由 10 个 2026 年、确有开仓策略的 Maker Notion 页面交叉读取后冻结。它采用收敛出的手工字段顺序，但不会伪造手工页面不存在于 typed 决策内的主观词（例如将一个并未认证的计划强写成“低多”）。策略类型、方向、区间、概率、风险和理由均直接来自认证字段；审计哈希、渲染状态、执行边界和订单状态留在机器证书，不进入用户消息。

Use these rules for all three slots:

- A certified `qualified_candidate` shows the complete 2--5 level Maker ladder, full-fill risk scenarios, stop, targets, cancellation price, thesis, counterevidence and invalidation.
- Every other certified Maker semantic state says **不做** with its certified state/reason.
- A broken evidence, reasoning, decision or projection gate makes the scheduler exit non-zero without any Telegram message. It must never manufacture a `不做` conclusion.
- A shadow run remains a candidate plan, never a live order instruction.

`runtime_vnext.maker_schedule` is intentionally a delivery scheduler, not an analysis engine. It sends only a same-day Maker message whose full typed decision and in-memory canonical model have just passed the original depth gate and match the already-sealed Maker certificate. It has no inbound API surface, omits Telegram `parse_mode`, disables link previews, and never logs secrets or response bodies. `tools/install_maker_telegram_tasks.ps1` creates three interactive-user Windows tasks for 09:00 / 16:30 / 20:30 Asia/Shanghai.
