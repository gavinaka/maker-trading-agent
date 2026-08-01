# 金标底稿与手工报告双参考推理契约

> 状态：维护期已学习的压缩方法摘要，不是运行期历史样本输入。
> AI 合格底稿参考范围固定为 2026-06-22 至 2026-06-26，只贡献推理链、交易方法、证据用法和表达节奏；用户手工 Notion 报告只贡献策略意图、字段语义和观望边界。二者均不得贡献旧行情、方向、评分、置信度、价位、仓位、风险结论或措辞。
> 运行期只读取本契约、本轮密封证据和 phase manifest。producer shape/leaf ownership 只以 `scoring/reasoning_submission_contract.json` 为机器真相；业务枚举、字段及真值表只以 `scoring/scoring_contract.json` 和 `governance/vnext_daily_workflow.md` 为机器真相。

## 1. 对齐目标与顺序

金标对齐是对齐观察 → claim → 反证 → 失效 → 情景 → 决策闭环，不是复制旧稿长度、数字数量或排版痕迹。固定顺序：

1. 完成本 slot 六源验真、转录和不可变证据密封。
2. vNext 请求 exact `gpt-5.6-sol/xhigh`；实际 `max|ultra` 只证明 `>=xhigh`，不改请求且非正确性依赖。结构化完成 observation、claim、current basis、future trigger、scenario 与 account decision。
3. 先密封独立推理和对抗反证，再允许 source/hash-bound 连续性事实进入；连续性只处理撤旧、保留、挂新与防守衔接，不回写市场判断。
4. compiler 从同一批 typed 制品确定性生成前台、Word、PDF 和逐页 PNG；报告或交付失败只在本阶段局部纠正，不重采、不重推。

## 2. 六源作用与增量边界

- BlockBeats：只提供密封 top3 事件事实与层级；逐事件兑现由跨源 claim 判断，综合价格兑现必须结合 TradingView。
- FedWatch：描述宏观概率环境和边际变化，不直接决定 Maker 方向，也不作为计划时置信度 adjustment。
- Farside：只提供最新完整日 ETF 流量事实；价格×流向关系按 3×3 合同形成 confirm/weaken/neutral，不能单变量翻向。
- Coinglass：同一 1H pivot 读取价格、CVD、OI、资金费率和清算通道，是 Maker 盘口主判。
- Exocharts：固定 Bybit BTCUSD 日线足迹配置，校验主动成交、Delta、CVD、POC 与吸收；只确认、削弱或反驳盘口主判。
- TradingView：负责 1D/4H/1H/15m、SMA20、结构区与位置质量。平台 VRVP 禁用；只承认本轮可读的用户手绘成交量分布区域。

VRVP/流动性猎杀、清算地图和 ETF 是增量维度：只表达位置、概率或确认强弱，不替代同 pivot 四维、足迹、多周期结构和账户优先级。手绘区域不足时明确 insufficient，不由清算图或辅助价位补值。

## 3. 账户、反证与情景

- 主账户：基本面 > 盘面 > 盘口；Maker：盘口 > 盘面 > 基本面。两者只共享六源 observation 与账户中立解释，各自拥有 regime、thesis、最强反证、失效和 base/counter/invalidation 三情景。
- `current_basis` 只证明当前反证/失效为何存在；`trigger_logic` 只描述未来何时增强或触发，二者分别是当前/未来控制语义唯一可见、唯一承重真相。自由 `conclusion`/`invalidation` 只供上游门内审计，不得进入 reasoning proof、scenario condition、报告或交付面；compiler 不得从方向、历史措辞或自由文本补条件。
- `account-trigger-logic-v5`：`any` 每条独立同向且当前均 false；`all` 同极性、同 field target 交集非空且至少一条 false；`one_of_at_trigger` 单极性。唯一 Coinglass/Exocharts `all` 对：reference target=current → `equals_at_trigger`，否则 `becomes`；relation=`equals_at_trigger`。runtime 只投影 operator；绑定／真值／方向无效即失败。
- 六项 scenario 使用 `scenario-ownership-v1` 的 exact `id/account/scenario_type/owner_claim_id`。模型只拥有 typed thesis/counter/invalidation 与其 `current_basis/trigger_logic`；同一个已密封 reasoning attempt 内的 runtime 从唯一同账户 typed owner 生成 top-level 六格、methodology 同格 `claim_id`、scenario type 对应 closed transition code，并把 owner 的 direct claim supports 按原顺序去重投影为 `trigger_claim_ids`。模型提交的 scenario/methodology 包装值、账户 claim 绑定、冲突政策、订单流 source-domain 到 claim-domain 的方向映射和 `pipeline_units` 均不构成第二 authority。compiler 从 base owner 的 typed direction 或 counter/invalidation owner 的 `trigger_logic` 投影 condition，并从 transition code 投影 expected path/action；真实订单生命周期仍只由 Decision 与 continuity 拥有。
- Enforce contract's disjoint/exhaustive 54-leaf ownership: deterministic server paths; 8 model business leaves; one `selected_event_sha256` producer key. Unclassified leaves hard-stop preflight; runtime never repairs business judgment or alters/infers/reorders the key.
- `cannot_do` 只属于 Maker，必须在 Maker 完整闭环后最后生成且 output-only；不得进入任何前置 claim、情景、评分、置信度或方向。
- 冲突必须保留。例如基本面偏暖而盘口承压，可以形成主账户等待、Maker 压力区短线，禁止为叙事一致强行同向。

## 4. 评分与计划时置信度

- 当前 production 盘口为任意整数 0–60，61–69 非法，70 仅为未来原生证明能力保留；盘面 0–30 只评价机会质量。先自然落分，再比较总分 65。
- 计划时置信度顺序固定：两轴 anchor → `adjustments[0]` 当前 Maker 最强反证负调整 → 独立 ETF adjustment → final → 比较 60。当前 `fundamental-event-assessment-v1` 没有 event-aligned price attribution basis，固定 `load_bearing_allowed=false + observation_only_reason_code=event_price_attribution_unavailable`，禁止用于 `winrate_adjustment|account_current_basis|account_trigger_logic`；`fundamental_price_realization` 必须为 `no_adjustment / event_price_attribution_unavailable`。只有未来认证价格归因 basis 后才可按 `price_attribution_basis_required_to_reenable=true` 重新承重。
- anchor 只绑定 shared|maker 的两条原始证据轴：Coinglass+Exocharts 可达的 orderflow 轴，以及 TradingView 可达的结构位置轴。主账户、thesis、regime、counter、cannot-do、基本面和 ETF claim 均不能充当 anchor。
- `anchor_rationale` 必须精确使用 authority canonical 文本；市场依据只由 typed anchor claim/source 拥有，compiler 不保留或编造自由文本市场解释。
- `adjustments[0]` 必须是 `maker_counter_current`，完整覆盖当前 Maker 最强反证的全部 current-basis clauses；不存在 resolved 后免调。ETF/基本面调整只能排在其后，FedWatch、footprint/orderflow、chart/structure 和清算地图不得重复计证。
- final 完成后才比较门槛；入场价格触达概率只衡量当前价到挂单价格的可达性，独立 `order_lifecycle` 只证明是否存在合法成交/撤单路径，盈亏比只属于风险数学；三者均不能替代计划时置信度，系统不估计订单实际成交概率。

## 5. 入场、止损与风险

- Maker 入场必须是 TradingView 认证价格区间内 2–5 档 ladder，比例合计 100%；single、代表价、清算图和 Exocharts POC 不得冒充 entry zone。
- 主账户初始止损只用自身 1D/4H 结构，全部非空成交组合不高于 8%；Maker 使用自身 4H/1H/15m 结构，全部组合同时满足不高于 3% 与 TP1 R:R 不低于 1:2.5。两账户不得串线。
- 结构噪声 buffer 不是风险门槛倒推公式。同账户 `invalidation_path` 必须在 reasoning 阶段密封 exact `structural-noise-buffer-v2`，绑定 support DAG 可达的本轮 TradingView observation、账户允许 timeframe、同周期截图、可机械定位的结构锚与图上 `noise_outer_boundary`，并固定 `risk_budget_input_used=false`。
- `status=certified` 时 decision stop basis 中实际存在的 identity/anchor/distance 字段必须精确等于 reasoning owner，Gate 另读 reasoning 的 status、visual evidence 与 boundary，并验证最终 stop 严格越过外边界；`status=insufficient` 时只允许闭合原因并保持 `observe`。3%/8% 与 R:R 只能后验，禁止压缩结构止损。compiler 只校验和投影，不得推断。
- 机械合同只能证明“证据绑定、方向化边界、先密封、后验算、下游不漂移”，不能读取模型在 reasoning 时的隐藏意图，也不能替人判断截图中的外边界是否识别正确。fresh 样本仍须人工复核；不得用任意最小点数、ATR 倍数、风险派生公式或新硬门伪装成证明。
- Maker 两层浮盈防守必须展示阿拉伯数字精确触发价：prefill 覆盖计划全档锚和全部成交组合，成交后按 actual weighted fill 重算；未来 4H 极点止损价不得预填。TP1 减仓 50%，TP2 清剩余 50%。
- Maker 报告语义必须由 `risk_plan` 是否非空作为候选是否已提交的唯一 owner，并互斥归类为 `maker-semantic-state-v1` 四态：`qualified_candidate`、`rejected_submitted_candidate`、`directional_thesis_only`、`non_directional_observation`。被拒态允许 `plan_constructible=true|false`，因为只要 `plan_state=observe + risk_plan` 非空就已有提交候选；其原始候选生命周期只可在附录 D 以不可执行审计保真。后两态必须明确披露“未提交候选计划”，不得称为候选/被拒候选、投影计划数字，或在情景中携带未被明确否定的候选执行生命周期。报告 evaluator 必须从 audit 重建 Maker summary、Maker execution 前台与主账户授权，不能反向相信可见摘要。

## 6. 人类可读投影与验收

正文可以精炼，但③后附必须让人直读六源的作用、事实、判断价值和边界，并保留同锚盘口、足迹、多周期、增量维度、双账户反证/失效、评分/置信度、风险和情景链。数字必须嵌入对应推理节点，禁止末尾堆锚点组。

主账户与 Maker 的 base/counter/invalidation 六个完整情景，以及两账户各自的“当前最强反证／未来反证触发／当前失效基线／未来失效触发”八个闭环标记，只能在附录 D 各详细出现一次；正文与附录 C 只保留指向附录 D 的短引用，不得复制完整情景树或完整 future trigger。

Word/PDF/逐页 PNG 必须同源确定性派生。Word passed 必须使用 exact `word-qa-vnext-v2`、authority 定义的 exact checklist 版本与键集合，并且所有检查项均为 boolean true；价格数字保持阿拉伯数字。vNext 切换前禁止发布 Notion。

## 7. 红线

- 禁止运行期重读历史 Word/Notion 样本，禁止复制旧方向、分数、置信度、价格或措辞。
- 禁止为了像金标而补字数、rubric、价位或模板段落；格式不得反向驱动交易判断。
- 禁止用 lint、布尔 PASS、长文本或测试样本冒充推理深度、真实视觉验收或市场事实。
- 任何与 machine truth 不一致的自由文本都无效并硬停；不得用配置、compiler 推断或历史经验补规则。
