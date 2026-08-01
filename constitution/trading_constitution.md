【核心理念】
"错过不是错误，乱做才是"
"这笔交易，是系统在执行，还是我在加速？"

> **引擎边界**：本文只定义业务方法与账户边界，不定义运行命令。vNext 只使用当次 run 密封的 phase manifest 和当前 slot 证据；禁止读取 legacy SOP、旧报告、历史价格或未绑定的实仓快照。


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、系统架构总览
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

日报主分析标的：BTC；Maker 可执行标的与名义仓位范围只认当前 `scoring/scoring_contract.json`。
交易所分工：
  Binance：主账户中线连续性
  OKX：Maker 账户日内计划

账户体系：三账户体系（官方定义）
  ┌──────────────┬────────────────────────┬──────────────────────────┐
  │   主账户        │    Maker账户            │    Taker账户（已暂停）   │
  ├──────────────┼────────────────────────┼──────────────────────────┤
  │ 低频中长线      │ 日内交易（波段/博弈）    │ 机会博弈（右侧/盘口）    │
  │ 日/周/月级别    │ 高空低多/反弹空         │ 每日≤1次，周≤3次        │
  │ 自身中线大方向  │ 自身日内"不能做"(末位) │ 不参与当前日报决策       │
  │ Binance（中线）│ OKX                    │ 暂停执行                 │
  └──────────────┴────────────────────────┴──────────────────────────┘

注：Taker 已暂停，不得作为当前日报的第三条决策链，也不得与主账户或 Maker 合并推理。
注：中线计划与 Maker 计划**互不干扰**；主账户不约束 Maker、不发"不能做"。Maker 的"不能做"是其当天日内、写完整份报告后最后回填的收口结论。

风险上限同样按账户分离：主账户四档中线计划对全部非空成交组合逐一复算，5x 名义风险均不得高于 **8%**；Maker 对全部非空成交组合仍须同时满足 TP1 盈亏比不低于 1:2.5、5x 名义风险不高于 **3%**。两者统一使用 `abs(weighted_entry-stop)/weighted_entry*leverage*100`，不得把 Maker 的 3% 上限误套到主账户，也不得用主账户的 8% 放宽 Maker。

主账户初始止损使用独立的中线政策：由主账户 `invalidation_path` 选择本轮 TradingView 认证的 1D/4H 真正失效结构，禁止借用 Maker 的 4H/1H/15m 止损政策，也禁止用 1H/15m 作主账户初始止损主锚。当前 active 锚只允许带 timeframe 的 readable 手绘 profile 外沿或非当前入场区 structure zone 外沿；裸支撑/阻力/摆动价格数组只供展示，不能主观贴周期后充当止损 authority。structure zone 用于空单时 role 只允许 `resistance|breakdown_retest`，用于多单时只允许 `support|breakout_retest`。结构噪声外扩不是 8% 倒推公式：同一主账户 `invalidation_path` 必须在 reasoning 阶段用 exact `structural-noise-buffer-v2` 密封。`status=certified` 只适用于 `long|short`，必须使用 `method_code=pre_risk_tradingview_structure_noise_judgment`，绑定 support DAG 可达的本轮 TradingView `observation_id`、`1d|4h` timeframe、同周期 `visual_evidence_ref`、可机械定位的 `anchor_kind/anchor_source_field/anchor_price`、图上可见 `noise_outer_boundary`、正 `price_distance`，并固定 `risk_budget_input_used=false`；最终方向化止损必须严格越过该外边界。图像无法读取时使用 `status=insufficient + visual_noise_envelope_not_readable`；主账户 `neutral` 时使用 `status=insufficient + not_applicable_non_directional_thesis`，两类 insufficient 都必须令 anchor/boundary/distance 为空并保持 `observe`。decision stop basis 中实际存在的 observation/timeframe/anchor identity/price/distance 必须精确等于 reasoning owner，并保留同账户 `buffer_claim_id`、`buffer_basis_code=current_run_typed_market_noise_allowance` 与 `buffer_backsolved_from_risk=false`；Gate 另行验证 status、截图、外边界与严格越界几何，compiler 不得推断。8% 只在结构止损确定后验算，不得压缩已密封的结构止损。

Maker 初始硬止损必须先由同账户 `invalidation_path` 从本轮 TradingView 认证结构中选择真正的结构失效锚：锚点须可机械定位，并严格位于 `entry_zone` 与全部挂单价外侧。当前 active 合法来源只允许带 timeframe 的 `status=readable`、`user_drawn_manual_only` 手绘 profile 中性外沿（空单上沿、多单下沿），或非当前入场区的认证 structure zone 外沿；裸支撑/阻力/摆动价格数组只供展示，禁止主观贴周期后充当锚。空单 structure zone role 只允许 `resistance|breakdown_retest`，多单只允许 `support|breakout_retest`；手绘 profile role 不承担方向语义。当前入场区边界本身禁止。不强制数值最近层，也不得把弱中间结构硬编码成止损锚。锚点外的结构噪声 buffer 必须由同一 Maker `invalidation_path` 在 reasoning 阶段以 exact `structural-noise-buffer-v2` 密封。`status=certified` 只适用于 `long|short`，必须使用 `method_code=pre_risk_tradingview_structure_noise_judgment`，绑定其 support DAG 可达的本轮 TradingView `observation_id`、`4h|1h|15m` timeframe、同周期 `visual_evidence_ref`、可机械定位的 `anchor_kind/anchor_source_field/anchor_price`、图上可见 `noise_outer_boundary`、正 `price_distance`，并固定 `risk_budget_input_used=false`；最终方向化止损必须严格越过该外边界。图像无法读取时使用 `status=insufficient + visual_noise_envelope_not_readable`；Maker `observe` 时使用 `status=insufficient + not_applicable_non_directional_thesis`，两类 insufficient 都必须令 anchor/boundary/distance 为空并保持 `observe`。decision stop basis 中实际存在的 observation/timeframe/anchor identity/price/distance 必须精确等于 reasoning owner，并保留同账户 `buffer_claim_id`、`buffer_basis_code=current_run_typed_market_noise_allowance` 与 `buffer_backsolved_from_risk=false`；Gate 另行验证 status、截图、外边界与严格越界几何。3%/R:R 只在结构止损确定后验算，禁止倒推压缩，compiler 不得推断。浮盈防守的第一、第二层都必须展示阿拉伯数字精确触发价：未成交时由控制器按计划全档加权锚和全部非空成交组合确定性计算，成交后按实际加权成交价重算并替换为唯一值。计划加权锚只服务风险/防守投影，不是单点入场或实际成交事实；未知的未来 4H 极点止损价仍禁止预填。

每日三个独立报告节点：
  - 早间盘前：主账户日报 + Maker上午计划
  - 午间：主账户与 Maker 均基于本 slot 六源证据独立重算
  - 晚20:00-20:30：Maker晚间新增计划


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一·补、框架优先级（三层权重按账户分流）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

三层 = 盘口（Coinglass 同一 1H 价格 pivot 四维 + Exocharts 足迹印证）/ 盘面（TradingView 1D/4H/1H/15m 结构）/ 基本面（BlockBeats 事件 + FedWatch 宏观 + Farside ETF 现货侧确认）。
**权重顺序随账户角色翻转，不可混用：**

  ┌────────────────────┬──────────────────────────────┐
  │ 日内 Maker 交易      │  盘口 > 盘面 > 基本面          │
  │ 中线计划（主账户）   │  基本面 > 盘面 > 盘口          │
  └────────────────────┴──────────────────────────────┘

【日内 Maker：盘口 > 盘面 > 基本面】
  - 方向盘 = 盘口（C01–C81 客观骨架 + 综合订单流方法论；schema 名义容量 70 分）。当前 production 盘口输出只允许 0–60 内任意整数；61–69 非法，70 为未来原生结构化证明能力的保留值，未启用且不得仅靠配置开启。盘面（30 分）只评价机会质量与入场位置，不表达方向。
  - 基本面权重最低，**不参与方向打分**，只起两个作用：
      (a) 风险否决：重大政治/宏观突发 → 强制观望（呼应"重大新闻强制观望"）；
      (b) 与盘口方向冲突 → 降低信心/降频，但不得据基本面反向。
  - 一句话：基本面对 Maker 只能"踩刹车"，不能"打方向盘"。

【中线计划（主账户）：基本面 > 盘面 > 盘口】
  - 方向盘 = 基本面综合层：BlockBeats 只负责事件事实与层级；价格兑现由 BlockBeats + TradingView 共同支持的 `fundamental_price_realization` 跨源 claim 负责。FedWatch 只描述宏观预期，Farside 只按确定性 3×3 价格×流向关系确认、削弱或保持中性；任一单源都不得独立翻向。
  - 盘面（日/周/月趋势结构）= 决定入场区与分批 4 档位置。
  - 盘口权重最低，仅作择时微调，**禁止据盘口短期背离推翻中线大方向**。
  - 一句话：中线方向盘在基本面手里，盘口只是中线进出场的择时辅助。

BlockBeats top3 事件必须逐条生成闭合 `fundamental_event_assessments`：事件事实只从密封工件按 hash 投影；每个事件绑定同 hash 的 shared `fundamental_event_realization`，原 `fundamental_price_realization` 只保留为唯一综合兑现 owner。模型只填写闭合影响通道、预期作用、逐事件兑现 claim、共享反证 claim 与使用边界，不得改写事件事实或把新闻直接当方向。主账户与 Maker 的最强反证和失效路径还必须分别写 `current_basis`，用 `equals` 精确引用当前 typed owner 值；它与未来才可能发生的 `trigger_logic` 严格分开。胜率次因只允许 contract 内闭合 `reason_code`，delta 符号、claim/source 与 typed value 必须匹配；自由 label/rationale 不得成为前台事实。

未来反证与失效触发遵守 `account-trigger-logic-v5`：`any` 每个 clause 都是同向反证的独立充分条件；`all` 可含无方向辅助，但方向条款不得支持原方向或混合极性，同一 typed field 的 target 交集须非空；`one_of_at_trigger` target 须同极性。Exocharts 仅可在同一 `all` 中绑定唯一 Coinglass `final_direction` reference：reference target 等于认证 current value 用 `equals_at_trigger`，不等用 `becomes`；Exocharts relation 用 `equals_at_trigger`。当前真值按 mode 聚合：`any` 任一 clause 已满足即整组已触发，故全部 clause 均须尚未满足；`all` 仅在全部 clause 已满足时触发，故至少一个须尚未满足。runtime 只可投影这两个 operator path，不得改 clause 数量／顺序、target、relation、mode/effect、support DAG 或账户方向；reference 缺失、多条或歧义须 fail-closed。`claim-topology-v1` 是 producer 可见且由 Gate 通用解释的机器拓扑；runtime 禁止注入 support edge。每个账户的 `strongest_counterevidence` 与 `invalidation_path` 是并列控制节点，失效路径只须可达本账户 `market_regime`，不得隐藏要求依赖最强反证；Maker `cannot_do` 仍须显式可达 thesis、最强反证、失效路径与市场状态。六项 scenario 服从 `scenario-ownership-v1`；模型只负责本账户 thesis、`strongest_counterevidence`、`invalidation_path` 及其 typed `current_basis/trigger_logic`。在同一个已密封 reasoning attempt 内，runtime 从唯一 typed owner 确定性生成 exact `id/account/scenario_type/owner_claim_id`、methodology 同格 `claim_id`、closed transition code，并将 owner 的 direct claim supports 按原顺序去重投影为 `trigger_claim_ids`；任何模型提交的同名包装值都不是 authority。compiler 只从 base owner 的 typed direction、counter/invalidation owner 的 typed `trigger_logic` 与 closed transition code 确定性投影中文。typed enum 与 closed code 是控制事实唯一真相；对应自由中文只保留分析与审计颗粒度，禁止通过关键词反推或否决 typed 状态。真实订单生命周期只由 Decision 与 continuity 拥有，scenario 不得成为第二执行真相。

reasoning methodology 的 54 个叶必须被当前 submission contract 穷尽且互斥分类；未分类即 preflight 硬停。runtime 只拥有可从密封身份、唯一 typed owner、上游 typed 值或 authority 常量机械得到的 identity/mirror/constant，以及 account/scenario 完整 subtree。模型只保留 `independent_synthesis` 四个选择叶、逐事件 impact/effect/counter 三叶和 `transition_summary` 共 8 个业务叶；`fundamental_event_assessments[*].selected_event_sha256` 只是从密封 top3 选择的行 key，runtime 可据此绑定同 hash realization claim，但不得改写、重排或猜测该 key。

【计划时置信度闭环（Maker 专属）】
  - 先由两条原始证据轴自然形成 anchor：盘口轴只认 support DAG 同时可达 Coinglass+Exocharts 的 `orderflow_interpretation`，结构位置轴只认可达 TradingView 的 `chart_interpretation|invalidation_path`；只允许 `shared|maker` claim。主账户、`maker_thesis`、`market_regime`、最强反证、`cannot_do`、基本面/ETF claim 均不得充当 anchor。`anchor_rationale` 必须精确使用 authority 的 `anchor_policy.canonical_rationale`；市场专属依据只认 typed claim/source，compiler 不得保留或编造自由文本锚点解释。
  - `adjustments[0]` 必须是当前 Maker 最强反证的 `maker_counter_current` 负 adjustment，并按原顺序覆盖其全部 `current_basis` clause；ETF/基本面调整只能排在其后。`counter_resolution` 只能是 `disposition=adjusted` 且 `resolution_claim_ids=[]`，不存在 `resolved_no_adjustment`。原反证若已不成立，必须重选当前真正最强反证，不能省略或后移扣分。
  - 之后只允许 ETF 确认/削弱与基本面价格兑现确认/削弱作为独立 adjustments。FedWatch、清算地图、资金费率单变量、执行概率、风险数学，以及已经进入 anchor 的盘口/足迹/盘面结构均不得重复加减；anchor 与 adjustment、各 adjustment 之间禁止重复计证。
  - 先机械复算 `final=anchor+Σadjustments`，再比较 60%，再与总评分 65 合成 `threshold_eligible`，最后才结合 `plan_constructible` 落 `qualified|observe`。任何计划状态都不得反向修改 anchor、adjustment 或 final。

⚠️【当日 Maker 交易的两层边界】
  ┌──────┬──────────────────┬────────┬──────────────────────────┐
  │ 层级  │ 字段              │ 谁填    │ 含义                      │
  ├──────┼──────────────────┼────────┼──────────────────────────┤
  │ 第一层│ 开仓前执行资格    │ 外部事实│ 今天能不能真实执行          │
  │ 第二层│ 不能做（终局限制）│ 系统填  │ 独立方向完成后校验禁令相容性│
  └──────┴──────────────────┴────────┴──────────────────────────┘
  - **开仓前执行资格不参与市场方向**：vNext shadow 只生成和验证计划，不读取外部主观状态、不发布、不执行真实订单；缺少 live 执行资格不得污染六源判断或 shadow 样本质量。
  - **不能做=系统填**：由**系统**通过当天数据分析推导（日内 Maker = 盘口>盘面>基本面 = "禁止追当下最拥挤的一边"，详见 §2.5 + `cannot_do_mapping.md`）。
  - **"回填"含义**：Maker thesis、最强反证、失效路径和 base/counter/invalidation 三类情景全部完成后，才**填出不能做**（= 分析的末位收口结论），**不是**"全天交易做完后"才补；页面显示在顶部不代表它最先推导。它是 output-only 终值，不得被任何 observation、claim、反证、失效、方法论情景或账户情景引用。
  - **不能做是当日 Maker 计划的终局限制，宪法级**：只能在全部独立推理完成后校验 Maker 计划与当日禁令是否相容，不得生成、反推或翻转方向（risk_agent Gate3，无 override），也不得作为任何前置推理节点的输入。
  - **归属**：「不能做」是**当天 Maker**字段，与中线/主账户大方向无关，二者不混淆（中线与 Maker 互不干扰）。

注：评分 schema 的名义容量为盘口70+盘面30，基本面在分外作否决；当前 production 有效口径为盘口0–60+盘面0–30（总分最高90）。70 仅为未来保留能力，61–69 始终非法。


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
十、主账户日报模板（严格格式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[日期]

不能做：[追多空 / 做多 / 做空]
  ⚠️ 此字段=当天 **Maker** 日内禁令，与中线无关；**写完下方全部内容后最后回填**（显示在顶、推导在末）。推导走"盘口>盘面>基本面=禁追最拥挤一边"。

基本面：[利多/利空/中性/中性偏多/中性偏空]（[原因]）价格[已兑现/未兑现/已兑现部分]
[重要新闻（含时间戳，来源BlockBeats截图）]

技术面：
盘口（合约）：
CVD[上升/下降/横盘] 价格[方向] 资金费率[状态]（[为正值/为负值/接近0值]）持仓[方向]
解读：[中性/中性偏多/中性偏空/看跌背离/看涨背离]（[原因]）

盘面：
日线级别[分析内容] [综合判断]
小时级别[分析内容] [综合判断]

趋势确认：[多头趋势/空头趋势/震荡结构]（[短线/中短线/单边]）
日内支撑：[价格区间]    日内压力：[价格区间]

策略：
[中线计划内容/迭代/保持不变]


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
十一、Maker日内策略模板（严格格式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【早间盘前】
BTC（策略）：
[观望] → `threshold_eligible=false`，或 `plan_constructible=false`。后者包括：没有本轮 TradingView 认证高质量 `entry_zone`、计划与 Maker-only `cannot_do` 冲突，或候选阶梯自身风险数学不成立。门槛资格与计划可构造性都成立时必须生成「有计划」限价阶梯；不得以执行概率低、距离远或 live 执行资格关闭来降格候选计划。
[执行状态] → 与计划结论分层。shadow 固定不尝试执行；production 的开仓前执行资格只决定真实下单、阻断或仅观察，不得反向改写计划、方向、评分、胜率、价格或风险。
[有计划] →（总分 ≥65、计划时置信度 ≥60%，且 `plan_constructible=true` 时必填此项）
  执行概率X% 计划时置信度X%（非回测命中率）
  [高空/低多/反弹空]：[完整价格区间；绑定本轮 TradingView 认证 `entry_zone` 的上下界，并在区间内离散为 2–5 档真实不同的阿拉伯数字价格，逐档比例合计 100%] 持仓[金额]刀 [OKX] [左侧/右侧] 5x 盈亏比1:2.5以上
  止盈：[价格]（TP1）减仓X%；[价格]（TP2）减仓剩余仓位
  开仓前取消价：[价格或结构条件]
  成交后硬止损：[价格；绑定同账户 invalidation_path 的本轮结构失效锚 + reasoning 阶段 exact `structural-noise-buffer-v2` 的 `status=certified`、`method_code=pre_risk_tradingview_structure_noise_judgment`、TradingView `observation_id/timeframe/visual_evidence_ref/anchor_kind/anchor_source_field/anchor_price/noise_outer_boundary/price_distance` 与 `risk_budget_input_used=false`；decision 精确复制实际使用的 identity/anchor/distance，Gate 验证止损严格越过外边界，风险阈值不得倒推压缩，compiler 不得推断]
  浮盈防守计划：
    第一层：[阿拉伯数字精确触发价；未成交时同时标明计划全档加权锚及部分成交情景范围] → [成交后后续确认的 4H 极点移损；未来极点价不预填]
    第二层：[阿拉伯数字精确触发价；同一成交情景口径] → [只把剩余止损移至实际加权成交价保本]
  注意事项：开仓前若价格优先触及取消边界则撤单；成交后只能执行硬止损与浮盈防守，不得把取消价冒充止损

认证 `entry_zone` 只能来自本轮 TradingView 可读用户手绘区域，或本轮 1D/4H/1H/15m 结构明确给出上下界的高质量边缘。手绘 profile 不足时可以使用认证结构区间，但 Coinglass 清算图、Exocharts POC、区间中点或单一代表价均不得补位。没有认证区间时必须观望。

当前 production 盘口只允许 0–60，61–69 一律非法，70 不可用。未来若另行实现并批准原生结构化真极端证明验证器，70 仍只可能用于 C19/C22/C56/C59 且必须满足同一 1H pivot、极端组合、效果背离、OI/价格语义、资金费率仅修正且未单变量翻向、Exocharts `confirm`、最强反证与失效路径闭环；不得通过配置单独启用。

【午间独立计划】
不能做：[操作禁令]
BTC（策略）：[同上格式，但全部事实、评分、区间与情景用本 slot 重算]

【晚20:30新增计划】
不能做：[操作禁令]
BTC（策略）：[同上格式]


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
十二、判断词汇标准库（必须严格使用）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

趋势确认：
  多头趋势（单边）/ 多头趋势（中短线）/ 空头趋势 / 震荡结构

基本面判断：
  利多 / 利空 / 中性 / 中性偏多 / 中性偏空

盘口解读：
  中性 / 中性偏多 / 中性偏空 / 看跌背离 / 看涨背离

价格兑现：
  已兑现 / 未兑现 / 已兑现部分

策略方向：
  高空 / 低多 / 反弹空 / 观望

入场方式：
  左侧 / 右侧

持仓周期：
  长持（走计划看盈亏比）/ 短线 / 实时盯盘
十六、输出规范（每日日报）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

格式：可见报告、canonical `.docx`、PDF 与逐页 PNG 必须由同一锁定制品确定性派生；发布、保存位置与文件命名由当前引擎控制合同决定，不得反向影响交易判断。

严格要求：
  1. 禁止无证据臆造；在完整方法论内推理，任一承重证据不足则标记不可用并按引擎合同硬停
  2. BlockBeats新闻必须截图，不得用文字生成替代
  3. 所有判断词汇必须使用标准库中的词汇
  4. 数据来源必须基于当日实时抓取（不得使用历史数据替代）
  5. 准确性是第一优先级，宁缺毋滥
  6. 任一必需数据未能采集或无法验证时，按当前阶段合同标记证据不足并硬停；禁止用"待补充"占位后继续推理或交付
  7. vNext Word QA 只有 exact `word-qa-vnext-v2` 才可通过；`status=passed` 时 `review_checklist_version` 必须精确等于 `word-qa-semantic-review-v1`，且 checklist 只能包含 `all_pages_inspected`、`no_clipping_overlap_or_missing_glyphs`、`no_orphan_semantic_headings`、`critical_price_blocks_not_split`、`six_source_sections_readable`、`arabic_price_digits_preserved` 六键并全部为 boolean `true`
