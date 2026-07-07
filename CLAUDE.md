# Trading-System 会话入口

- “写/出/跑/生成日报、早报、午报、晚报”及对应“早间/午间/晚间日报”只触发 `/daily-report`。
- 本工作区只提供 `/daily-report` 日报入口，禁止调用、串联或输出任何外部报告、总结或跨工作流流程。
- 完整流程以提交态 `sessions/日报SOP.md` 为权威；`.claude/skills/daily-report/SKILL.md` 仅作为本机 Claude Code 兼容镜像，不能覆盖提交态 SOP。
- 数据采集和确定性脚本可以优化；采集后的验真、读图、转录、分析、评分、胜率、风险、情景、决策、成稿与审查全部使用最高可用模型能力和 MAX 思考预算。
- 进入验真前必须确认 Effort=`Max`，并用 `session_runner.py prepare ... --capture-manifest <精确路径> --lease-token <token> --max-reasoning-confirmed` 留痕；缺任一项硬停。
- 每个报告节点完整独立重算，禁止复用前序特征、分数、胜率、风险与判断；资源不足则硬停。
- 分析前只使用 `context_pack.py` 最小包，禁止直接读取完整台账、聚合记忆和前序判断。
- 分析锁前读取与搜索必须遵守 `context_pack.py` 输出的 `read_policy.prelock_safe_read_policy`；禁止裸全仓库搜索命中 `sessions/archive/**`、旧 `outputs/**`、旧 `runtime_state/**`、`reviews/**` 或 quarantine。
- combined.md 通过 lint 后先运行 `session_runner.py lock-analysis`；分析锁建立前禁止读取前序计划。锁后完成计划衔接／漂移对照及晚报独立审查，再运行 `finalize-post-lock`；commit 缺任一道门均硬停。
- 三门与最终台账记录完成后运行 `session_runner.py deliver`。
- 采集前运行 `begin-session`，整链携带 lease token；前一时段未 deliver 时下一时段硬停。中断只能显式 abandon/recover 并写原因。
- 逻辑版本变化只使分析失效，不触发完整重采；完整采集 fallback 仅限证据失败、缺失、过期或无效。
- Word 只走 canonical DOCX → Word COM → Poppler → MAX 逐页审核 → QA manifest；同哈希复用、最多两次、第三次硬停。context_log/delivery 不得早于实际 QA 证据。
