# 日报运行合同（紧凑入口）

此文件只承载不随报告变化的机械入口；完整业务规则按 `context_pack` 的 phase read plan 分阶段读取，禁止每轮重复通读全部仓库。

1. 先运行 `runtime/automation_memory_guard.py`，再运行 `runtime/daily_report_status.py`。
2. `complete` 正常结束；其它状态严格按 status 输出的 `next_action` 处理，不抢占别的 lease。
3. 分析锁前只允许 `runtime/prelock_read_policy.py` 声明的路径；搜索只能使用 `runtime/prelock_safe_search.py`。每个阶段先运行 `runtime/phase_contract.py` 生成一个 hash-bound bundle，只读该 bundle 一次，禁止对同一权威文件反复分段读取。技能入口只读一次，`workflow_entry` 不重复装载技能；分析阶段必须完整读取 `analysis_orderflow`、`analysis_chart_winrate`、`analysis_agents` 三包。任何 bundle 超过 60KiB 或 `complete` 非 true 都硬停，禁止截断或删减权威。
4. `begin-session → immutable capture` 后，先运行 `runtime/host_capability.py` 从当前 session JSONL 绑定实际 model/effort；自动化固定 `gpt-5.6-sol + high`，实际 effort 低于 `high` 即硬停（`max` 也兼容），再把该 manifest 传给 `prepare`。Prompt 或布尔参数自称高深度不构成证据。
5. 先用 `runtime/reasoning_contract.py` 生成 v2 强类型合同：当前证据、同锚三问、足迹交叉验证、多周期转换、增量 VRVP/猎杀/清算图/ETF 维度、账户分流、三情景树、支持/反证、评分、计划时置信度和 Word/Notion 语义投影缺一不可。再用 `runtime/adversarial_review.py` 对每个承重 claim 的真实 support/counter 节点做隔离第二遍反证。评分、置信度和 Maker 风险数学最后由绑定同一 reasoning contract 的 `runtime/decision_contract.py` 生成。
6. `certify-reasoning` 将工作稿、capture、transition、host capability、golden、reasoning、adversarial review 与 decision contracts 一起绑定；reasoning contract 必须机械复算 C01–C81、效果背离与 OI/价格语义，禁止资金费率翻向，并保证盘面30为 TradingView-only 的方向中立机会质量分。TradingView VRVP 是流动性猎杀主判；Coinglass 清算热力图是独立辅助 observation，只能确认/削弱，不得加盘面分、改盘口分或翻方向；随后必须 `lock-reasoning` 冻结独立分析并恢复锁后只读上下文。前序计划/实仓只允许此后读取并生成 `continuity_contract`，证明撤旧/保留/挂新和最终活跃订单数，且不得改变已锁分析。
7. `combined → report semantic projection → cards → certify-draft → preflight-report → lock-analysis → finalize-post-lock → commit → canonical render → Word QA → publish → frozen verifier → unique page → record-delivery-evidence → deliver` 缺一不可。draft/preflight 必须证明金标准承重语义同时存活于可见正文和③后附，Notion 由同一 combined 确定性派生且不可压缩丢失。`record-delivery-evidence` 只从真实 render/QA/publish manifest 原子生成 context 机械证据块，`deliver` 仍独立回读验证。
8. 晚报不生成独立审查。外置交易准确性评估由 Technical expert 在交付后一小时执行，不属于生产链。
9. 报告深度以六源证据、因果链、反证、失效路径和机械计算完整性判断，不以字符数、价位引用次数或工具调用次数判断。
10. 交付后运行 `runtime/host_usage_import.py` 导入当前 `CODEX_THREAD_ID` 的真实 token/轮次/工具指标；目标为模型轮次不超过 80、非缓存输入不超过 80 万。超标只形成效率告警，不回写或改变交易结论。
