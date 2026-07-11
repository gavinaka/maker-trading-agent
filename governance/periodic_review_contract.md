# 周报 / 月报运行契约

## 职责边界

- 周报和月报是 Trading-System 的**运营与执行复盘**：交付完整性、用户实际执行、纪律、风险和已确认的账户事实。
- 报告预测的入场击中率、条件 TP1 命中率、执行概率/胜率 Brier、12 维日报质量与校准结论只归外置 `Technical expert` 交易准确性评估器。生产周/月报不得重复计算、覆盖或反向调节这些指标。
- 周/月报不得自动修改评分、胜率、风控或开单阈值。

## 当前真值来源

1. 用户在本次周期明确确认的数据，或 Notion 当前行的只读查询结果。
2. 本周期已交付日报、交付 manifest、违规记录和可验证的生产运行状态。
3. `state/*.json`、旧周/月报和历史财务表只能作为线索；使用前必须回源核实，不能当当前余额、仓位、盈亏或洁净样本真值。

所有动态数字必须记录来源、北京时间采集时间和统计窗口。缺少当前余额、仓位、交易结果、用户核心洞察或下周期目标时，保留 gate、停止发布并报告缺项；禁止用旧值、行业均值或模型推测补齐。

## 执行顺序

1. 先运行 `runtime/automation_memory_guard.py`；memory 只可保存 gate、路径、哈希和完成状态，出现交易判断即硬停。
2. 再运行 `runtime/daily_report_status.py --kind weekly|monthly`；`complete` 立即结束，避免重复 token 消耗。
3. 只有 `ready_to_claim` 才 claim 对应 automation gate；存在 stale/in-progress gate 时停止。
4. 只加载当前周期必要的交付文件、Notion 行和模板，不全量读取历史报告。
5. 计算必须使用 Python `Decimal` 或等价确定性脚本；报告中的合计、同比、比例必须能由输入重算。
6. 按 `.agents/skills/weekly-review/SKILL.md` 或 `.agents/skills/monthly-review/SKILL.md` 与对应模板生成本地 Markdown。
7. 发布只允许使用 Notion 已安装连接器或仓库现有参数化机制；token 只能来自受控环境变量。禁止读取 ignored `.claude` 火种、生成一次性推送脚本或把 token 写入命令/文件。
8. 发布后回读标题、父页、块数量、关键数字和唯一性；全部通过才 complete gate。失败时 release 自己持有的 gate。

## 输出要求

- 周报：`reviews/<YYYY-Www>_weekly.md`。
- 月报：`reviews/<YYYY-MM>_monthly.md`。
- 正文必须有“数据边界与来源”段，列出统计窗口、动态来源、用户确认项和未知项。
- 不允许 `{{placeholder}}`、`TODO`、未解释的旧值、把状态摘要当业务真值，或把外置准确性结论复制成生产系统自评。
- 默认不 commit。
