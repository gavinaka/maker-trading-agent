# 日报执行 SOP（确定性流程 · 照此走不试错）

> ⚡ **已落成 skill**：跑日报直接调 `/daily-report`（先取得整链租约，六源统一走带 lease token 的 capture 脚本；Notion 实际持仓只允许分析锁后校准）。本文件是权威全文，skill 是其可执行 checklist；路径/规则变更时**本文件 + 对应 SKILL.md + memory 三处同步**。
> 🟥 **工作流永久隔离边界（2026-06-28 用户明确）**：今后每一次早报／午报／晚报均只执行本 SOP 及其明确列出的本仓库子流程；与任何其他报告、总结或跨仓库工作流无关。禁止调用、串联、读取或写入其他工作流，禁止把其他工作流的规则、上下文或产物混入日报。此规则永久生效，不是单次例外。
> 目的：减少踩坑、省 token。每条都是已验证的「唯一正确路径」，不要再探索替代方案。
> 维护：发现新坑或路径变化时更新本文件 + 对应 memory。
> 🟥 **宪法级·第一优先级（除用户拍板的系统逻辑外最高优先）：报告必须完全对齐用户 Notion 实际模板字段**（字段名/顺序/含义全对）。出稿前对照用户最近 Notion 条目逐字段核，**严禁臆造/混用字段**（如把"止损"标成"取消价"）。模板对齐错误=宪法级违规、误导执行+二次返工耗 token。详见 §3 渲染规则与 `memory/report-template-alignment.md`。
> 🟥 **一次锁死铁律（2026-06-01 用户带情绪强调）：锁模板/逻辑时样本不足，就在同一次里随机抽查 2 年内最多 20 个 Notion 样本补足，一次核到 100% 再落地；禁止半验证上线后反复改 skill 浪费用户 token。** 见 `memory/verify-once-sufficient-samples.md`。
> 🟥 **Claude Code → Codex 平移硬门（2026-07-04）**：旧 `.claude/skills/daily-report/SKILL.md` 是本机兼容镜像，不是 Codex committed 权威；旧入口中的关键 guardrail 必须由本 SOP、`.agents/skills/daily-report/SKILL.md` 与 `runtime/context_pack.py` 承载。每次 Codex 跑日报必须读取并执行：`memory/independent-report-no-user-reference.md`、`memory/precise-numbers-no-fuzzy.md`、`memory/report-chinese-only-narrative.md`、`memory/notion-publish-checklist.md`、`memory/stability-contract.md`。缺任一项或只存在于 `.claude/` 即硬停同步，不得继续出稿。

---

## 0.0 用户每日/周/月工作流顺序（权威 · 2026-05-31 用户给定 · 系统严格照此序）

> 🟥 **报告节点＝每日三份（2026-06-20 用户拍板·原 2 份→3 份·只新增「午报」一个节点·其余任何逻辑内容均不变）**：
> - **早报 08:00–10:00（亚洲开盘）** ＝ 原早间链 A 全骨架，Notion 子页 `🌅`。
> - **午报 15:30–16:00（欧美交接）** ＝ **新增节点·走与早报完全相同的全骨架**（六源+70/30评分+主账户plan+Maker plan，受开单双门槛），Notion 子页 `🌇`，结构门复用早间 28 块金标。**门禁沿用当日早间结论·不重读**（门禁是每日一次的硬前置）。
> - **晚报 20:00–20:30（美盘开盘前）** ＝ 原晚间链 B（Maker 新增/更新计划 + 反思四件套 + 独立审查），Notion 子页 `🌙`+`🔍`。
> - 🟥 **三个报告节点的内部逻辑/评分/模板/六源/门槛全部一致·零改动**——午报只是「把早报全骨架在欧美交接时段再跑一次」。
> - 🟥🟥 **三报告各自 MAX 深度独立思考·禁复制前序判断（宪法级）**：早/午/晚每节点都从当时重新采集的完整有效六源重新验真、读图、转录、分析、评分、胜率、风险并形成决策。共享层仅复用模板、字段、块序、来源指纹规则与确定性事实元数据，禁止复用前序报告证据快照、派生特征、评分、胜率、风险或判断。采集后的所有推理节点使用最高可用模型能力与 MAX 思考预算；资源不足硬停，禁止降档、截断、只重算变化节点。分析锁定前禁止读取前序方向、分数、胜率和 Maker 结论，锁定后仅用于撤旧挂新及漂移对照。
> - 「11:00／15:30／20:00 评分点」是冻结模板节点标签，不是实际采集/发布时间；quote 必须写真实采集时段。发布可执行计划前动态检查源文件年龄：Coinglass／Exocharts／TradingView 四档任一超过 4 小时即硬停并重采、重评分、重出稿；禁止把过期报告晚推后继续当实时计划。

> 系统前置（用户不列、我必跑）：先取得整链租约 + 采集六源 + 门禁/心力硬前置。**分析锁定前禁止读取两库交易Check 实际持仓；持仓只允许锁后操作校准，且不得改变独立报告判断。** 独立报告边界见 `memory/independent-report-no-user-reference.md`。
> 🟢 **六源统一采集（2026-07-05 加入 Farside BTC ETF Flow）：BlockBeats／Coinglass／Exocharts／FedWatch／Farside BTC ETF Flow／TradingView 全部由本仓库 Playwright 采集器顺序处理。** 先 `begin-session`；早报运行 `capture_all.js --slot morning --lease-token <token>` 建立完整基线，午报运行 `capture_delta.js --slot midday --lease-token <token>`，晚报运行 `capture_delta.js --slot evening --lease-token <token>`。这里的 delta 只表示午/晚使用保守顺序、变化指纹与一次 full fallback 机制，绝不表示可跳过任一六源或复用早报/前序证据。每次生成 slot/lease/run-id 强绑定、不可覆盖的 manifest；出任何报告前六源都必须重新采集并重新通过有效性门。
> 六源喂入对应步骤：BlockBeats→主账户基本面；Farside→BTC 现货 ETF 流入/流出与价格方向一致性验证（策略辅助确认，不替代盘口/盘面评分）；Exocharts/Coinglass→技术评分；TradingView 15m→Maker 最终把关。

### 每日早报（08:00–10:00 亚洲开盘 · 链 A 全骨架）
1. **开仓前门禁** —— ⛔ **硬前置**：门禁关闭 → **今日工作暂停，不做任何计划**（主账户/Maker 计划都不写），报告只记"门禁关闭·今日观望"。门禁开启才往下走。
2. **交易 Plan 主账户（撰写）** —— 中线计划，按 **基本面>盘面>盘口** 推导，**不依赖技术评分**。
3. **技术指标评分（填充）** —— 盘口 70 + 盘面 30。
4. **交易 Plan Maker（撰写）** —— 按 **盘口>盘面>基本面**；**开单双硬门槛（并列·任一不满足即观望不挂）：① 总评分 ≥65　② 胜率自估 ≥60%** → 两者全满足才必须挂 Maker 单（挂价=⑤源高质量边缘）；执行概率 ≥50% 为软参考·非门槛·只定挂价可达性·不决定是否开仓（2026-06-16 用户拍板：总评分门槛 70→65、胜率升级硬门槛、执行概率由60%降为软参考，见 `memory/score70-must-place-maker.md`）；**「不能做」最后回填**（写完全文后，当天 Maker 收口结论）。
   - 若当天有实际开仓 → 增加「交易 Check」填充。
   - → 早报工作完毕。

### 每日午报（15:30–16:00 欧美交接 · 新增节点 · 与早报同骨架）
> 🟢 **走与早报完全一致的链 A 全骨架·逐步同上**（六源有效性确认和增量采集→完整六源 MAX 独立分析→主账户plan→70/30全量重算→Maker plan 受双门槛→「不能做」最后回填→有开仓补 Check），只两点差异：① **门禁不重读**，沿用当日早间门禁结论（关闭则午报同样只记观望）；② **Notion 子页用 `🌇 2026.M.D 午间`**，结构门 `py outputs/notion_verify_against_yesterday.py <午报page_id> midday`（midday 复用早间 28 块金标）。其余评分/模板/字段/三门收尾与早报零差异。
> 🟥 **「走与早报相同骨架」＝只复用模板/字段/块序，不复用前序证据或判断**：午间在采集层做保守 delta，但六源仍必须全部重新采集、重新锁定、重新通过有效性门；分析层必须读取当时完整有效六源，完整独立重做验真、读图、转录、评分、胜率、风险、情景与方向；**禁照搬早报的基本面/盘口/盘面/趋势/Maker 结论**（欧美盘已走出新行情，判断据当时证据重出、可与早报不同）。这是一次全新探索，不是把早报稿改改时间戳。

### 每日晚报（20:00–20:30 美盘开盘前 · 链 B）
0. **（20:00-20:30）交易 Plan Maker 晚间新增计划（撰写）** —— 20:00 晚间评分点后，按当天行情更新/新增 Maker 计划；「不能做」同样最后回填。
之后（至 23:00 反思·复盘四件套，按序）：
1. **心智自控日记表**
2. **心力监控模块**
3. **check 系统 50 笔交易（结晶/洁净样本）**
4. **交易 review（撰写）**

### 每周：周日晚上补充周报
### 每月：月底补充月报

> ⚠️ 顺序铁律：主账户 plan **先于** 技术评分写（中线方向由基本面定，不等分数）；Maker plan **后于** 评分写（受门槛约束）。「不能做」永远最后回填。

---

## 0. 开场（每次会话固定）
1. 运行 `context_pack.py`，先核对生成包中的 `authority_sha256`、`authority_manifest`、`authority_read_plan` 与 `read_policy.prelock_safe_read_policy`。只固定读取 `read_policy.mandatory_guardrails_always_read` 列出的硬门文件；其余权威文件按当前阶段（采集验真／分析评分／风控执行／渲染发布）展开读取，禁止每次盲读全量权威文件。若权威摘要意外变化、阶段边界不清或相关文件缺失，则读取受影响权威文件并硬停确认。分析锁定前禁止直接读取 `sessions/context_log.md`、`sessions/archive/**`、`memory/MEMORY.md`、旧 `outputs/**`、旧 `runtime_state/**`、`reviews/**`、`.prelock_quarantine/**`、前序报告、`analysis_*.json` 或 `decision_*.json`；禁止裸全仓库 `rg` 搜索 pre-lock 事实，只能按 context pack 明确路径读取或使用 `runtime/prelock_read_policy.py` 的 safe rg excludes。
2. 确认今天出早报(🌅链A)、午报(🌇新增·同早报全骨架)还是晚报(🌙链B)。
3. 不再拉取 Chrome 扩展 schema；六源统一走本仓库 Playwright 采集器，Notion REST 走 PowerShell。
4. **分析锁定前不读两库交易Check 实际持仓**。禁止沿用上次 state，也禁止用 Notion 已开/已平、已成交比例、缺均价、缺止损等改变 Maker/主账户独立判断。持仓校准只能在 `lock-analysis` 成功后作为单独操作校准执行。
5. **读 `开仓前门禁` + `心力监控` 当日行（工作流第 1 步·硬前置）**：
   - 门禁=关闭 / 主观=「不可交易」 → ⛔ **今日工作暂停，不写任何计划（主账户/Maker 都不写）**，报告只记"门禁关闭·今日观望"+原因（5/25 身体疲惫、5/21 团建收缩机制即此类）。
   - 门禁=开启且**当日心力行**异常=「收缩机制」 → 降频/观望，报告注明。
   - 门禁=开启且正常 → 进入工作流第 2 步（主账户 plan）。
   - 🟥 **心力状态按自然日隔离，禁止跨日继承**：仅日期等于报告日期的心力行可干预当日报告；当日查询结果为 0 行时，只记录“今日无心力记录”，不得把前一日或更早的收缩机制、复盘机制、双重异常外推至今日。历史心力只能作为后附事实，不得改变今日主账户/Maker 方向、技术评分、胜率、是否挂单或风控结论。

### 0.1 原始证据共享与全量分析协议（2026-06-30）
> 🟥 **2026-06-26 前本地 Word 金标的正确用法（2026-07-04 修正；2026-07-06 加硬）**：金标只代表已经学习并固化的思考方式、推理逻辑和维度，不是每次报告重新读取旧 Word/旧 combined 的运行输入，也不是 MD 生成后为了“像金标”补字数、补价位、补 rubric。六源采集与 `prepare` 完成后、正式 MD 动笔前，必须以 `scoring/golden_report_reasoning_alignment.md` 的压缩契约组织推理，并先形成内部 `runtime_state/<date>/reasoning_work_<slot>.md`；随后运行 `session_runner.py certify-reasoning` 生成 `reasoning_readiness_<slot>.json`。`combined.md` 只能在 readiness 之后生成；后补理由、后补 rubric、后补任何推理均视为违背交易系统底层逻辑。`lock-analysis` 校验 `golden_reasoning` 与 `reasoning_readiness` 均早于报告文件。旧样本不得进入每次报告上下文，节省 token；表面长度/锚点检查只能 WARN，不能作为质量证明。推理方式、深度和维度硬对齐；旧 Word/冻结金标的格式只要求接近 100%，但字段含义、交易参数、Word QA 与 Notion 发布校验仍是硬门。

1. `context_pack.py` 只提取交付连续性、权威文件哈希与分阶段读取计划，不复制台账中的方向、评分、胜率或计划；context 包只有在 `context_log` 哈希和权威 manifest 哈希同时未变时才允许复用。
2. 早报建立来源基线；午/晚在采集层做 delta，但 delta 的含义是全六源重新采集后比较变化指纹、必要时一次 full fallback，不是跳过某个源或复用前序截图/JSON。`current.json` 仅保存来源清单、指纹和运行事实元数据。
3. 数据源 SHA-256 与依赖图只解释“哪里发生变化”，绝不授权复用分析。三节点每次固定重算完整分析图。
4. 分析结论与决策分别归档为 `analysis_<slot>.json`／`decision_<slot>.json`，均为 post-lock only，禁止进入下一节点分析前上下文。
5. 采集完成后、进入源验真前必须确认宿主为最高可用模型且 Effort=`Max`，并以 `session_runner.py prepare ... --capture-manifest <精确路径> --lease-token <token> --max-reasoning-confirmed` 留下机械确认；缺任一项硬停。从源验真至审查结束全部使用 MAX 思考预算。
   `prepare` 会同步启用 `runtime/prelock_guard.py`：在分析锁建立前，`sessions/context_log.md`、前序 `analysis_*.json`／`decision_*.json`、前序 combined/payload/render 输出会被临时移入 `runtime_state/<date>/.prelock_quarantine/<slot>/`，并记录 `runtime_state/<date>/prelock_guard_<slot>.json`；该 manifest 同时写入 `runtime/prelock_read_policy.py` 生成的安全读取策略。任何人工或自动化不得绕过、手动恢复或读取隔离区内容。默认 `rg` 受 `.rgignore` 保护，隐藏 archive/old outputs/runtime_state/reviews 等已知污染面；若维护审计必须使用 `--no-ignore`，只能在非日报正式分析上下文中执行。`lock-analysis` 成功后自动恢复给锁后连续性/独立审查使用；`abandon-session`／`recover-session` 必须恢复后退出。
6. 🟥 **pre-MD 推理就绪门（2026-07-06 午报起）**：正式 `outputs/<date>_<slot>_combined.md` 生成前，必须先完成内部推理工作稿 `runtime_state/<date>/reasoning_work_<slot>.md`，覆盖六源准确性、pivot/CVD/SMA20/VRVP 承重点、盘口/盘面/总分合成链、胜率 rubric 链、方向反证/失效路径、风险验算。随后运行 `session_runner.py certify-reasoning --date <date> --slot <slot> --work-file runtime_state/<date>/reasoning_work_<slot>.md --capture-manifest <精确路径> --lease-token <token> --confirm-six-source-accuracy --confirm-critical-data-calibrated --confirm-score-winrate-risk-refutation --confirm-no-formal-md-written --confirm-no-posthoc-reasoning --confirm-max-reasoning`。缺 readiness 或 readiness 晚于 MD，`lock-analysis`、Word render、Notion publish 全部硬停。
7. 完整独立分析和 combined.md 通过 lint 后，必须先运行 `session_runner.py lock-analysis` 建立与报告哈希绑定的分析锁，再允许读取前序计划。
8. 锁后完成撤旧挂新／漂移对照；晚报同时完成三段独立审查。运行 `session_runner.py finalize-post-lock` 后才可 commit；缺分析锁、post-lock 门、六源覆盖或任一完整分析节点时硬停。
9. 最终 Notion 唯一页、冻结 verifier、Word 视觉 QA 和 `context_log.md` 最终记录全部完成后，必须运行 `session_runner.py deliver` 写入最终交付遥测。
10. 运行命令以本 SOP 与 `.agents/skills/daily-report/SKILL.md` 为准；`.claude/skills/daily-report/SKILL.md` 仅为本机 Claude Code 兼容镜像，不得覆盖 committed Codex 权威。业务逻辑、三报告、模板、Notion 四子页及三门不变。
11. 🟥 **报告／数据源独立性与时间锁（2026-06-30 用户拍板）**：每份报告绑定唯一不可变证据快照（交易日＋slot＋真实采集时间＋来源 SHA-256）。早／午／晚的报告与数据源均相互独立；后续时段采集不得覆盖、替换、补鲜、重新解释或替前序报告通过 freshness 门。分析锁建立后样本时间与来源冻结，发布延迟不改变样本时点；Notion、Word、台账和 deliver 必须使用同一报告哈希及同一 slot 快照。用户明确要求继续交付已锁定时点报告时，不吸收后续采集。工程实现与验收见 `memory/report-evidence-time-lock.md`。

---

## 1. 六源数据采集（唯一路径，按源对号入座）

### ①②③④⑤⑥ BlockBeats / Coinglass / Exocharts / FedWatch / Farside BTC ETF Flow / TradingView — **统一自动采集**
🟢 **2026-07-05 起六源全部自动抓取**（机制/坑全见 `memory/browser-capture-toolset.md`）：
- **命令**：先 `begin-session`，早报运行 `node tools/browser_capture/capture_all.js --slot morning --lease-token <token>`，午报运行 `node tools/browser_capture/capture_delta.js --slot midday --lease-token <token>`，晚报运行 `node tools/browser_capture/capture_delta.js --slot evening --lease-token <token>`（工具在 `tools/browser_capture/`）。用 PowerShell/Bash 跑、**必须前台 + 关沙箱（dangerouslyDisableSandbox）**。禁止旧 `npm run all` / `npm run delta` 无租约快捷入口。顺序＝BlockBeats → Coinglass → Exocharts → FedWatch → Farside BTC ETF Flow → TradingView → 清算热力图辅助源。
- **BlockBeats 产物**：`blockbeats.png` + `blockbeats.json`。🟥 任何早报／午报／晚报及单源重采，只要发生 BlockBeats 抓取行为，均须先勾选页面「重要快讯」，并覆盖抓取前 12 小时内所有可加载重要快讯；截图必须显示已勾选，JSON 必须包含 `"important_only": true`、`"capture_window_hours": 12`、`"window_covered": true`、不少于 3 条 `candidate_rows`、正好 3 条 `selected_rows`，且 `rows` 必须等于按基本面影响优先级筛出的 selected top3。未勾选、勾选状态丢失、12 小时窗口不足、top3 缺失、`rows` 与 `selected_rows` 不一致或字段不合规均按核心源无效硬停，禁止退回未筛选快讯、只看最新几条或缩短窗口。完整契约见 `memory/blockbeats-important-only.md`。
- **前置**：TV/Exo 登录态长期存在 `~/.tv_chrome_profile`；跑前确认这几个独立 profile 的 Chrome 窗口已关（独占锁；与你日常 Chrome 默认配置互不影响）。
- 🧹 **采集前自动清理（`cleanup.js`）**：动态图(inbox 7 张 + blockbeats 快讯卡)读完/推完即无长期价值，`capture_all.js`/`capture_delta.js` 每次采集前只删"日期<cutoff"的过期图、保留最近 `CLEANUP_KEEP_DAYS` 天(默认 2=今天+昨天)，绝不碰当天在用的图；也可 `npm run cleanup` 手动。两处目录均已 gitignore、不进库。
- 🧹 **交付后自动保留期清理（`session_runner.py deliver` 自动触发 `runtime/report_retention.py`）**：报告交付完成后，除本地 Word 底稿 `outputs/<date>_<slot>_render.docx`、Notion 页面和必要交付/租约/automation 最小状态外，六源截图、combined 草稿、HTML 审查报告、执行中间 JSON、Word-QA 图片/PDF、publish attempts、一次性 `_*.py` 等可再生重物料只保留最近 `REPORT_RETENTION_KEEP_DAYS` 天(默认 2)。`deliver` 成功后自动真实清理并写 `runtime_state/<date>/retention_cleanup_<slot>.json`；排障时才允许临时加 `--skip-retention-cleanup`。
- 🟥 **采集后验证门（接六源硬停·防把登录墙/空图/陈旧当数据读）**：Read 每张确认是**真实登录态正确图/结构化数据**——Exo 须 Bybit BTCUSD·Bid-Ask·有 VWAP/Footprint 统计·非"delayed 24h"·非默认 BitMEX；TV 四档须有手绘线/正确周期·非"需要登录"墙；Coinglass 须干净 4 面板·1H；CME 须工具概率表已渲染；Farside 须同时存在 `farside_btc_etf.png` + `farside_btc_etf.json`，JSON 标题匹配 `Bitcoin ETF Flow (US$m)`、Total 列可解析、latest 日度净流入/流出为数值。**除 FedWatch 浏览器渲染故障外，任一核心源失败 = 该源缺失 = 按六源硬停规则**（`memory/five-sources-complete-or-halt.md` 兼容旧名）→ 重登或回退该源用户手动截图；**绝不拿登录墙/空图/陈旧图当数据读**。
- 🟢 **FedWatch 固定回退（2026-06-28 用户拍板）**：若 `fedwatch.png` 为浏览器错误页、空白页或 iframe 未渲染，先重试 1 次；仍失败则允许全网检索**当日权威数据**补全，不再因单一截图渲染故障硬停。来源优先级：① CME Group 官方 FedWatch 页面/API/官方发布；② Federal Reserve 官方资料；③ 能明确标注数据时点并直接引用 CME FedWatch 的主流金融数据源。必须记录来源 URL、采集时间、下次 FOMC 日期、各目标利率区间概率及相对 1 日/1 周/1 月变化；至少两处权威来源交叉核验关键数字。不得使用搜索摘要、旧闻、无日期转载或模型估算。替代数据写入 `data_sources/inbox/<当天>/fedwatch.json`，标记 `capture_mode=authoritative_web_fallback` 和截图失败原因；`fedwatch.png` 保留作故障证据但不得当有效图引用。
- `capture_all` 走**独立 Playwright/Chrome、不经 Claude-in-Chrome 扩展**；六源均走此唯一路径。
- 🟥 **采集只取图、判读口径全不变**：以下各源读取法、盘口锚点 3 问自检、81/16 组合、评分门槛一律按原逻辑执行（纯采集层改动·思考零改）。
- ② Exocharts：BTCUSD 日线 footprint → 读 POC / Delta / CVD / 日波幅。
- ③ Coinglass：BTCUSDT **1h** → 读 CVD / 价格 / 资金费率 / OI 四维。
  - **读取法（2026-05-31 修正）**：CVD / 价格 / OI 三维起始点取该面板**最近一个阶段性高点或低点**，按趋势线斜率读 **上升 / 横盘 / 下降**（不用 24h% 等绝对阈值，不要求精确数值）；起始点优先用截图上手绘的趋势线。
  - **资金费率例外**：仍读零轴正负（正 / 负 / 近零），供 C01/C02 背离判定。详见 `agents/footprint_agent.md` §统一读取法。
- ④ FedWatch：下次 FOMC 概率表 + 1日/1周/1月变化。
- ⑤ TradingView：**15m**（盘面执行最终 Check，入场把关）。若用户给 4H 先用着，但提醒补 15m。

---

## 2. Notion 读取（门禁/心力前置；持仓仅限锁后校准）— REST API only

- **永远走 REST API，永远用 PowerShell `Invoke-RestMethod`。**
  - ❌ 不调 `mcp__...__notion-*`（连接器一直 403，已弃用）。
  - ❌ 不用 `python3`/`python`（本机是 Windows 商店 stub，curl|python3 静默返回空）。
- **令牌唯一**：从环境变量 `$env:NOTION_TOKEN` 读取（**禁止把 token 明文写进任何入库文件**）。本机未设时临时设置：`$env:NOTION_TOKEN="<你的_ntn_token>"`（仅当前会话有效、不落盘）。token 由用户私下提供，对话里出现的其它串忽略；除非报 401 才换。
- **header**：`$tok=$env:NOTION_TOKEN; @{ "Authorization"="Bearer $tok"; "Notion-Version"="2022-06-28"; "Content-Type"="application/json" }`
- **持仓在两库**（只允许 `lock-analysis` 成功后读取；取最新一条，按 created_time desc）：
  - （主）交易Check：`212fda35-a098-809f-bb92-c681fad1b12f`
  - （Maker）交易Check：`21bfda35-a098-8062-a0a5-c7cb3f3e1f34`
- **只取需要的字段**，不要 dump 整页原始 JSON（rich_text 注解极占 token）：
  - 状态 / 交易策略 / 持仓量 / 杠杆 / 盈亏比 / 计划起始时间
  - 描述（复盘）= 均价·TP·SL / 浮盈防守计划
- 逐日手写判断（对照用）在主账户 plan page 汇总库；中文 filter body 需 UTF-8 字节，否则 400——能不发 filter 就 `page_size` 取回本地筛。

---

## 2.5 渲染规则（2026-05-31 据 5 月 17 天手写样本落地 · 低风险组）
> 详见 `outputs/2026-05_日报逻辑优化.md`。以下为已确认落地项。
> 🪦 **"判断口径满 20 次对照再定"对照实验已废止（2026-06-10 用户拍板）**：原依赖出稿读用户手写判断累积计数，已被 5/31「独立成稿铁律」切断停滞。用户已在 Notion 建独立栏目作对照数据源，样本够后再让系统读取（届时另设读取方案，不沿用旧的出稿累积对照）。本条不再产生出稿约束。

1. **「不能做」字段 = 禁止追当下最拥挤的一边**，**不再机械抄持仓方向**（17 天证实系统性错误）。
   - ⚠️ **归属 = 当天 Maker 日内，与中线计划无关**（不是主账户大方向输出，别混淆）。
   - ⚠️ **时序 = 写完整篇日报（盘口/盘面/基本面）后最后回填的收口结论**，不是开头先写。
   - 推导树：
   - 出现**背离** → 禁追被挤压的拥挤侧（看涨背离=空头拥挤→禁「做空」；看跌背离=多头拥挤→禁「做多」）。
   - 否则按 趋势阶段 + 价相对支撑压力位置：多头单边且价偏上沿→禁「做多」；空头/破位且价近支撑→禁「追空」。
   - **震荡分两种（2026-05-31 据 10 样本校验·精修）**：
     * 震荡且**无明确方向倾向**（中性/双爆筹码消耗）→ 禁「追多空」（两边都禁，如 3/24、4/24）。
     * 震荡但**有方向倾向**（利多/反弹/诱多，或 利空/破位/诱空）→ **只禁那个拥挤侧**（利多反弹诱多→禁「做多」，如 4/14、5/15；利空破位→禁「做空/追空」）。
   - 「追」前缀=力度区分：**「做X」禁全部该方向**；**「追X」只禁右侧追单**，对侧左侧反应单仍可（行情已延伸时用「追」，趋势刚启动用「做X」如 5/18）。详见 `constitution/cannot_do_mapping.md`。
2. **主账户策略段 = 独立中线计划**：分析锁定前不得读交易Check 最新持仓；先按六源与中线框架独立输出「保持/迭代/暂停/新增计划/观望」等系统计划。实际仓位、防守层级、已成交比例只能在锁后作为操作校准事实，不得改变正文判断。
3. **基本面必带「价格{已/未/部分}兑现」字段**（原模板漏此字段；主线锚定是否取代计数法仍观察）。
   - 🟥 **正文括号精炼铁律（2026-06-19 用户迭代·在 2026-06-12 精简基础上再收紧·纯文字输出层·思考/推理/系统底层框架零改动）**：「基本面：标签（……）价格兑现」与「盘口·解读：标签（……）」**两个括号内只给精炼的核心结论与本质判断**——标签后一句话定性 ＋ 最关键 1-2 个驱动/矛盾本质；**不做"所有信息逐条叙事铺陈"的全量输出**。分维证据、Tier 逐条、各源细节、完整推导链**全部移到 ③ 后附**（本地 docx·不进 Notion 正文）。**无字数限制——抓到核心本质即可、不卡死字数**（取代 06-12 的"约 150 字内"上限）。⚠️ **只动括号内文字密度，不动 Notion 块结构/金标块数/run 结构/配色**——基本面仍 1 个 heading_3、解读仍在原块内括号、verifier 门①不受影响（6/2 金标本就把全部基本面/盘口推理装在这两个括号内）。🟥 **逻辑推理深度、六源全读、81/16 组合判定、评分/胜率/门槛推导一律按原系统逻辑全量执行**——详尽推理只换地方放（进 ③ 后附）、绝不缩减。🟥 **正文禁元叙事（2026-06-19 用户追加）：日报正文（基本面/解读括号 + 盘面 + 趋势 + 策略 + Maker 全段）禁出现"内部规则/铁律/方法论/评分代号/门槛判定"的元叙事**——禁写 C25/52分/极端候选/价格锚点法/背离合成引擎/投入产出比/参 rebound-short-highest-edge 等规则引用，禁写"双门槛全满足→必挂"/"门槛①②"/"≥65门槛"/"(20xx-xx-xx铁律)"等机制措辞；正文只用自然语言给结论与本质（像给执行者直接看的 plan）。组合代号(CXX)/方法论名/评分分项/门槛判定/规则出处全部只进 ③ 后附（6/2 金标本就是干净写法；6/18 稿把这些写进正文＝漂移，须回归金标）。🟢 **金标字段豁免**：Maker 段首行 `执行概率X%（已执行X%）　胜率X%` 是 Notion 金标固定字段·照写不算元叙事（被禁的是另塞的 总评分/C代号/门槛①✔/双门槛→必挂）；观望日 Maker 段只写「观望·不挂单＋一句自然语言理由」，分数/胜率自估值/哪项未达进 ③ 后附；门禁评分的稿首 `>` 自查摘要属内部工作笔记·不入 Notion 正文·不在本约束内。🪦 06-12 旧口径（基本面"标签＋Tier1 1-2条＋对冲1条＋价格兑现"、解读"组合结论＋四维一句话证据＋保留项"、各约150字内）仍是有效下限参照，06-19 进一步要求"括号内只留结论本质、细节全进③后附、不卡字数、且禁元叙事"。见 `memory/fundamentals-brief-core-priority.md`。
   - 🟥 **正文一律中文铁律（2026-06-25 用户迭代·纯文字输出层·思考/逻辑/评分/框架零改）**：日报 Notion 正文（①正文 + ②Maker）所有可中译叙事术语必须写中文；保留指标缩写、模板字段/账户名和新闻专有名词。③后附明细和方法论文档可保留英文。机械强制由 `outputs/report_lint.py` 正文英文术语门执行；见 `memory/report-chinese-only-narrative.md`。
4. **支撑/压力恒为区间** XXXXX-XXXXX（宽约 300-500 点），不输出单点。
5. **盘面两层各以单字结论收口**：日线层 + 小时层，每层末尾给「中性/利空/利多」。
6. **Maker 段按用户 Notion 条目完整字段输出**：交易策略(做空/做多·高空/低多/反弹空) ｜ 开仓方式(Maker) ｜ 交易类型(左/右) ｜ 杠杆 ｜ 持仓量 ｜ 盈亏比(≥1:2.5) ｜ **入场区间** ｜ **止盈(TP1 减仓50%／TP2 清剩余·帐 100% 闭合)** ｜ **止损** ｜ **浮盈防守计划(第一层/第二层·只移损/保本损/取消加仓·禁减仓%)** ｜ **注意事项(取消价)** ｜ 核心(开仓理由)。
   - 「已执行X%」是本报告这张新计划发布后的成交比例字段，分析锁前默认按新计划写 0%；禁止用 Notion 既有持仓/已成交比例填充或改变 Maker 结论。
   - 🟥 **仓位帐一致性=金标口径锁死（2026-06-11 用户发现双扣矛盾后拍板·禁止飘移）**：仓位扣减**只在止盈档**（TP1 减仓50% → TP2 清剩余50%·全计划帐 100% 闭合）；**浮盈防守层只"移止损/保本损/取消加仓"、禁写任何减仓/平仓百分比**（6/2 冻结金标即此口径；6/3-6/10 曾漂移回 6/1 旧手写措辞"第二层减仓50%+保本损"与 TP1 双扣、TP2 成死条款＝飘移事故）。审查/复盘表述："价格触及 TPx"≠"仓位捕获至 TPx"，仓位已在 TP1 全部离场则禁写"TP2 命中·完整兑现"。门② lint 含此硬检查。见 `memory/defense-layer2-vs-tp1-conflict.md`。
   - 🟥 **第一层防守级别锁死（2026-07-04 事故修复；2026-07-06 用户补充底层逻辑）**：Maker 浮盈防守第一层必须写 **成交后后续形成并确认的4H级别K线结构性极点**；空单用成交后确认的 4H 极点高点，多单用成交后确认的 4H 极点低点。第一层必须有具体触发价、成交/入场后形成并确认的4H极点规则、取消所有加仓；**禁止预填第一层移动止损的具体极点价**，禁止把历史 4H 高/低点、当前未完成 K 线高/低点、1D high/low 或任何报告生成时已存在的价位当作未来防守止损价；禁止写 1H、1小时、15m、15分钟或笼统“小时级别”。第二层只设保本损。
   - ⚠️ **「取消价(注意事项)」≠「止损」（2026-06-01 用户纠错）**：取消价=挂单**成交前**失效价（价格优先触及反方向某位→撤掉未成交挂单，如"优先跌破71,000则取消"）；止损=**成交后**离场价（第一层只能写"触及X后，移动至成交后后续形成并确认的4H级别K线结构性极点"，不得预填未来极点价；受宪法"单笔3%以内""浮盈≥+1.5R 才激活防守层"约束）。"站稳XXX上方=结构失效"是止损，别误标成取消价。
   - 🟥 **精确数字铁律（2026-06-02 用户拍板）**：报告里所有价格/百分比必须是核对过的确切数字；禁止 `71,2xx`、`712XX`、`@~71,7xx`、臆造 `~3%` 或具体价格位写 `73k`。现价取最新最细粒度图的确切收/现价；入场、止盈、止损、防守层触发价由六源和风险参数推导。出稿前自查无模糊数字残留；见 `memory/precise-numbers-no-fuzzy.md`。
   - edge 是资金保全（5 月成交 9 笔=盈2/保本5/亏2，7/9 不亏），不是高胜率；写到可执行单粒度。
7. **盘口 footprint 表的 Coinglass 四维呈现为「上升/横盘/下降」**（按阶段性高低点斜率读，1H 周期），**资金费率双轨**=趋势「上升/横盘/下降」+ 水平「（为正值/为负值/低于正常值）」一起写（5 样本校验：你实际写法即"资金费率下降（为负值）"）；读数后跟一句文本含义，不要求精确数值。⚠️ 注意：旧稿常把 OI 写「稳/偏升」(24h 口径)，新口径须从最近阶段高/低点判（如 5/28 峰 62K→56K 应读**下降**）。
8. **框架优先级按账户分流**（权威：`constitution/trading_constitution.md` §一·补）：
   - **日内 Maker：盘口>盘面>基本面** —— 方向由盘口70+盘面30 定，基本面只作风险否决/降频，**不打方向盘**。
   - **中线主账户：基本面>盘面>盘口** —— 中线大方向以基本面先导，盘面定入场区，盘口仅择时微调（禁据盘口短期背离推翻中线方向）。注：「不能做」不属中线，是当天 Maker 末位收口结论（见本节第 1 条）。
   - **基本面内部：政治(地缘/升降息/监管立法)>行业资讯**；Tier1 政治主导方向，Tier2 行业不得翻转（详见 `agents/news_agent.md`）。

## 3. 评分（70+30）与出稿
- 盘口 70（footprint 16 组合；C01/C02 极端=自动70，其余手动）+ 盘面 30（接近度10/掠夺10/SMA20·5/量价3/斐波2）。
- **总分 ≥65 且 胜率自估 ≥60%（双硬门槛全满足）→ 必须挂 Maker 单**（方向由盘口定，挂价=⑤源高质量边缘；Maker 限价单挂边缘等待、价不到不成交，天然满足"入场位置要求极高"，**位置不优只改挂单价、不改是否挂单**）；**总分 <65 或 胜率 <60% → 观望不挂**。执行概率 ≥50% 为软参考·非门槛（只定挂价可达性、够不到也照常开单）。门禁关闭/收缩/风控阻断优先于此（即便双门槛满足也不挂）。2026-06-01 确立必开制·2026-06-16 总评分门槛70→65+胜率升级硬门槛+执行概率降软参考，见 `memory/score70-must-place-maker.md`。
- **盘面分析只有两层：日线级别 + 小时级别**（Notion 固定格式，6 样本核实）。15m 只属于 TradingView 源内部执行 Check，不要写成「盘面·15m级别」。
- 出稿：python-docx（`py` 运行，字体 Microsoft YaHei）。正文按用户 Notion 手写格式（主账户段 + Maker 段在文首可直接复制），后附评分明细/六源支撑。
  - docx 被占用报 PermissionError → 换新文件名。
  - 生成后用一条命令确认文件存在即可，不要反复 Read/Glob 验证。

---

## 4. 省 token 纪律（本次踩坑总结）
> 本节只管确定性机械动作。不得据此减少采集后的验真、读图、转录、分析、评分、胜率、风险、情景、决策、成稿与审查预算。
1. **不并行重复调用**：一个动作发 1 次，看结果再决定下一步。禁止"先多发几个保险"。
2. **不发探针**：不要 `echo probe` / 重复 `list_connected_browsers` 试连接。
3. **已知会失败的不试**：MCP-notion、python3、Chrome 扩展采集日报源。
4. **不重复 Read** 同一文件；Edit/Write 成功即生效，不回读验证。
5. **读 Notion 抽字段，不 dump 全量 JSON**。
6. 临时中转文件（`sessions/_*.txt`）用完即删。

---

## 5. 收尾
> ⚠️ 本节为 committed 权威全文；`.claude/skills/daily-report/SKILL.md §6` 仅作本机兼容镜像。灾备重建只读本文件 + `.agents/skills/daily-report/SKILL.md` + memory 也必须能复原三门。改任一处必同步本文件、Codex SKILL 与对应 memory。

### 5.1 Notion 归档（机制·见 `memory/push-report-to-ai-agent-plan.md`）
- 唯一路径＝`import outputs/notion_push_lib.py` + `py`；token 走 `$env:NOTION_TOKEN`。
- 2026-06-29 起新报告使用参数化入口：三张卡片=`outputs/generate_cards.py`+JSON 内容；Daily Notion payload 唯一生成入口=`py outputs/daily_payload_builder.py outputs/<date>_<slot>_combined.md`，再由 `outputs/publish_report.py` 发布。`combined.md` 是 Notion 正文唯一真相源；payload 必须带 `payload_source.kind=combined_md_to_notion_payload`，发布器会重新从 combined 派生签名比对，任何手写 `children`、空块、增补 combined 不存在的 Maker/边界字段都会硬停。禁止继续复制或新建日期专用 `_make_blockbeats_cards_*.py` / `_notion_push_*.py` / `_prepare_*`；活工作区不保留这些旧可执行入口，历史审计以 `context_log`、publish manifest 和 Git commit 为准。底层事务替换、三门和四子页结构不变。
- 🟢 早报直接建 `🌅` 子页写入（不平铺到日期页）→ 午报新增 `🌇` 子页 → 晚报只新增 `🌙`+`🔍`，四子页同级共存、永不迁移（2026-06-20 三节点）。午报用 `push_subpage(date_str, "🌇 2026.M.D 午间", ...)`，去重前缀 `🌇`。
- 🟥 正文发布结构＝字段含义/块序/快讯卡/配色机械门通过；旧 Word/冻结金标版式只要求接近 100%（见 `memory/basemian-needs-news-cards.md`）：早报/午报对早间骨架、晚报对晚间骨架；「基本面」后 3 张快讯卡；块型与逐 run 配色沿用既定唯一规则。2026-07-05 起参数化发布必须在写入 Notion 前套 `daily-gold-run-colors-v1`：标签默认色；基本面括号内理由整段 yellow，只有独立的「价格已兑现/价格已部分兑现」短语 green；日线/小时级别的关键技术判断句（如重新站上/跌破 SMA、趋势线压制）单独上色；趋势确认整段结论按主方向上色；支撑/压力/止盈/止损/策略/注意事项按 6/2 手写金标 run 级分布上色；禁止把整段 heading 或 Maker 行粗暴染成同一种颜色。
- 🟥🟥 **同名页事务式替换（2026-06-27 根因修复）**：统一调用 `replace_page_transactional(...)`，严格按「snapshot 全部旧页 → 唯一 staging 标题建新页 → 上传三图 → `verify_published` → 改最终标题 → frozen verifier → 归档全部旧页 → 同前缀唯一存活检查」执行。**禁止先归档旧页再 create_page**。准备阶段失败只回滚 staging 页并保留旧页；提交阶段清旧失败则保留已验证新页并硬停，宁可短暂重复、不可全失。
- 🟥 **日报正文 Notion 写入前硬门**：`assert_source_freshness(...)`（核心评分源≤4h；BlockBeats/FedWatch至少当日）→ `run_report_lint(...)`。任一失败立即退出，不允许静默跳过或以“仅推送”名义发布过期可执行计划。晚间独立审查页走 §5.3 的 review contract，禁止套用日报 freshness/lint/source-binding 门。

### 5.2 机械三门＝完成判据（宪法级·全 PASS 才算完成、才回复用户·见 `memory/stability-contract.md` 与 `memory/notion-publish-checklist.md`）
- **门②反幻觉 lint（push 前硬门）**：`py outputs/report_lint.py outputs/{date}_{morning|midday|evening}_combined.md` → `[PASS]`（0 HARD）才能 push；WARN 逐条人工确认。**含 Maker 仓位帐门（2026-06-11 加）**：防守层出现减仓/平仓百分比、或 TP1 部分止盈而无 TP2 清仓档（帐不闭合）＝HARD。
- **门①结构+配色（push 后硬门）**：`py outputs/notion_verify_against_yesterday.py <今日page_id> morning|midday|evening|review`（午报用 `midday`·复用早间 28 块金标）→ 对照 **2026.6.2 冻结金标**（非昨日·防错误逐日传播；金标 id 在脚本 `GOLD` 字典）逐块比对类型/块数/图数 + `daily-gold-run-colors-v1` run 级配色分布 + 语义配色按情绪词唯一规则逐 run 校验。`[PASS]` 才算完成；`[FAIL]`/`MISMATCH` 必改 push 脚本→归档重建→重跑到 PASS，绝不带 FAIL 交付。
- **失败码铁律（2026-06-27 根因修复）**：verifier PASS＝输出 `[PASS]` 且进程退出码 0；`[FAIL]`／异常必须退出非零，调用方必须传播并回滚 staging。禁止仅凭日志字符串自行打印“PASS”。
- **Word 视觉门（2026-07-02 整链修复；2026-07-05 底稿结构硬门）**：唯一入口为 `render_from_combined.py <combined> --date <date> --slot <slot>`，唯一产物为 `outputs/<date>_<slot>_render.docx`。渲染前由 `outputs/report_structure_gate.py` 硬拦：人类可见标题必须为 `YYYY.M.D 早/午/晚间日报`，combined 必须保留 `## ① 正文` → `## 不能做` → `## ② Maker 计划` → `## ③ 后附` 骨架，禁止裸 `---` 渲成 Word 文本，禁止 2026-07-05 起任何报告仍写“五源”，③后附必须覆盖 BlockBeats／Coinglass／Exocharts／FedWatch／Farside／TradingView 六源。渲染后再次抽取 DOCX 段落结构校验同一骨架；源稿＋渲染器＋结构门哈希一致时直接复用，最多两次，第三次硬停。随后只运行 `word_qa.py export`：本 Windows 主机确定性选择隐藏 Word COM（不先试 LibreOffice）＋Poppler；在 MAX 下逐页查看 manifest 中的 PNG 后才运行 `word_qa.py approve`。禁止生成 V2/V3/report/中文名 DOCX 副本或日期专用 VBS/PS1。只验 ZIP/XML 不算视觉 PASS。
- **门③回复前自查**：模板对齐/独立成稿/六源齐/精确数字等清单自查。
- ⚠️ verifier 与 lint 脚本禁 print emoji（PS 控制台 GBK 崩）。

### 5.3 晚报链 B 专属·必做（见 `memory/evening-review-visual-to-notion.md`）
- 晚报收工额外产《Notion 原生块独立审查报告》：去系统逻辑；不再生成 HTML/截图/Word/PDF 审查产物；只记入当日日期页子页 `🔍 ...晚间独立审查（倒推）`（与🌅/🌇/🌙同级）。早报/午报不出审查。
- 🟥🟥 **倒推范围＝三段·缺一即口径违规（2026-06-20 随午报新增节点·由双段扩为三段；原双段铁律见 2026-06-12 锁死缘由）**：**段一＝前一天晚报**（隔夜→今日走势检验）＋**段二＝当天早报**（早→午走势检验）＋**段三＝当天午报**（午→晚走势检验）；缺某一节点稿时按实际存在的相邻报告顺次单/双段（如午报缺则退回双段·6/10 单段先例同理）。评分表/价格阶梯/关键发现三段都须覆盖。
- 🟥 **独立审查发布硬门（2026-07-06 根因修复）**：`review` 不再走 non-daily skip。先写 `runtime_state/<date>/evening_independent_review.json`（`evening-independent-review-v2`），再用 `py outputs/review_payload_builder.py runtime_state/<date>/evening_independent_review.json` 生成 payload。发布前 `outputs/review_contract.py` 必须通过：首表为五维×三段评分，价格阶梯表覆盖三段，`review-font-rendering-v1` 必须逐项校验 `rich_text.annotations.color/bold`（评分表分数、价格阶梯三段标签/审查意见、六条发现、边界、结论均不得默认无样式），用户可见内容不得出现 runner/锁/commit/payload/verifier/Word-QA/context_log 等系统执行词；`payload_source` 必须绑定 manifest、report hash 与 children signature。review 发布不得要求或验证日报 `source_specs`、不得触发日报 freshness/lint/source-binding 门、不得改动早/午/晚任何报告产物。发布后 `py outputs/notion_verify_against_yesterday.py <page_id> review` 必须用同一 contract 拉取 table 子行并校验字体颜色到 `[PASS]`，否则归档重建。

### 5.4 收尾杂项
- render manifest、Word QA manifest（`status=passed`）、publish manifest、线上 verifier＋唯一存活页全部形成后才写 `context_log.md`（倒序，新日期块在顶）；必须写最终 page id、发布时间与 PASS。`context_log` 与 delivery 的时间必须晚于真实 DOCX／PDF／PNG／视觉审核证据，禁止在证据出现前声明 PASS。
- 每份报告采集前必须持有 `begin-session` 整链租约；午报/晚报仅在前一时段 delivery 完整后才能开始。deliver 机械核对 DOCX/QA/publish/context_log 哈希闭环后才释放；中断用带原因的 abandon/recover，禁止自动抢过期锁。
- 若同一日期/时段的六源采集已经成功生成不可变 manifest，但后续 hard stop 已把原 lease 关闭，不得手改 manifest、不得复制 evidence、不得伪造 lease。只能通过 `session_runner.py recover-session --date <date> --slot <slot> --from-lease-id <capturing_lease_id> --reason <明确原因>` 建立带 `recovered_from_workflow_lease` 的新 lease，然后用新 token 对同一旧 manifest 运行 `prepare`；`prepare` 必须在 transition 中记录 `capture_lease_recovery`。归档 lease、日期、时段、manifest 任一不匹配则硬停并重新采集。
- 每阶段通过 `runtime/usage_logger.py` 记录耗时、重试、真实全量回退及宿主真实提供的 token；宿主不提供 token 时写 `null`，严禁估造。至少覆盖 `render_docx`、`word_export`、`visual_qa`、`publish`、`delivery`。Token 优化只评价机械层，分析层以质量和 MAX 合规为先。
- 更新 memory（若有新坑/决策）。
- ❌ 默认不 commit；**仅当用户明确要求才 commit**，且推送脚本里的 Notion token 必须读环境变量、绝不硬编码进库。
- 清临时文件（`sessions/_*.txt`）。同日与保留期内不得删除动态图、锁定 evidence snapshot、capture/prepare/analysis/render/Word-QA/publish/delivery manifest。超过保留期后由 `session_runner.py deliver` 自动执行保留期清理；该清理长期只保留本地 Word 底稿、Notion 页面、`context_log.md`、delivery/lease/automation 最小状态，不清理当前日报仍需回查的证据。人工可运行 `py runtime/report_retention.py --json` 审计，但日常不再等待用户单独下清理指令。

### 5.5 收工触发器（Claude Code 旧机制平移到 Codex）
- 用户说「收工」「如无问题即收工」「完成后收工」，或助手准备回复“完成/已交付”时，必须触发本节；不得把“我认为差不多了”当完成。
- **日报交付型收工**：必须同时满足 `report_lint`/时效门、canonical render manifest、Word-QA `status=passed`、publish manifest、线上 verifier `[PASS]` 且退出码 0、同前缀唯一存活页、最终 `context_log.md`、`session_runner.py deliver` 成功、`retention_cleanup_<slot>.json` 形成、`sessions/_*.txt` 清理完成；晚报还必须完成 §5.3 独立审查 manifest/payload 与 Notion 子页，不生成 HTML/截图/Word/PDF 审查产物。缺任一项＝未收工，只能报告阻塞点。
- **工作流维护/审计型收工**（不发布日报时适用）：必须完成本次范围内的权威文件/测试/审计更新，跑相关回归检查，若用户明确要求 commit 则只 stage 本次范围文件并提交；最终回复必须列出验证结果、commit hash（如有）和仍存在的无关脏文件边界。
- 完成回复只允许基于真实工具输出和 manifest；禁止用布尔自证、口头 PASS、未验证截图或未核 exit code 代替证据。
