# vNext 日报生产工作流合同

## 1. 目标

在不牺牲交易宪法、六源方法论、推理深度和交付质量的前提下，消除旧链路的共享路径覆盖、隔离/恢复碰撞、格式失败重跑分析、下游故障重复采集以及 fail-first 修复循环。

本合同只定义 vNext 影子链。通过正式验收前：

- 不修改当前日报自动化入口；
- 不发布 vNext Notion 页面；
- 不替换旧 `runtime`；
- 不删除旧审计证据；
- 自动化继续保持暂停。

## 2. 单一真相源

| 层 | 真相源 | 不允许替代它的内容 |
|---|---|---|
| 证据 | `evidence-snapshot-v1` | Prompt 摘要、旧报告、旧评分 |
| 方法 | `methodology-manifest-v3` 分离的 `semantic_contract_sha256`、`release_sha256` 与组合 `manifest_sha256`；历史 v2 仅作 immutable combined identity 读取 | ignored 镜像、历史报告事实、从旧 combined hash 反推 semantic identity |
| 推理 | `reasoning-model-v5` 的 observation/claim/scenario DAG、固定 `pipeline_units`、`scenario-ownership-v1` 与结构化触发条款 | 后补理由、自由文本 scenario、渲染层猜测反证或失效条件 |
| 决策 | `decision-model-v7`（绑定 v2 run 身份/哈希/模式，并只接受 closed typed 业务语义） | 手算评分、手算风险、自由 rationale 或正文反推决策 |
| 报告 | `canonical-report-model-v11` | Agent 手写 `combined.md`、reasoning 自由报告段落、把备用源伪装成 CME |
| 正式交付 | `delivery-model-v1` | 口头 PASS、布尔自证 |
| 影子封存 | `shadow-delivery-model-v1` | 伪造 Notion 发布记录、跳过本地视觉证据 |

新 run 只能是 `daily-run-vnext-v2`，并在 `begin` 时显式提供
`run_mode=shadow|production` 与批准引用。运行态只保存批准引用的 SHA-256
和该模式的固定授权类型，不保存批准原文。v1 终态只读兼容；v1 非终态禁止
推断模式或继续执行，只能经显式授权退役后另起 v2 run。

vNext 的运行时阶段仍固定为 `evidence -> reasoning -> decision -> report -> delivery`。
`reasoning-model-v5.pipeline_units` 只是单个原子 reasoning attempt 内部的逻辑
micro-DAG，不是新的运行时阶段；每个 unit 禁止独立 checkpoint、独立 attempt 或
独立 retry。A5-R1 不改变六源采集器、顶层阶段机、`sample_outcome` 学习出口、
Word/Delivery 后端或既有 immutable run。

`reasoning-model-v5` 的生产者可见形状由 `reasoning-submission-contract-v6` 承重，
`reasoning-submission-scaffold-v6` 与 `reasoning-server-projection-v4` 由 reasoning phase 内的
`scoring/reasoning_submission_contract.json` 单独承重。Evidence 密封后、首次
reasoning 模型调用前，运行器必须先执行一次静态 `reasoning-contract-preflight`，
再读取确定性 `reasoning-scaffold`。前者只验证当前 contract、scoring policy 与
runtime handler 是否兼容；后者预填已密封 run/evidence/methodology 的绑定、六源 exact observation
skeleton、authority 常量、六格 scenario 包装和 17 个 unit 的恒定拓扑。二者均不得接收或检查候选答案，不得调用
模型、创建 attempt、写 checkpoint 或生成业务方向、claim、scenario、评分、计划。
不得以候选 preview、草稿校验或 scaffold 补全为名在正式 attempt 之外形成未记账
retry。methodology 的 54 个叶必须穷尽且互斥分类，未分类即 preflight 硬停。正式 attempt 打开后、
Gate 运行前，runtime 只可重绑身份、六源 observation identity、同源密封工件 inventory
`evidence_refs`、结构化源 `structured_binding` 和视觉制品自哈希，投影可从密封身份、唯一 typed owner、
上游 typed 值或 authority 常量机械得到的 methodology identity/mirror/constant、完整
account/scenario subtree、closed orderflow direction 与 `pipeline_units`。模型仍只拥有
`independent_synthesis` 四个选择叶、逐事件 impact/effect/counter 三叶、`transition_summary` 这
8 个业务叶，以及从密封 top3 中选择 assessment 行的 `selected_event_sha256` key；runtime 可据该 key
绑定同 hash realization claim，但不得改写、重排或猜测 key，也不得修复事实、图像判断、claim DAG、
`current_basis`、`trigger_logic`、thesis、counterevidence 或 invalidation。extra field 不删除，
missing model-owned field 不补齐；候选的 exact shape 与业务语义只在该单个密封 attempt 内正式验证。
`evidence_refs` 只是同源密封工件的完整 allowlist/inventory，不证明模型实际读取了每个工件；
具体 `visual_citations`、crop、metric coverage 与结构噪声截图选择仍由模型负责并独立硬验。
`claim-topology-v1` 必须在 contract、preflight 与 scaffold 中对生产者可见，support edge 仍由模型选择，
runtime 禁止注入业务 DAG。`strongest_counterevidence` 与 `invalidation_path` 是同账户并列控制节点：
后者只须可达本账户 `market_regime`，不得隐藏要求其依赖前者；最终 `cannot_do` 仍须显式可达
Maker thesis、最强反证、失效路径和市场状态。typed enum/closed code 是控制事实唯一真相，
对应自由 `conclusion` 或 rationale 仅供审计，不得再用中文关键词反推或否决 typed 状态。

采集阶段只采集六源市场证据，禁止读取开仓前状态门禁、Notion、个人持仓或
订单状态。shadow 全链禁止创建、读取或消费 pretrade contract，固定
`live_execution_allowed=false`、`execution_action=not_attempted`，但
`plan_state=qualified` 时仍必须完整验证并展示 Maker 区间、2–5 档、计划持仓、
5x、TP1/TP2、止损、防守与风险情景。production 只允许在 decision 阶段消费
vNext 原生、同日、哈希有效的个人执行资格合同；该合同只能改变
`execution_action`，不得改变计划是否成立、方向、评分、胜率、价格、风险或
主账户判断。

`threshold_eligible` 只表示总评分不低于 65 且胜率不低于 60%。
`plan_constructible` 还要求 Maker thesis、反证、失效与最终 `cannot_do` 一致，
存在当前 run 的 TradingView 认证 `entry_zone`，区间内有 2–5 档且比例合计
100%，并且所有非空成交组合均通过风险复算。只有两者同时为真时
`plan_state` 才能为 `qualified`；任一为假时输出结构化 `observe` 是合法业务
结果，不是工程失败，且不得为了通过门槛补造区间、价位或风险参数。

## 3. 数据源角色

- BlockBeats：`observation.metrics`只拥有本轮事件事实、时间窗与影响层级四字段；不能凭低层级资讯翻转高层级政治/宏观背景。价格兑现不属于BlockBeats metrics，而由 `fundamental_price_realization` 跨BlockBeats `fundamental_context` 与TradingView `chart_interpretation` 唯一合成并拥有。
- FedWatch：保留为利率预期逻辑槽位兼容 ID；实际 provider 必须由 evidence meta 密封。主源为 `cme_fedwatch_ui`；仅当主源出现 closed eligible 技术失败时才可选择 `kalshi_public_market_data_api` 的 `KXFEDDECISION` Plan C。Kalshi 是独立事件合约市场、非 CME 等价且仅作 observation。两者都只定义宏观环境，不能直接担任 Maker 方向盘。
- Farside BTC ETF Flow：`observation.metrics`只拥有 `latest_complete_date`、`latest_total_usd_m`、`flow_direction` 三个制品字段；`price_relation`只能由同时精确追溯 Coinglass 同锚价格方向与 Farside 流向的 `etf_confirmation` typed claim 拥有。其关系由同锚价格方向×ETF流向确定性生成：`up+inflow`、`down+outflow`为`confirm`；`up+outflow`、`down+inflow`为`weaken`；其余五格均为`neutral`。ETF只能确认、削弱或保持中性，不能单独翻向。
- Coinglass：价格、CVD、OI、资金费率与清算通道。
- Exocharts：足迹与主动成交确认。
- TradingView：1D/4H/1H/15m 结构、SMA20、用户手绘成交量分布区域和入场位置质量；平台内置 VRVP 禁止使用。

用户手绘 VRVP／成交量分布、流动性猎杀、清算地图和 ETF 只能增加判断维度，不得替换原始盘口四维、盘面结构或账户优先级。当前 profile 权威模式为 `user_drawn_manual_only`：平台内置 VRVP 必须隐藏且永不取值；自动 POC/VAH/VAL/HVN/LVN 数值禁止。平台状态不能可靠证明时必须记为 `unknown`，不得误记为 `absent`；profile sidecar 缺失、无效或与本轮证据不绑定时，只允许 `status=insufficient`。

## 4. 四道硬门

### 门一：证据完整性

- 六源齐全且角色不漂移；
- TradingView 四周期齐全；
- BlockBeats 重要快讯和 12 小时窗口成立；
- 推理层的 BlockBeats 事件窗口与入选数量必须机械等于证据快照；
- Farside BTC ETF Flow 最新 Total 为可验证数值；
- CME 主源每时段重新导航官方页面、真实概率工具完成渲染并生成本轮不可变截图，即视为本时段最新页面快照；页面内 `Data as of ... CT` 仅作展示／转录，禁止与主机时钟比较并据此判定未来、陈旧、重采或硬停。只有密封的 closed eligible CME 技术失败可以启动一次 Kalshi Plan C；CME 有效时禁止调用、混入或展示 Kalshi。Plan C 必须保留 API 数据时点、`KXFEDDECISION`、bid/ask midpoint 报价基础、bounded-simplex + `other_unlisted` 归一化、fallback reason 与 provenance hash；不得声称 CME/Fed Funds futures 方法等价，也不得把 `>25bp` 改写成 `50bp`；
- 文件路径、大小和 SHA-256 一致；
- 所有缺陷一次性返回。

### 门二：推理一致性

- observation 必须绑定 evidence 文件；
- claim 只允许引用已定义节点；
- 高影响结论必须有显式反证和失效条件；
- 六源 observation 与账户中立的源解释 claim 属于共享证据层，可以被主账户与 Maker 分别消费；共享层不得引用任何账户专属 claim；
- 主账户与 Maker 的账户专属 claim 只能引用共享层或本账户 claim，禁止跨账户依赖；两条链必须各自拥有 `market_regime`、`strongest_counterevidence`、`invalidation_path` 与完整决策闭环；
- runtime 必须按 authority 固定拓扑生成 17 个逻辑 unit：六源逐源单元 `BlockBeats -> FedWatch -> Farside -> Coinglass -> Exocharts -> TradingView`，随后依次合成基本面、盘口足迹、图表趋势、ETF 关系、日内位置、基本面兑现，再闭合 Main controls/strategy 与 Maker controls/thesis-score-basis/cannot-do。每个 observation、claim 与 scenario 恰好由一个 unit 拥有；scenario input 只来自其 `owner_claim_id`，其它 input、source scope 与依赖由 typed 引用和 support DAG 机械导出，禁止未来依赖、跨账户依赖或模型自报完成/hash；模型提交的 `pipeline_units` 非 authority，认证 hash 只能由 Gate 生成；
- 上述 17 个 unit 必须在同一个 reasoning attempt 内整体提交、整体认证或整体失败。unit 之间只有逻辑拓扑，不得写入阶段 checkpoint，不得单独重试，也不得把局部失败伪装成新的 reasoning attempt；
- reasoning Gate 必须按 `reasoning_submission_contract` 对提交形状做完整聚合：同一候选中可独立判断的 missing、unknown、type、cardinality、enum、最小长度与 policy-value 缺陷必须一次全部返回，不能因第一个字段失败而隐藏同级根因；形状足够后仍必须继续执行既有 business-semantic Gate。静态 preflight 只证明 contract/handler 相容，不代表候选正确，也不得代替本条正式验证；
- `reasoning-model-v5` 要求主账户与 Maker 的 `strongest_counterevidence`、`invalidation_path` 各自拥有 closed typed `trigger_logic`。每个 trigger 只能引用其 support DAG 可达的 observation/claim typed field；主账户必须组合 TradingView 结构与基本面/ETF，Maker 必须组合 TradingView 结构与盘口/足迹，失效必须使用 `mode=all`。对 `long|short` 必须包含当前账户方向的相反类型化状态；对主账户 `neutral` 或 Maker `observe`，future trigger 必须由 TradingView/Coinglass 的绝对方向字段给出唯一 `long` 或 `short` 替代方向，中性辅助条件不能单独充当反证，且 `strongest_counterevidence` 的 future 方向必须与其 `current_basis` 已认证的当前最强反证方向一致。`current_basis` 与 `trigger_logic` 是当前/未来控制语义唯一可见、唯一承重真相；自由文本 `conclusion`/`invalidation` 只供上游门内审计，不得进入 canonical compiler、reasoning proof、scenario condition、Markdown、Word、卡片或任何用户可见出口，也不得根据方向自行猜触发条件；
- `account-trigger-logic-v5` 机械解释组合充分性：`any` 每 clause 独立触发且须单独指向同一反证方向；`all` 可含无方向辅助，但方向条款须同极性，同一 typed field 的 target 交集非空；`one_of_at_trigger` target 须单极性。Exocharts `cross_check_result` 仅在同一 `all` 绑定唯一 Coinglass `final_direction`：reference target 等于认证 current 用 `equals_at_trigger`，不等用 `becomes`；relation 用 `equals_at_trigger`；`confirm` 同向、`contradict` 反向、`weaken` 中性。当前真值按 mode 聚合：`any` 任一 clause 已满足即整组已触发，故全部 clause 均须尚未满足；`all` 仅在全部满足时触发，故至少一个须尚未满足。runtime 只投影上述 operator，不得改 clause 数量／顺序、target、relation、mode/effect、support DAG 或账户方向；在 `any` 单独使用 Exocharts、绑定缺失／多个／歧义、当前已触发或形成支持方向均硬失败；
- 每个主账户/Maker `strongest_counterevidence` 与 `invalidation_path` 还必须独立包含 `account-current-basis-v2` 的 `current_basis={mode,clauses}`；clause 只能使用 `{owner_type,owner_id,field,operator,value}`，`operator=equals` 且 value 必须等于 support DAG 可达 owner 的当前 typed 值。Gate 按同账户 thesis 方向把每个 owner 机械归类为 `support|counter|neutral`；`strongest_counterevidence` 的每个 clause 都必须为真实 `counter`，支持或中性证据不得为了来源数量被填入反证。对 `long|short`，相反方向才是 counter；对主账户 `neutral` 或 Maker `observe`，方向性证据是对继续中性/观察的 counter、无方向证据是 support，且一份最强反证的全部方向性 clause 必须指向同一个替代方向。TradingView/Coinglass 的绝对方向按 closed map 解释；Exocharts `confirm|contradict` 必须相对其可达 Coinglass 方向解释，`weaken` 不得冒充相反方向；ETF、基本面兑现及其它无绝对多空含义的字段默认中性。至少一个真实反证即可，不强制虚假的跨源拼接；
- 每个账户的 `invalidation_path` 还必须在 reasoning 阶段拥有 exact `structural-noise-buffer-v2`：字段集合为 `schema_version/status/method_code/observation_id/timeframe/visual_evidence_ref/anchor_kind/anchor_source_field/anchor_price/noise_outer_boundary/price_distance/risk_budget_input_used/insufficiency_reason_code`。`status=certified` 只适用于 `long|short` thesis，必须绑定 support DAG 可达、本轮有效的 TradingView observation 与具体截图引用，结构锚须可机械定位且匹配账户方向/周期，`noise_outer_boundary` 必须是同图可见噪声外边界，最终方向化 stop 必须严格越过该边界；`risk_budget_input_used=false`。截图不足时使用 `visual_noise_envelope_not_readable`；主账户 `neutral` 或 Maker `observe` 没有方向化 stop，只能使用 `status=insufficient + insufficiency_reason_code=not_applicable_non_directional_thesis`。两类 insufficient 均须空 anchor/boundary/distance，后续只能 `observe`；不得发明固定最小点数、ATR 倍数或由 3%/8%/R:R 反推 buffer；
- reasoning 先于风险数学密封 anchor、可见噪声外边界与 distance；decision stop basis 中实际存在的 observation/timeframe/anchor identity/price/distance 必须精确等于 reasoning owner，Gate 同时读取 reasoning 的 status、截图引用与噪声外边界验证 certified 状态及 stop 严格越界，compiler 不得后改或补造。系统只证明证据绑定与方向化几何，不声称读取模型隐藏思维；fresh 样本仍需人工判断图上边界是否被正确识别；
- Maker 必须同时追溯 Coinglass 与 Exocharts；
- Coinglass 的价格/CVD/OI/资金费率使用同一 BTC、1H pivot；Exocharts 每轮先选择 `Bybit BTCUSD`，再精确确认 `D`、`Tick 120`、`Bid-Ask Profile`、`Imbalance`、`Candle None`、`FPBS`、`vWap` 日线足迹配置，只做跨源强弱印证，不冒充同周期主判；
- Maker 必须覆盖价格/CVD、OI、资金费率、足迹确认；
- 主账户至少绑定基本面/宏观证据与 TradingView 结构；
- `methodology.fundamental_event_assessments` 必须用 exact 六字段逐条且恰好一次覆盖密封 BlockBeats top3 `selected_event_sha256`。事件事实只能由 compiler 从密封工件投影；模型不得重写。每项 `realization_claim_id` 必须指向同 hash 的 shared `fundamental_event_realization`；该逐事件 claim 由当前 shared `fundamental_context` 与 `chart_interpretation` 共同支持。唯一 shared `fundamental_price_realization` 只作三事件综合兑现 owner，不得冒充三个逐事件状态。`impact_channel`、`expected_effect`、`boundary_code` 使用 scoring 闭集；非空 `counter_claim_ids` 只允许 shared typed 盘口/盘面/ETF/清算确认 claim；新闻本身不得单变量翻向。当前 `fundamental-event-assessment-v1` 没有事件发生时点对齐的前后价格窗口，因此固定 `load_bearing_allowed=false`、`observation_only_reason_code=event_price_attribution_unavailable`，并禁止用于 `winrate_adjustment`、`account_current_basis` 或 `account_trigger_logic`。对应 secondary signal `fundamental_price_realization` 必须为 `disposition=no_adjustment + no_adjustment_reason_code=event_price_attribution_unavailable`；compiler 只披露“当前 v1 缺少事件对齐价格归因，未进入置信度或控制链”。只有未来经另行批准的合同提供并认证 event-aligned price attribution basis 后，才允许 `price_attribution_basis_required_to_reenable=true` 所描述的重新承重；不得用当前价、综合状态或自由文本绕过；
- ETF 原始流量事实只能追溯 Farside BTC ETF Flow；`price_relation` 不得写入 Farside observation，而由门使用已认证的 Coinglass 同锚价格方向与 Farside `flow_direction` 按九格真值表复算；
- ETF claim 必须声明“仅确认/削弱/中性、不可单变量翻向”；
- 流动性猎杀必须追溯 TradingView 的用户手绘成交量分布区域，并明确它只表达位置/概率而非方向；手绘区域不可读时必须 `zones=[]`、原因必填、`chart.liquidity_hunt=0`，禁止 POC/VAH/VAL/HVN/LVN 数值与概率落点，但不阻断四周期结构；
- 清算地图必须来自 Coinglass 固定周期证据，并明确只作手绘成交量分布的辅助印证；profile 不足时保持 neutral，不得替代或翻向；
- 上述三类 7 月增量 claim 均为必需，禁止出现“采集了但推理未使用”；
- 主账户与 Maker 必须分别拥有唯一 thesis、`strongest_counterevidence`、`invalidation_path`。runtime 在同一个已密封 attempt 内据此生成 `scenario-ownership-v1` exact 六格：base 绑定本账户 thesis，counter/invalidation 绑定本账户唯一 typed owner；methodology 同格 `claim_id` 与 top-level owner 完全相同，`action` 由 scenario type 的 closed transition code 生成，`trigger_claim_ids` 精确等于 owner `support_ids` 中按原顺序首次出现的 direct claim IDs，observation ID 与 owner 自引用均排除。producer 不拥有这些包装字段，也不得提交 condition、expected path、action prose 或额外 claim list；compiler 只从 owner typed state/trigger 与 transition code 投影中文，真实订单生命周期只由 Decision/continuity 决定；
- 盘口结论必须从同一 pivot 的价格/CVD、OI/价格语义、资金费率修饰和 Exocharts 足迹确认投影；资金费率不能单变量翻向，Exocharts 只能确认、削弱或反驳，不能替代 Coinglass 主判；
- Maker 最强反证的未来 trigger 不得把 Exocharts `cross_check_result=confirm` 单独解释为反证。只有 `mode=all`，且同一 trigger 已要求 Coinglass `final_direction` 翻到当前 Maker thesis 的相反方向时，该 `confirm` 才表示“足迹确认了已翻向的 Coinglass 主判”；否则方向语义反转并硬失败；
- 当前生产盘口输出域仅为任意整数 0–60；61–69 为 `reserved_invalid`。70 仅保留给未来原生结构化极端证明能力，当前 `production_enabled=false` 且验证器未实现，C19/C22/C56/C59 即使满足候选语义也最高 60；仅修改配置不得启用 70，普通报告也不得因该能力不可用而硬停；
- `cannot_do` 只约束 Maker，且只能在 Maker thesis、最强反证、失效路径和基准/反证/失效三类情景全部完成后生成，作为最后且 output-only 的限制结论；任何 claim 的 support/counter/invalidation、reasoning scenario 或 methodology scenario 都不得引用它。它不得依赖主账户、不得生成或翻转 Maker 方向。Maker 评分、计划时置信度、入场价格触达概率、订单生命周期和订单依据不得引用主账户 claim；两账户的比较只能在各自决策完成后用于展示，不能反向驱动任一账户；
- 所有前台关键段落必须绑定 claim。

除 reasoning 外，每个阶段首稿失败只允许一次同输入、同方法论的局部纠正，第二次仍失败即进入人工复核；reasoning 依第 5 节执行“首次失败 + 两次同输入局部纠正”的三次总尝试预算。报告或交付失败不得重采证据、重跑推理或整轮自动重启，禁止无限循环。
人工复核后只有写入绑定 run/date/slot、复核人、批准引用与原因的哈希授权记录，才可从失败阶段继续；不得手改 checkpoint 或删除锁。

### 门三：风险与执行闭环

- `decision-model-v7` 只接受可机械复算的 closed typed 语义：Main 计划状态使用 `plan_state_reason_code`；盘口与盘面评分只保存分值、claim IDs 和类型化周期关系；`entry_reach_probability` 仅估计从 TradingView 1H 当前价到候选入场档的价格触达概率，并以 `applicability` 区分适用与不适用。它不是订单成交概率。`order_lifecycle` 必须逐字段等于 Gate 从 current/entries/cancel 派生的 `maker-order-lifecycle-v1`；实际 `fill_probability` 永远为 `null`。只有取消价位于 current→entries 的反方向分支才为 `fillable`；同向且更近为 `cancel_blocks_all_entries`，同向且更远为 `entry_before_cancel`，碰撞或混合侧为 `invalid_geometry`。生命周期不可行必须先于结构止损和风险数学显示为 `order_lifecycle_invalid`；
- Coinglass observation 只拥有原始清算地图。清算图相对于 TradingView 手绘 profile 的 `confirm|weaken|contradict|neutral` 结果只属于跨源 `liquidation_confirmation` claim；该 claim 必须直接绑定 Coinglass observation 与认证 `chart_interpretation` claim，禁止直接引用原始 TradingView observation 绕过 chart claim。手绘 profile 不足时结果只能为 `neutral`；
- 当前生产盘口合法值仅为任意整数 0–60；61–69 为 `reserved_invalid`，不得输出、四舍五入、插值或用作过渡分；70 是未来原生结构化证明保留位，当前不得输出；
- C19/C22/C56/C59 的极端语义继续完整认证，但在原生序列验证器、独立回归与显式生产启用全部完成前一律最高 60；配置开关本身不构成启用证据；
- 盘面五分项机械合计为 0..30，只代表机会质量；
- 总分机械等于盘口加盘面；
- 盘口、盘面五分项均必须绑定可追溯 claim；用户可见中文说明由 compiler 从认证分值、closed reason code、typed owner 与 claim 证据确定性投影，decision 中禁止另存自由 rationale；
- 计划时置信度必须严格按 `anchor → adjustments[0]=当前 Maker 最强反证负 adjustment → 其它独立 adjustments → final → 门槛/状态` 机械复算，禁止正文或计划状态倒推。anchor 的 claim IDs 只允许 `account=shared|maker`：盘口轴必须用 support DAG 同时可达 Coinglass+Exocharts 的 `orderflow_interpretation`，结构位置轴必须用可达 TradingView 的 `chart_interpretation|invalidation_path`；可选 `liquidity_hunt` 只能补位置/概率。主账户 claim 与 `maker_thesis|market_regime|strongest_counterevidence|cannot_do|fundamental_context|fundamental_price_realization|etf_confirmation` 均禁止充当 anchor。`anchor_rationale` 必须精确等于 authority 的 `anchor_policy.canonical_rationale`；市场专属事实只能由 anchor claim IDs 与可达来源拥有，compiler 只投影 canonical 文本和机械验证出的两轴，不得消费或补造自由文本市场解释；
- `adjustments[0]` 必须用 `maker_counter_current` 对当前 Maker `strongest_counterevidence` 作负 adjustment，任何 ETF/基本面 adjustment 排在其后。`counter_resolution` 只能使用 `maker-counter-resolution-v2` exact 字段、`disposition=adjusted`、`adjustment_reason_code=maker_counter_current` 与 `resolution_claim_ids=[]`；`residual_clause_indexes` 必须按顺序覆盖该反证全部 `current_basis.clauses`。不存在 `resolved_no_adjustment`；若原反证已不再成立，必须先选择当前真正最强反证，再完整扣分；
- 其余 adjustment 当前只允许 `etf_confirm|etf_weaken`。`fundamental_confirm|fundamental_weaken` 仅保留为未来兼容枚举；在 `fundamental-event-assessment-v1` 缺少事件对齐价格归因期间不得生成或进入 adjustment，`fundamental_price_realization` 必须按 `event_price_attribution_unavailable` 处置为 `no_adjustment`。FedWatch、清算地图、资金费率单变量、入场价格触达概率、订单生命周期、风险数学，以及已进入 anchor 的 footprint/orderflow/chart/structure 证据均不得作为 adjustment，禁止重复计证。每项必须使用 scoring 闭合 `reason_code`，匹配允许 claim type、可达 source、typed owner value 与非零整数 delta 的正负号；reason code 唯一、单项 claim IDs 唯一、跨项 claim IDs 与 typed owner signatures 互斥、anchor 与 adjustment 直接 claim 不重叠。compiler 只投影 `reason_code + delta + claim_ids + typed_values`，自由 `label/rationale` 只供门内检查，不得作为用户可见事实；
- `final` 必须等于 `anchor + Σadjustments` 且先完成落值；之后才比较 60%，再与总分 65 合成 `threshold_eligible`，最后才与 `plan_constructible` 共同决定 `qualified|observe`；
- 盘面评分的 reason code 必须独立显式投影 1D/4H/1H 当前结构并保留周期冲突，不得发明多数规则或误写成 15m；它不属于计划时置信度 adjustment；
- 总评分达到 65 且胜率达到 60% 只令 `threshold_eligible=true`；还必须满足 `plan_constructible=true` 才能形成 `qualified` Maker 计划，否则必须为结构化 `observe`。Gate 与 compiler 必须从认证 Maker decision 确定性且互斥地分类为 `maker-semantic-state-v1` 四态，候选是否已提交的唯一 owner 是 `maker.risk_plan` 是否非空：`qualified_candidate`（方向性、`plan_state=qualified`、`risk_plan` 非空）、`rejected_submitted_candidate`（方向性、`plan_state=observe`、`risk_plan` 非空；`plan_constructible` 可为 true 或 false）、`directional_thesis_only`（方向性 thesis、`risk_plan={}`）或 `non_directional_observation`（`direction=observe + primary_reason_code=non_directional_thesis + risk_plan={}`）。只有前两态可使用“候选”；被拒候选参数和原始候选生命周期只可在附录 D 中性审计块保真出现，并必须同时明确不可执行；后两态必须明确披露“未提交候选计划”，不得称为候选/被拒候选、显示计划数字，情景展示必须由 `scenario-ownership-v1` 的 typed owner 与 closed transition code 确定性投影，不得从中文词汇推断、创建或改变真实候选生命周期。Maker summary、Maker 执行前台与方向/计划态必须由 `audit.maker_execution` 精确重建；主账户授权文案必须由 `audit.main_plan.plan_state` 决定，`observe` 不能写成候选主账户计划。Maker thesis 本身为 `observe` 时，计划不适用原因必须是 `non_directional_thesis`，并且 `position_notional_usdt=null`、`entry_type=not_applicable`、`entry_zone_basis=null`、`risk_plan={}`、`defense_plan={}`、触达概率与订单生命周期均为 no-candidate N/A，不能遗留幽灵仓位或被 compiler 隐藏的候选。其余方向性候选的 `plan_constructibility.failure_codes` 必须一次性、无短路地按固定顺序返回全部命中项：`no_certified_entry_zone -> entry_zone_binding_invalid -> entry_zone_role_invalid -> maker_order_marketable -> entry_semantics_invalid -> cannot_do_conflict -> order_lifecycle_invalid -> structural_stop_invalid -> risk_math_invalid -> defense_trigger_invalid`；`primary_reason_code` 只能是该有序列表的首项（无失败时为 `constructible`），禁止用单一风险错误隐藏更早的方向、区域角色、Maker 静态挂单、触达、撤单或 `cannot_do` 语义错误；
- 入场价格触达概率只作为软参考；系统当前不估计实际成交概率；
- 主账户四档计划枚举全部 15 个非空成交组合，统一按 `abs(weighted_entry-stop)/weighted_entry*leverage*100` 复算，全部情景名义风险必须不高于 8%；主账户不适用 Maker 3% 上限；
- 主账户初始止损必须使用独立 `main_initial_stop_policy`：只绑定主账户 `invalidation_path` 和本轮 TradingView 1D/4H 中线结构，禁止复用 Maker policy 或以 1H/15m 作主锚。active 锚只允许带 timeframe 的 readable 手绘 profile 中性外沿或非当前入场区 structure zone 外沿；裸支撑/阻力/摆动价数组只供展示。structure zone role 对空单只允许 `resistance|breakdown_retest`，对多单只允许 `support|breakout_retest`。锚点须严格位于主账户入场区与全部分档价外侧。外向 buffer 的唯一 owner 是同一主账户 `invalidation_path.structural_noise_buffer`：decision 的 observation/timeframe/anchor/source-field/anchor-price/outward-buffer 必须精确复制 reasoning 密封值，derived stop 还必须严格越过 reasoning 认证的 `noise_outer_boundary`；`buffer_claim_id` 仍绑定该失效 claim、`buffer_backsolved_from_risk=false`。8% 只能在结构止损确定后验算，不得压缩；
- Maker 每个非空成交情景单独复算 TP1 盈亏比和名义风险，全部情景必须达到 1:2.5 且不高于 3%；Maker 不得借用主账户 8% 上限；
- TP1 必须减仓 50%，TP2 必须清剩余 50%，且 TP2 必须位于 TP1 之后；
- Maker 初始止损锚必须由同账户 `invalidation_path` 在 reasoning 阶段从本轮 TradingView 认证结构中选择，且可机械定位并严格位于 `entry_zone` 与全部挂单价外侧。active 闭合来源只允许带 timeframe 的 readable `user_drawn_manual_only` 手绘 profile 中性外沿（空单上沿、多单下沿）或非当前入场区的认证 structure zone 外沿；裸支撑/阻力/摆动价数组只供展示。decision 只能精确复制 reasoning 的 observation/timeframe/anchor/source-field/anchor-price/distance，并保持同一 `buffer_claim_id`、`buffer_basis_code=current_run_typed_market_noise_allowance`、`buffer_backsolved_from_risk=false`；最终止损必须严格越过 reasoning 认证的可见 `noise_outer_boundary`。3%/R:R 只在此后验算，不得反向压缩；证据不足只可 `observe`；
- decision 对 reasoning 已密封 buffer 的 `observation_id/timeframe/price_distance` 任一改写属于跨阶段 owner mutation，必须令该 decision submission 失败并消耗本阶段尝试，不得仅自报 `structural_stop_invalid` 后获得成功 attempt。若密封周期没有合法的非入场结构锚，decision 必须保持 `observe` 且不提交 `risk_plan/defense_plan`，不得换周期补造候选；空候选只保留 `structural_stop_invalid + risk_math_invalid`，不因没有提交 entry geometry 额外误报 `entry_semantics_invalid`；
- 多档入场在真实成交前，由控制器按计划全档加权锚和全部非空成交组合确定性生成两层阿拉伯数字精确触发价；每个组合必须保存正 canonical Decimal 字符串原始值（无指数、前导零、尾随小数零）、闭合取整规则、正 canonical 价格步长字符串或 `null` 及最终价格，且可机械复算。`exact_no_rounding` 必须用 `null` step；`nearest_step_half_up` 必须绑定正 step 并按 HALF_UP 复算。计划锚不是单点入场、代表入场或实际成交事实。真实成交后才按成交明细计算实际加权成交价，并重算、替换为唯一触发价：多单向上加 1.5R/2R，空单向下减 1.5R/2R；禁止 `+/-`、`±` 或仅倍数无价格的展示；
- 第一层只允许成交后后续形成并确认的 4H 结构性极点，禁止预填未知的未来极点止损价；该禁令不允许删除第一层精确激活触发价。第二层只允许把剩余止损移至实际加权成交价保本，且必须展示第二层精确激活触发价；
- Maker 入场业务语义必须是当前 run TradingView 结构认证的 `entry_zone` 价格区间，并由区间内 `ladder` 的 2–5 档明确价位与合计 100% 比例执行；用户手绘 profile 可提供位置证据，profile 不足时只能退回明确认证的 TradingView 四周期结构区，不得使用清算地图、Exocharts POC、代表价或其他辅助值冒充 `entry_zone`。禁止 `single`、代表价或单一价位一次性 100% 入场；未来即使恢复 70 也无例外；
- Maker 候选必须明确 `OKX`、交易标的、500–1000 USDT（BTC）/300–800 USDT（ETH）候选名义持仓、固定 5x、左/右侧、策略类型和结构化 `cannot_do` 绑定。`decision-model-v7` 尚无右侧价格行为确认的 closed owner，因此 `right` 只可被记录为 `entry_semantics_invalid` 的不可执行候选；在新增并认证 `right_confirmation_basis` 前不得形成 `qualified` 或 `place_order`。`追多|追空|追多空` 与 `entry_type=right` 的方向对应禁令仍独立命中 `cannot_do_conflict`；
- Maker decision 必须使用门定义的精确 closed typed schema；任何额外字段均拒绝，尤其禁止 `plan_text`、`entry_price`、自由文本计划或代表价形成第二套方向、价格、仓位、风险或动作真相；
- 主账户必须独立拥有结构化的 thesis、`plan_state`、方向、行动、`entry_zone`、仓位、止损/止盈、最强反证、失效路径与三类情景；报告文本只能投影这些认证字段，不得由 Maker 结论推导或改写。主账户不存在 `cannot_do` 字段；
- 连续性只能在推理锁定后读取可核验的前序计划来源，绑定来源哈希、已执行比例、唯一有效订单、当日交易次数和当日有效期，且不得回写分析。`reconcile_filled` 只允许前序状态为 `filled`、已执行 100%、前后均无 active order 且不撤旧/挂新；`open` 的部分成交余单必须显式 `keep`、`cancel` 或 `cancel_replace`，不得借 `reconcile_filled` 消失，且已成交账本必须保留；
- TradingView 正文必须显式投影 1D、4H、1H、15m 四周期认证事实，15m 只细化 Maker 入场，不进入方向主判或名义 70+30 评分框架；当前盘口生产上限仍为 60；
- 入场区间、TP1、TP2、止损、未成交取消价、仓位账本和防守触发均由决策模型统一拥有，正文不得另写一套数值；
- 实仓均价只承认可核验成交明细或锁后明确记录；缺失时禁止从 1.5R/2R、止盈、止损、区间中点、代表价或任何假设成交组合反推业务事实；
- 未成交取消价必须能在从当前认证价前往入场区间的反方向先触发，并与成交后止损分离；
- 主账户和 Maker 分别绑定各自 thesis、市场状态、最强反证、失效路径和三类情景；
- production 决策必须绑定同日开仓前状态门禁；shadow 决策必须绑定自身密封
  run 并证明未读取个人状态、未尝试订单变更。门禁只决定执行资格，不得反向
  改写计划、方向、评分、胜率、价格或风险参数。

### 门四：交付一致性

正式渲染前先通过两道报告产品门：

- `human_reasoning_depth`：六源必须逐一写清“作用、事实、判断价值、使用边界”，并完整呈现同锚盘口、足迹确认、多周期、7 月增量逻辑、基本面/ETF 兑现、主账户反证/失效、Maker 反证/失效、账户分离、评分/胜率和风险/情景十段证明链；机器 DAG 通过但人无法直读时仍判失败。
- `gold_template_fidelity`：版式与阅读节奏绑定 `vnext_report_presentation_contract.json`；禁止原始 snake_case、SHA-256、机器指标树、一条 claim 一个标题和碎片化 bullet 洪水。模板在 canonical Markdown 生成后、DOCX 渲染前即机械验收，Word 逐页 QA 只作最后视觉确认，不承担补救模板漂移。

- Markdown、Word、Notion 和卡片都来自同一个 `canonical-report-model-v11`；`reasoning-model-v5` 禁止 `report_sections`。前台必须由 compiler 从 typed observation、claim、scenario owner、decision、continuity 与 evidence 中密封的 provider meta 确定性重建；provider 显示名只能由 closed `provider_id` 映射，不能相信自由 `provider_name`。CME 显示为官方主源；Kalshi 必须显示为 `KXFEDDECISION` Plan C 备用观察源，并显式给出 API 数据时点、独立事件合约/非 CME 等价/observation-only；`cut_gt_25bp`、`hike_gt_25bp` 与 `other_unlisted` 必须显式投影。compiler 不得消费、补造、改写或隐藏上游业务判断，禁止自由文本形成第二结论。入场价格触达概率不适用时所有前台与审计出口必须显示 N/A 及闭合原因，不得显示 `0%`；适用且真实为 0 时仍必须显示 `0%`。该字段不得被命名或解释为订单实际成交概率；`order_lifecycle` 必须单独投影可成交路径、撤单路径和永远为 `null` 的实际 `fill_probability`。`equals_at_trigger` 固定投影为“触发时必须为”，`one_of_at_trigger` 固定投影为“触发时必须属于”，不得使用“保持”暗示当前状态持续不变。Maker 状态必须先按 `maker-semantic-state-v1` 四态分类再投影，四态用词与计划数字权限不得互换。被拒 Maker 候选必须按 authority 顺序展示全部 `failure_codes` 的中文投影，并同时展示未达到的评分/置信度门槛；若其 risk input 可机械复算，须通过独立 `rejected_candidate_risk_scenarios` 展示所有实际情景值，并逐行注明“不可执行、不得用于下单”，不得复用合格计划的 `risk_scenarios`。若已提交 risk input 但其几何或分配不满足确定性复算前提，必须以 closed recalculation status 明示不可复算且不得生成风险百分比，不能误写为“未提交参数”或使报告阶段失败。ETF 与基本面 `signal_dispositions` 的类型化当前值、处置与闭合 reason 必须可见；当前 event-v1 的基本面 disposition 必须明确显示 `no_adjustment / event_price_attribution_unavailable`，不得把逐事件或综合 realization 文本投影成置信度增减、current basis 或 future trigger。被拒候选参数只允许在附录 D 的中性审计块出现，Maker 前台不得显示仓位、入场、止损或止盈数字；
- compiler 只能从 top-level `owner_claim_id` 指向的 typed owner 投影 scenario：base condition 来自 thesis 的 typed direction，counter/invalidation condition 来自同 owner 的 typed `trigger_logic`，expected path/action 来自 scenario type 的 closed transition code；methodology owner/code 必须与 top-level 精确一致。自由 `conclusion`/`invalidation` 即使通过上游审计也不得进入证明链、情景、正文或任何交付面。完整 future 条件在附录 D 对应情景中恰好出现一次，证明链与最终闭环只引用该情景。主账户与 Maker 的六个完整情景，以及两账户共八个当前／未来反证—失效闭环标记，必须在附录 D 各详细出现一次；正文与附录 C 只能保留短引用；scenario 分析状态转换不得拥有、猜测或改变真实订单生命周期；
- 兼容边界仅允许不可变 `evidence-snapshot-v1` 且 provider meta 为空时，以 `provider_id=unknown` 和“旧版只读证据”显式投影为 observation；禁止借此推断 CME。当前 `evidence-snapshot-v2` 的 provider meta 缺失、混搭或不受支持时必须 fail closed，不得生成 provider-qualified report 或 sample outcome；
- 每次 report compile 都必须真实执行 compatibility lint；CLI、controller、测试入口和恢复路径均不得提供 skip/bypass 语义。lint 未执行或失败必须保留为 report failure，禁止把“跳过”记录成 `exit_code=0` 或据此密封成功 attempt；
- 三张 BlockBeats 卡片必须来自证据快照中已选定的三条哈希绑定事件，不得由 Agent 另写事件；
- Word 视觉 QA 为真；
- DOCX 必须是可解析的 Word 包、PDF 必须有有效签名、每页截图必须是有效 PNG；
- Notion 结构和视觉合同为真；
- 同前缀唯一页面为真；
- report hash 在 render、publish、delivery 全链一致；
- Notion children signature 可复核。

仅有布尔 PASS、占位文件或哈希正确但类型错误的伪交付证据，均不得通过。

影子验收期使用独立的 `shadow-delivery-model-v1` 终态：它必须通过同一份 report、DOCX、PDF、逐页 Word QA、卡片规格和三张卡片的本地完整性校验，并明确记录 `publish.status=not_attempted`、`publish.reason=shadow_mode_forbids_notion`。production 与 shadow 共用的 Word QA 必须是 exact `word-qa-vnext-v2`，绑定当前 run id/hash/date/slot、允许的 Microsoft Word backend、明确复核人、带时区的复核时间以及 `1..page_count` 全页检查；`status=passed` 时还必须使用 exact `review_checklist_version=word-qa-semantic-review-v1`，`review_checklist` 只能且必须包含 `all_pages_inspected`、`no_clipping_overlap_or_missing_glyphs`、`no_orphan_semantic_headings`、`critical_price_blocks_not_split`、`six_source_sections_readable`、`arabic_price_digits_preserved`，六项全部为 boolean `true`。Python approval API 本身也必须显式收到 `confirm_visual_pass=True`。跨 run、错日期、错时段、缺复核、checklist 版本/键集合/值不精确或仅靠布尔 PASS 均由既有 delivery 门拒绝，不新增第五道门。影子 payload 出现任何 Notion manifest、verification、page id 或发布成功主张均硬失败。通过后 checkpoint 只能标记为 `shadow_complete`、`completion_mode=shadow`、`notion_published=false`；这不等于正式 `complete`，也不得作为已发布证明。正式 `delivery-model-v1` 的 Notion 发布、唯一页、签名与读回门禁保持不变。

## 5. 错误处理

| 错误类型 | 重试层 | 是否重跑推理 |
|---|---|---|
| 源缺失、文件哈希变化 | evidence | 是，只有新证据认证后 |
| claim DAG、同 pivot、反证缺失 | reasoning | 仅推理层，最多两次同输入局部纠正 |
| 评分、门槛、风险数学错误 | decision | 否 |
| Markdown/格式/lint 错误 | report | 否 |
| Word、Notion、网络、视觉失败 | delivery | 否 |
| 同时运行冲突、宿主能力不明 | 人工复核 | 否 |

阶段预算按独立失败类型收敛：`reasoning` 执行“首次失败 + 两次同输入局部纠正”，第三份哈希有效的 `failure.json` 转 `needs_review`；其余阶段继续执行“首次失败 + 一次局部纠正”，第二份哈希有效的 `failure.json` 转 `needs_review`。孤儿 attempt 不计入逻辑失败。人工批准可以从失败阶段继续，但不允许自动化自行重复授权或删除失败证据。

reasoning 的纠正预算只作用于完整原子 attempt；`pipeline_units` 不是可恢复子阶段，
不得对单个 unit 建 checkpoint、继承半成品或进行隐藏 retry。

上下文容量不作为正确性依赖：历史金标只在离线合同中蒸馏一次，生产阶段只读取当前证据快照、当前 phase 方法清单和上游哈希制品。更大模型窗口只能提供余量，不能成为找回规则、补全模板或恢复历史事实的机制。

可执行计划的入场价格触达概率说明不得在自由文本中隐藏价格距离。决策模型必须绑定 `TradingView 1h` 认证价、由当前 run TradingView 结构认证的完整 Maker `entry_zone`、2–5 档全部价格与比例、各档绝对距离及触达方向；不得用单一代表价压缩区间，也不得让触达概率把任何价位移出认证 `entry_zone`。订单能否沿合法路径成交必须由独立 `order_lifecycle` 判断，不能由触达概率替代；系统不估计实际成交概率。决策门机械复算，报告编译器只负责把结构化结果翻译成人类可读语句。

控制进程硬停时，短期控制锁必须先确认原 PID 已死亡，再把旧锁保留为孤儿证据并从密封 checkpoint 续跑；禁止删除运行目录或回滚已认证阶段。

每个阶段 attempt 必须记录 PID、线程和密封哈希。活 owner 存在时禁止重复启动同阶段；死 owner 只能通过写入 `orphaned.json` 终态证据后创建新 attempt。失败计数只承认哈希有效的 `failure.json`，孤儿 attempt 不计为逻辑失败。

未完成 run 若确需放弃，只允许使用绑定 run/date/slot、复核人、批准引用、原因和时区时间的 `run-retirement-authorization-v1` 显式退役。退役必须保留全部目录、checkpoint、attempt 和事件，并且在活阶段 owner 存在时禁止执行；禁止以删除 active 文件或运行目录代替退役。
同一 date/slot 通常只有在原 current run 已完成哈希验证并正式 `retired` 后，才允许新 run 原子接替 `current.json`；新 run 必须记录 `supersedes_run_id`，旧 run 与全部失败证据永久保留。`running` 与 `complete` 永久禁止接替。仅在用户明确授权的影子验收期，内部 `begin --allow-shadow-repeat` 可让新影子 run 接替已密封的 `shadow_complete`，并额外记录原终态与 `shadow_repeat=true`；不得覆盖旧样本、不得发布 Notion、不得把该路径用于正式 complete。

若进程在密封 `complete` / `shadow_complete` / `retired` checkpoint 后、释放全局 active 位之前硬停，下一次 begin 只能在取得旧 run 控制锁、复核 active/run/checkpoint 三方身份与哈希一致、确认终态且无开放活 attempt 后自动对账释放。任何非终态、哈希异常或活锁存在都必须继续阻断。

run 初始化期间的 active 位必须标记 `initializing` 并绑定初始化 PID；只有该 PID 已死亡时，下一次 begin 才可把原 active 原样迁为孤儿审计记录后重新认领。初始化完成后必须先原子切换为 `running`，再写入 slot current 指针，避免半初始化状态被误当成可续跑 run。

vNext 的 Word、PDF、逐页截图与渲染状态只能写入当前 run 的 `delivery_assets/`，不得写入或覆盖旧版共享 `outputs/` 路径。

## 6. 历史样本使用边界

- 6.22–6.26 AI 合格稿：作为方法链、交易思路和推理深度验收参考；不得贡献旧事实、价格、方向、评分或措辞。
- 用户手工 Notion 稿：作为字段语义和前台表达验收参考；不得变成市场事实来源。
- 7 月新增逻辑：以增量方法规则和专门测试迁移；不得覆盖原方法链。

历史样本不进入生产运行上下文，只进入离线金标回放和验收。

## 7. 切换自动化前的完成标准

- 至少连续 5 份状态为 `shadow_complete`、`bindings.semantic_contract_sha256` 等于当前 semantic contract，且 `sample_outcome.evidence_provenance.mode=fresh_full_recollection`、`provider_id=cme_fedwatch_ui`、`method_class=cme_target_rate_probability`、`sample_source_class=cme_canonical` 的真实全量重采影子样本；每份样本还必须保留 `release_sha256` 与 `methodology_manifest_sha256` 供 rollback/bisect。该 provenance 只能由本 run 密封 evidence 的 `capture_mode=full_base`（morning）或 `capture_mode=full_recollection`（midday/evening）及 FedWatch source meta 确定性映射，禁止跨 semantic epoch、使用仅有 legacy combined identity 的 v1-v5 样本或复用旧证据累计；
- immutable replay、测试注入、fixture、历史报告回放以及无故障的 Kalshi Plan C 只可验证合同或提供备用观察，统一记为 observation；即使其余产品门通过、机械全绿或终态为 `shadow_complete`，Kalshi 也永远不是 clean，不增加 stability evidence、不进入 production switch。该边界不得隐藏备用链工程故障：同 authority epoch、同 provider/method/source class 的两个独立 run 出现同一可复核 failure fingerprint 时，仍可形成 `candidate_defect`，但不得跨 CME/Kalshi 方法聚类，也不得自动修复、改方法或新增硬门；
- 覆盖早、午、晚三个时段；
- 0 次 Technical expert 临时修复；
- 0 次 Agent 手写正式 `combined.md`；
- 0 次格式/Word/Notion故障导致重新采集或重新推理；
- 0 个共享路径恢复冲突；
- 六源完整率 100%；
- 关键结论证据可追溯率 100%；
- 主账户与 Maker 无串线；
- v4 手工金标前台、Word 和 Notion 视觉验收通过；
- 进程中断、report 失败和 delivery 失败均能从正确阶段恢复。

只有以上条件全部成立，才允许另行提出自动化切换 diff 并等待用户批准。

## 8. 样本学习出口（不是第五道门）

每个 `complete`、`shadow_complete` 或 `retired` run 在终态 checkpoint 密封后，必须尽最大努力生成同 run 内不可变的 `sample_outcome.json`。其合同见 `vnext_sample_outcome_contract.json`。

新 `methodology-manifest-v3` run 生成 `vnext-sample-outcome-v6`，必须逐项复制 run 创建时密封的 `semantic_contract_sha256`、`release_sha256` 与 `methodology_manifest_sha256`，并从本 run 密封 evidence 确定性导出 `provider_id/method_class/sample_source_class`；不得再输出含义重复的 `authority_epoch_sha256` alias，也不得输出模式批准原文或任何业务结论。既有 v1-v5 文件保持逐字节不可变；legacy v2 manifest 的终态 run 如需补发仍生成 v5，并且只能作为 observation，禁止伪造 v6 semantic identity。缺少 semantic triple、provider 未知、immutable replay、测试注入、fixture、历史报告回放与 Kalshi Plan C 都不得计入当前 semantic epoch 的 clean 连续样本；不同 semantic epoch 的 clean 样本禁止累加。

- 该文件只记录 run 身份、哈希、attempt／failure／orphan／人工复核次数、耗时、报告产品门布尔结果和去文本化故障指纹；禁止记录价格、方向、仓位、盈亏、评分、胜率或交易结论。
- 生成失败只能留下观察事件，不能阻断终态密封、释放 active run 或正式交付；下次终态对账可补发，但禁止覆盖不一致的既有结果。
- `sample_outcome.json` 只供 Technical expert 的外置事后评估器读取，生产 Evidence、Reasoning、Decision、Report 和 Delivery 阶段均不得读取它或外部学习台账。
- 单个普通异常只能成为 observation，不能自动修改代码、模板、方法论、宪法或新增硬门；重复独立样本或单次关键级事故也只形成候选项，仍必须经过根因、用户批准、回归验证和后续真实样本验证。
- 样本没有缺陷时，贡献的是稳定性与可重复性证据，不得为了显示“学习”而制造修改。
