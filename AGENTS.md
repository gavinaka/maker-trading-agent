# Trading-System 工作区路由与推理宪法

## 意图优先级

- 用户要求“写/出/跑/生成日报、早报、早间日报、午报、午间日报、晚报、晚间日报”时，只运行项目级 `daily-report`。
- 上述精确时段日报意图绝对优先，禁止触发、串联或输出任何外部报告、总结或跨工作流流程。
- Trading-System 工作区只提供本仓库明确定义的交易日报流程；非日报请求不做跨工作流路由。
- 本仓库是七 Agent 生态中的交易生产所有者；生态清单以 `../Technical expert/ecosystem/registry.json` 为准，但日报正式分析不得读取该注册表或其它 Agent 内容。跨库修复只归 Technical expert 且需用户批准。
- 确定性分类规则见 `runtime/intent_router.py`，回归测试见 `tests/test_report_intent_routing.py`。

## 执行权威

- Codex 入口：`.agents/skills/daily-report/SKILL.md`
- 周报入口：`.agents/skills/weekly-review/SKILL.md`；月报入口：`.agents/skills/monthly-review/SKILL.md`。两者必须先读 `governance/periodic_review_contract.md`，且不得承担外置交易准确性评估。
- 日报必须在任何 run-specific 动作前选定且只选定一个引擎：
  - **vNext**：仅限明确的 `runtime_vnext` / `runtime_state_vnext` / shadow / cutover 任务。开始后只以当次 run 密封的 `methodology_manifest.json` 中当前 phase 文件为业务权威，逐文件复核路径、字节数和 SHA-256。禁止读取或运输 `sessions/日报SOP.md`，禁止运行 legacy `context_pack` / `phase_contract` / `session_runner`，禁止混入 legacy state。切换前只允许本地 `shadow-delivery`，`notion_published=false`，不读写 Notion。
  - **legacy**：提交态完整执行权威为 `sessions/日报SOP.md`，仅此分支使用 `runtime/session_runner.py` 及其有界上下文传输。
- Claude Code 本机兼容镜像：`.claude/skills/daily-report/SKILL.md`（该目录被 `.gitignore` 排除，不得覆盖提交态 SOP 权威）
- `.claude/skills/weekly-review`、`.claude/skills/monthly-review` 或其它 ignored 镜像都不是 Codex 执行权威。

## 宪法级推理边界

- 只在网络抓取、文件处理、纯算术、lint、verifier、渲染和发布等确定性机械层优化 token。评分/胜率/风险的“解释”属于推理层，其算术一致性必须由 `decision_contract.py` 机械复算。
- 从源有效性验真、图表阅读和指标转录开始，生产模型固定为 `gpt-5.6-sol`。新 vNext run 请求的推理努力固定且只能为 `xhigh`，并保持完整工作流深度；宿主实际观测为 `xhigh|max|ultra` 只表示满足 `>= xhigh` 的能力证明，不是更改 run 请求值或正确性依赖，不得换成其它模型。历史已密封 run 的 effort 不得改写；legacy engine 仍遵守其独立的 exact `high` 合同。
- 每份早/午/晚报均从完整有效六源重新分析、评分、估算胜率、验算风险并形成决策；禁止复用前序派生特征、评分、胜率、风险或判断。
- 推理资源不足时硬停，禁止降档或降质继续。

## legacy 引擎专属机械链

以下条款只属于 legacy `runtime/session_runner.py` 分支，不得被 vNext 读作命令或缺失依赖：

- 进入推理层前，通过 legacy host manifest 传入精确 `--capture-manifest`、整链 `--lease-token` 与完整深度确认。
- 从 2026-07-06 午报起，正式 `combined.md` 生成前完成 `runtime_state/<date>/reasoning_work_<slot>.md` 并运行 `session_runner.py certify-reasoning` 形成 pre-MD readiness；后补理由、后补 rubric 或后补任何推理均禁止。
- 分析前只读取 `context_pack.py` 生成的最小包，禁止直接读取完整 `context_log.md`、聚合 `MEMORY.md` 或前序分析／决策。
- 分析锁前读取与搜索必须遵守 `context_pack.py` 输出的 `read_policy.prelock_safe_read_policy`；禁止裸全仓库搜索命中 `sessions/archive/**`、旧 `outputs/**`、旧 `runtime_state/**`、`reviews/**` 或 quarantine。
- lint 后必须先建立与报告哈希绑定且包含 pre-MD readiness 的 `lock-analysis`，再允许事后读取前序计划；完成撤旧挂新／漂移对照后运行 `finalize-post-lock`，commit 缺任一道门或完整节点时硬停。晚报交付后的准确性评估由 `Technical expert` 外置流程异步执行，不属于交易生产门禁。
- 最终三门和台账记录完成后必须运行 `session_runner.py deliver`，形成最终交付状态。
- 采集前必须 `begin-session` 并把 lease token 传给采集及所有 runner 阶段；租约持续到 hash-closed delivery，禁止时段交叠或静默抢锁。
- 逻辑版本变化只触发本时段 MAX 全量分析失效，不触发证据重采；完整采集回退只允许证据失败、缺失、过期或无效。
- DOCX 仅允许 canonical 文件；渲染/Word 导出哈希幂等且最多两次，且从 2026-07-06 午报起必须有 hash-bound analysis lock。producer 遇到 Windows `80070520` 时，只能经共享 heartbeat 与 canonical、nonce/SHA-256 绑定的 attempt 请求使用预安装的常驻交互式 Word broker；sandbox 不得查询/触发 Task Scheduler，禁止任意路径或任意参数任务。两次历史失败后的基础设施迁移例外仅可使用一次，成功或失败均永久消耗；delivery 必须复核 broker request/response 与迁移证据，并读取真实 render/Word-QA/publish/context_log manifest，禁止布尔自证。
