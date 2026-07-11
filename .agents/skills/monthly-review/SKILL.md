---
name: monthly-review
description: 自然月最后一天生成 Trading-System 运营与执行月报；动态事实缺失时硬停。
---

# Trading-System 月报

1. 完整读取 `governance/periodic_review_contract.md`。
2. 运行 automation memory guard 与 `daily_report_status.py --kind monthly`，按状态机决定停止、验证现有产物、claim 或继续。
3. 统计窗口固定为北京时间自然月首日 00:00 至月末 23:59，只加载本月必要交付与当前真值。
4. 按 `templates/monthly_review.md` 输出 `reviews/<YYYY-MM>_monthly.md`。
5. 余额、仓位、盈亏、交易记录、违规和洁净样本必须来自月末 Notion 当前行/用户确认；旧状态和历史财务表不能自动沿用。
6. “整月核心问题 / 下月目标”必须来自用户确认；缺失则 release gate，不生成模型替代内容。
7. 不把外置准确性评估指标复制为生产自评，不自动调整任何交易参数。
8. 发布后回读验证标题、父页、块数、关键数字与唯一页；通过才 complete gate。
9. 不读取 `.claude/skills` 作为权威，不生成一次性推送脚本，不从文件提取 token，默认不 commit。
