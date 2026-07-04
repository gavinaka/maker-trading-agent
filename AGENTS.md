# Trading-System 工作区路由与推理宪法

## 意图优先级

- 用户要求“写/出/跑/生成日报、早报、早间日报、午报、午间日报、晚报、晚间日报”时，只运行项目级 `daily-report`。
- 上述精确时段日报意图绝对优先，禁止触发、串联或输出 `quant-summary`。
- Trading-System 工作区不提供 `quant-summary`；出现“量化总结／量化点评”时不做跨工作流路由。
- 确定性分类规则见 `runtime/intent_router.py`，回归测试见 `tests/test_report_intent_routing.py`。

## 执行权威

- Codex 入口：`.agents/skills/daily-report/SKILL.md`
- 提交态完整执行权威：`sessions/日报SOP.md`
- Claude Code 本机兼容镜像：`.claude/skills/daily-report/SKILL.md`（该目录被 `.gitignore` 排除，不得覆盖提交态 SOP 权威）

## 宪法级推理边界

- 只在网络抓取、文件处理、纯算术、lint、verifier、渲染和发布等确定性机械层优化 token。
- 从源有效性验真、图表阅读和指标转录开始，全部使用最高可用模型能力与 MAX 思考预算。
- 进入推理层前必须确认模型/努力档位为最高可用与 Max，并在 `session_runner.py prepare` 传入精确 `--capture-manifest`、整链 `--lease-token` 与 `--max-reasoning-confirmed`；缺任一项硬停。
- 每份早/午/晚报均从完整有效五源重新分析、评分、估算胜率、验算风险并形成决策；禁止复用前序派生特征、评分、胜率、风险或判断。
- 推理资源不足时硬停，禁止降档或降质继续。
- 分析前只读取 `context_pack.py` 生成的最小包，禁止直接读取完整 `context_log.md`、聚合 `MEMORY.md` 或前序分析／决策。
- lint 后必须先建立与报告哈希绑定的 `lock-analysis`，再允许事后读取前序计划；完成撤旧挂新／漂移对照及晚报独立审查后运行 `finalize-post-lock`，commit 缺任一道门或完整节点时硬停。
- 最终三门和台账记录完成后必须运行 `session_runner.py deliver`，形成最终交付状态。
- 采集前必须 `begin-session` 并把 lease token 传给采集及所有 runner 阶段；租约持续到 hash-closed delivery，禁止时段交叠或静默抢锁。
- 逻辑版本变化只触发本时段 MAX 全量分析失效，不触发证据重采；完整采集回退只允许证据失败、缺失、过期或无效。
- DOCX 仅允许 canonical 文件；渲染/Word 导出哈希幂等且最多两次。delivery 必须读取真实 render/Word-QA/publish/context_log manifest，禁止布尔自证。
