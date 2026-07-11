---
name: weekly-review
description: 每周日生成 Trading-System 运营与执行周报；不承担报告预测准确性评估。
---

# Trading-System 周报

1. 完整读取 `governance/periodic_review_contract.md`，其边界优先于历史模板示例。
2. 运行 automation memory guard 与 `daily_report_status.py --kind weekly`，按状态机决定停止、claim 或继续。
3. 统计窗口固定为北京时间周一 00:00 至周日 23:59，只加载本周必要交付与当前真值。
4. 按 `templates/weekly_review.md` 输出 `reviews/<YYYY-Www>_weekly.md`。
5. 实际账户笔数、盈亏、纪律与洁净样本只能来自本周 Notion 当前行/用户确认；本地 state 和旧周报不能补缺。
6. “核心迭代 / 核心洞察 / 下周目标”需要用户已确认内容；没有则 release gate 并列出缺项。
7. 不计算报告预测入场击中率、条件 TP1、Brier、日报质量或概率校准；这些只归外置准确性评估器。
8. 发布到 AI agent（Tradingplan）周维度顶层子页后，回读验证标题、父页、块数、关键数字与唯一页；通过才 complete gate。
9. 不读取 `.claude/skills` 作为权威，不生成一次性推送脚本，不从文件提取 token，默认不 commit。
