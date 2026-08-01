# vNext 报告语言与数字合同

> 本合同只约束 vNext 可见报告的表达层，不产生交易判断，也不改变评分、胜率、账户优先级或风险规则。

## 1. 独立报告

- 报告只消费本轮已密封的六源 observation、结构化推理、对抗性反证与决策制品。
- 市场推理与报告事实禁止读取或引用用户观点、Notion 报告页面、历史成稿、旧行情事实、旧方向、旧分数、旧价格、旧仓位或任何外部报告结论。唯一例外是 production 在独立推理密封后消费 vNext 原生、同日、哈希绑定的个人执行资格合同；该合同只决定执行资格与动作，禁止进入或改写计划、方向、评分、胜率、价格、风险与主账户判断。shadow 不适用该例外，任何阶段均不得读取个人执行资格、持仓或订单状态。
- 主账户与 Maker 必须各自呈现 observation → claim → counter → invalidation → scenario → decision 闭环；展示时可对照，推理时不得互相引用结论。
- 实际成交、持仓与旧单状态只可来自独立推理锁定后开放的 source/hash-bound continuity artifact。没有这种证据时必须写“未验证”，禁止从止损、R、仓位上限、计划价或报告文字反推。

## 2. 数字

- 所有价格、区间、仓位、比例、评分、胜率、杠杆、止损与止盈必须使用阿拉伯数字。
- 每个承重数字必须来自本轮 observation 的 value path 或由这些值按明确公式确定性计算；禁止手工补全、猜测、近似改写或沿用历史数值。
- 禁止把价格数字转换为中文数字；禁止 `xx`、`约`、`左右`、`附近`、`~`、`k` 等模糊占位替代已要求的精确价格。
- 多源价格不一致时，必须保留来源、时点和差异，按既定新鲜度与周期规则选择主值；禁止为了版面擅自平均。
- Maker 入场必须显示为完整价格区间，并列出区间内 2–5 个不同挂单档位及合计 100% 的比例；禁止用单一代表价替代区间。
- Maker 决策必须严格使用 decision gate 的闭合字段集合：`claim_id`、`combination_id`、`direction`、`plan_state`、`threshold_eligible`、`plan_constructible`、`plan_constructibility`、`execution_action`、`order_transition_action`、`strategy_type`、`order_method`、`entry_type`、`exchange`、`instrument`、`position_notional_usdt`、`cannot_do_code`、`cannot_do_claim_id`、`orderflow_score`、`extreme_confirmed`、`orderflow_scorecard`、`chart_components`、`chart_scorecard`、`chart_score`、`total_score`、`win_rate`、`entry_reach_probability`、`entry_reach_probability_basis`、`order_lifecycle`、`winrate_rubric`、`risk_plan`、`defense_plan`。禁止 `plan_text`、`entry_price`、自由文本订单摘要、代表价或任何额外字段成为第二套业务真相。
- `entry_reach_probability_basis.applicability=applicable` 时，入场价格触达概率必须为真实的 `0..100` 整数并绑定完整 TradingView 1H 触达几何，真实 `0%` 不得隐藏；`not_applicable_no_certified_entry_geometry` 时，概率与 entry/distance/reach 几何必须为 `null`，所有可见出口统一显示“不适用”，禁止用 `0%` 冒充 N/A。该字段只描述价格是否可能触达挂单区域，不能命名或解释为订单实际成交概率。
- `order_lifecycle` 必须逐字段投影 Gate 从 current price、全部 entries 与 cancel price 派生的 `maker-order-lifecycle-v1`。报告必须明确区分 `fillable`、`cancel_blocks_all_entries`、`entry_before_cancel`、`invalid_geometry` 与无候选几何；实际 `fill_probability` 固定为 `null`/N/A，不得由价格触达概率、自由文本或 compiler 猜测。

## 3. 语言

- 人类可见叙事默认使用中文，语句必须直接表达事实、判断价值、反证、失效条件与动作。
- 行业标准缩写、产品名、数据源名、交易所名、标的名与固定字段可保留，例如 CVD、OI、SMA20、POC、VAH、VAL、Delta、VWAP、VRVP、ETF、Maker、TP1、TP2、BTC、ETH、TradingView、Coinglass、Exocharts、FedWatch、Farside、BlockBeats、OKX。
- 列入 `human_visible_enum_domains` 的承重或存在同值歧义字段，必须按字段域做确定性中文投影；这些字段不得共用无所有权的兜底翻译。其未知字段域、域外值、大小写或空白漂移必须在生成 Markdown 前硬失败，禁止把 raw enum 原样回退到报告。其它既有、无歧义且已闭合的 `METRIC_VALUE_CN` 映射继续按原合同投影；新增承重字段或同值多义字段必须先进入字段域合同。机器 schema、reason code、ID、hash 与 owner path 继续留在审计结构中，不得借翻译进入正文。
- 禁止为了“更像模板”增加无证据结论、重复段落或主观修辞；格式只能渲染已经锁定的业务语义。
- 未来触发条件的操作符必须保持原义：`equals_at_trigger` 译为“触发时必须为”，`one_of_at_trigger` 译为“触发时必须属于”，`becomes` 译为“转为”；不得用“保持”暗示从当前到未来一直未变。
- `scenario-ownership-v1` 的 producer scenario 只含 exact `id/account/scenario_type/owner_claim_id`。base condition 只从 owner thesis 的 typed direction 投影；counter/invalidation 的完整 future trigger 只从其 owner claim 的 typed `trigger_logic` 投影；expected path/action 只从 scenario type 对应 closed transition code 投影。自由 `conclusion`/`invalidation` 只供上游门内审计，不得进入 reasoning proof、scenario、正文、附录、卡片、Word 或任何用户可见文本。完整 future trigger 只在附录 D 对应情景中出现一次；其它位置只允许引用该情景。真实订单生命周期只由 Decision/continuity 拥有，scenario 投影不得反推执行。
- trigger 组合须忠实投影：`all` 为“且／全部条款触发”，`any` 为“或／任一条款触发”，不得交换、合并或弱化。Exocharts `confirm|contradict|weaken` 仅可相对同一 `all` 内唯一 Coinglass `final_direction` 翻译；reference target 等于 current 用 `equals_at_trigger`，不等用 `becomes`，relation 用 `equals_at_trigger`。当前密封时 `any` 全部 clause 均须未满足，`all` 至少一个须未满足。报告不得改写或隐去 operator／target／组合；同 field 互斥 target 不得投影为可达。主账户与 Maker 六个完整情景及两账户八个当前／未来反证—失效闭环标记，只能在附录 D 各详细出现一次；正文与附录 C 只用短引用，authority sentinel 不得进入用户可见 scenario。

## 4. 计划结论与执行资格

- `plan_state=qualified` 只表示本轮 Maker 候选计划在方法论、评分和风险数学上成立；报告必须完整展示入场区间、2–5 档且合计 100% 的分配、计划持仓、固定 5x、TP1、TP2、成交后止损、两层浮盈防守和风险情景，不得因为本轮未真实下单而降格为“观察”。
- 真实执行资格只由独立、哈希绑定的 `execution_authorization` 决定。报告必须把“计划结论”和“执行资格/动作”分层表达，禁止用执行阻断反向改写已认证的候选计划。
- shadow 报告必须先从认证 Maker decision 按 `maker-semantic-state-v1` 确定性归入且仅归入一态：`qualified_candidate` = `direction=long|short + plan_state=qualified + risk_plan` 非空；`rejected_submitted_candidate` = `direction=long|short + plan_state=observe + risk_plan` 非空（无论 `plan_constructible` 为 true 或 false）；`directional_thesis_only` = `direction=long|short + risk_plan={}`；`non_directional_observation` = `direction=observe + primary_reason_code=non_directional_thesis + risk_plan={}`。`risk_plan` 是否非空是候选是否已提交的唯一 owner。合格态写“影子候选计划”；被拒态只能在附录 D 使用“被拒候选审计”，原始候选生命周期可保真审计但必须明确不可执行；方向性 thesis-only 与非方向观察态必须明确披露“未提交候选计划”，禁止把它们表述成“候选”或“被拒候选”或显示计划数字。scenario 的 condition/expected path/action 全部由 typed owner 与 closed transition code 生成且只描述分析状态，不得承载入场、挂单、成交、TP、撤单、止损等订单生命周期。Maker summary 与 Maker execution 前台必须逐字段精确匹配 `audit.maker_execution`；主账户 shadow 授权必须匹配 `audit.main_plan.plan_state`，观察态只能写“影子主账户观察状态”，不得写“影子候选主账户计划”。四态都必须附“未读取个人持仓/订单状态；未创建、撤销或挂出真实订单”，且禁止显示真实下单成功、有效订单数量、个人实际持仓或任何订单变更主张。只有 Decision/continuity 中真实存在的入场、分档、止盈、止损、防守、成交与减仓状态才能使用“候选”或“若未来另获 production 授权”的条件语态，不得把计划成立写成当前已执行、已成交、已挂单、已撤单或已持仓。
- production 报告只有在 production 授权合同允许且连续性合同验证通过时，才可展示真实执行动作与有效订单数量；计划成立本身不等于已下单。
- 连续性必须使用精确状态语义：`reconcile_filled` 只在前序状态为 `filled`、累计成交比例恰为 `100%` 且前后均不存在 active order 时成立；`open` partial remainder 必须显式 `keep`、`cancel` 或 `cancel_replace`，不得借 `reconcile_filled` 消失，既有成交账本必须保留。

## 5. 投影完整性

- Word、PDF 与逐页 PNG 必须由同一锁定报告制品确定性派生；任何一层不得改写价格、方向、分数、区间、账户归属或失效条件。
- 正文保持精炼，③后附保留完整承重推理链；精炼不得删除反证、失效、来源边界或风险验算。
- `reasoning-model-v5` 禁止 `report_sections`，预认证、审计与 canonical compiler 都只能消费 typed observations、claims、scenario owners、decisions、continuity 与其确定性 canonical model；不得保存或恢复任何自由文本报告第二真相。
- Coinglass observation 仅投影原始清算地图；清算图相对于 TradingView 手绘 profile 的确认结果只从 `liquidation_confirmation.confirmation_result` 投影，并保留其 Coinglass observation 与 `chart_interpretation` claim 的双重 lineage。禁止从 observation 旧字段形成第二真相。
- 当前 `fundamental-event-assessment-v1` 只有事件枚举与 hash 绑定，没有事件发生时点对齐的价格窗口，因此仅为 `observation_only_no_event_aligned_price_attribution`：`load_bearing_allowed=false`，`observation_only_reason_code=event_price_attribution_unavailable`，禁止用于 `winrate_adjustment`、`account_current_basis` 或 `account_trigger_logic`。`fundamental_price_realization` 的 signal disposition 必须投影为 `no_adjustment / event_price_attribution_unavailable`，并用中文明确说明“当前 v1 缺少事件对齐价格归因，未进入置信度或控制链”。任何 `realized|partially_realized|not_realized|conflicted` 文本都不得绕过该边界。只有未来认证 event-aligned price attribution basis 后才可按 `price_attribution_basis_required_to_reenable=true` 重新承重。
- 报告表达层失败只允许对同一输入做一次局部纠正；不得因此重采证据、重跑推理或循环整轮。
