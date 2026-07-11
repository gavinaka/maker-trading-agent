# 日报运行合同（紧凑入口）

此文件只承载不随报告变化的机械入口；完整业务规则按 `context_pack` 的 phase read plan 分阶段读取，禁止每轮重复通读全部仓库。

1. 先运行 `runtime/automation_memory_guard.py`，再运行 `runtime/daily_report_status.py`。
2. `complete` 正常结束；其它状态严格按 status 输出的 `next_action` 处理，不抢占别的 lease。
3. 分析锁前只允许 `runtime/prelock_read_policy.py` 声明的路径；搜索只能使用 `runtime/prelock_safe_search.py`。每个阶段先运行 `runtime/phase_contract.py` 生成一个 hash-bound bundle，只读该 bundle 一次，禁止对同一权威文件反复分段读取。技能入口只读一次，`workflow_entry` 不重复装载技能；分析阶段必须完整读取 `analysis_orderflow`、`analysis_chart_winrate`、`analysis_agents` 三包。任何 bundle 超过 60KiB 或 `complete` 非 true 都硬停，禁止截断或删减权威。
4. `begin-session → immutable capture → prepare` 后，完成六源验真与 MAX 推理工作稿。
5. 评分、胜率和 Maker 风险数学必须先生成并通过 `runtime/decision_contract.py`；不得只在自然语言中声称算术正确。
6. `certify-reasoning` 将工作稿、capture、transition、golden manifest 与 decision contract 一起绑定，之后才允许写正式 `combined.md`。
7. `cards → preflight-report → lock-analysis → finalize-post-lock → commit → canonical render → Word QA → publish → frozen verifier → unique page → record-delivery-evidence → deliver` 缺一不可。`preflight-report` 在锁前机械复核 reasoning readiness、golden reasoning、lint、统一正文解析、payload 派生、来源绑定输入和三张 BlockBeats 卡；不得修改任何交易推理。2026-07-11 起分析锁必须绑定该预检 manifest。`record-delivery-evidence` 只从真实 render/QA/publish manifest 原子生成 context 机械证据块，`deliver` 仍独立回读验证。
8. 晚报不生成独立审查。外置交易准确性评估由 Technical expert 在交付后一小时执行，不属于生产链。
9. 报告深度以六源证据、因果链、反证、失效路径和机械计算完整性判断，不以字符数、价位引用次数或工具调用次数判断。
10. 交付后运行 `runtime/host_usage_import.py` 导入当前 `CODEX_THREAD_ID` 的真实 token/轮次/工具指标；目标为模型轮次不超过 80、非缓存输入不超过 80 万。超标只形成效率告警，不回写或改变交易结论。
