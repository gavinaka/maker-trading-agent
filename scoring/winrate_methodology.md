# 计划时置信度方法论（Maker 开单硬门槛②）

> 本文件是系统自估“胜率”的唯一业务口径。对外固定写作**计划时置信度，非回测命中率**。
> 在具有充足、独立、定义一致且带真实结局的样本并完成校准检验前，`calibrated_probability=false`、`calibration_status=insufficient_outcome_samples`；禁止把自估百分比解释为真实命中率、稳定收益率或模型已校准证明。

## 1. 三轴严格分离

- **计划时置信度**：当前证据对 Maker thesis 的支持强度与反证可控程度，取 0–100 的整数。
- **入场价格触达概率**：当前价在计划窗口内触达挂单价格的可能性，只是软参考，不进入计划时置信度；它不是订单实际成交概率。
- **盈亏比**：入场、止损与 TP 的独立风险数学，必须满足自身合同，不进入计划时置信度。
- 三轴不得互相替代：高置信度不代表高可达，高盈亏比也不证明方向更可能成立。

## 2. 取值与门槛

- 计划时置信度使用 0–100 连续整数，实际证据支持多少就落多少；禁止固定三档、只给整十/整五或为了过门槛凑值。
- 硬门槛仅为 **60%**：最终值 ≥60% 满足门槛②，<60% 不满足。
- 必须严格按 `anchor → 当前 Maker 最强反证负 adjustment → 其它独立 adjustments → final → 60% 门槛` 完成；禁止先看开单结果或门槛倒推数字。
- 盘口总分、盘面分和计划时置信度相关但不等价；禁止用总评分线性换算置信度。

## 3. Anchor：两条主轴联合确定

Anchor 只能由当前推理 DAG 中 `account=shared|maker` 的允许 claim IDs 确定，并同时回答两条主轴：

1. **盘口轴**：必须绑定 `orderflow_interpretation`，且其 support DAG 同时可达 Coinglass 与 Exocharts；它回答同一 pivot 四维是否闭环、足迹是确认／削弱／冲突，而不是把足迹另作加减分。
2. **结构位置轴**：必须绑定 `chart_interpretation` 或 `invalidation_path`，且其 support DAG 可达 TradingView；它回答 1D/4H/1H 结构、Maker 入场位置与结构失效边界是否明确。可选 `liquidity_hunt` 只能补充位置/概率，不能代替该轴。

主账户 claim 一律禁止进入 anchor。`maker_thesis`、`market_regime`、`strongest_counterevidence`、`cannot_do`、`fundamental_context`、`fundamental_price_realization` 与 `etf_confirmation` 也不得充当 anchor；这些结论层或独立次因不能冒充两条原始证据轴。

连续估值边界：

- 任一主轴缺证据或自身闭环不足：anchor 必须 <60。
- 两轴均有效但确认一般、冲突仍显著：anchor 可落 60–69 的任意整数。
- 一轴强、另一轴至少明确且两轴自身冲突有限：anchor 可落 70–79 的任意整数。
- 两轴均强、跨源一致、位置和失效高度清晰：anchor 可落 80–89 的任意整数。
- ≥90 只允许两条 anchor 轴的多源证据极强一致、结构位置高度清晰；在未校准阶段必须保持罕见，并明确轴内残余不确定性。当前 Maker 最强反证仍须在下一步强制负调整，不能被高 anchor 吞并。

区间只是证据强度边界，不是固定档位。anchor 必须绑定支持两轴的允许 claim IDs；具体市场依据只由这些 typed claims 与其可达来源拥有。`anchor_rationale` 不是模型自由填写的市场解释，必须被当前 authority 的 `anchor_policy.canonical_rationale` 精确规范化；compiler 只能把 canonical 文本与机械验证出的两轴 claim/source 投影成人类说明，禁止保留、拼接或推断任何自由文本市场事实。anchor 只评价两轴，不得提前读取计划状态、门槛结果或反证处理结果。

## 4. Adjustments：只处理独立次因

Anchor 后逐项加入有符号整数 adjustments，顺序不可改变，最终值必须满足：

`final = anchor + Σ adjustments`

`adjustments[0]` 必须是当前 Maker 最强反证的负 adjustment；任何 ETF 或基本面兑现 adjustment 都只能排在其后：

- `counter_resolution` 必须使用 `maker-counter-resolution-v2` 的 exact 字段，`disposition` 只能为 `adjusted`，`adjustment_reason_code` 只能为 `maker_counter_current`，`resolution_claim_ids` 必须为 `[]`。
- 该 adjustment 必须绑定本轮 Maker `strongest_counterevidence`，为负整数；`residual_clause_indexes` 必须按原顺序覆盖该 claim 的全部 `current_basis.clauses`，不得挑选、遗漏或伪称已经解决。
- 不存在 `resolved_no_adjustment`。若某一反证已不再成立，模型必须重新选择当前真正最强的反证；任何当前最强反证都必须扣分。

在强制反证 adjustment 之后，当前合法的独立次因只包括：

- `etf_confirm|etf_weaken`：只绑定 Farside 与同锚价格共同形成的 `etf_confirmation` typed claim。上涨+流入/下跌+流出=`confirm`，上涨+流出/下跌+流入=`weaken`，其余 5 格=`neutral`；neutral 不生成 0 adjustment。
- `fundamental_confirm|fundamental_weaken` 仅保留为未来兼容枚举。当前 `fundamental-event-assessment-v1` 没有逐事件时间对齐的价格窗口与方向归因，固定为 observation-only；`fundamental_price_realization` 必须使用 `no_adjustment / event_price_attribution_unavailable`，不得进入 adjustment、账户 current basis 或 future trigger。只有未来另行认证 event-aligned price attribution basis 后，才可重新申请承重资格。

每个 adjustment 必须使用 closed `reason_code`，绑定本轮允许 claim IDs 与 certified typed values，且 delta 为非零整数并符合合同规定的正负号。`reason_code` 必须唯一；单项 claim IDs 不得重复，不同 adjustment 的 claim IDs 与 typed owner signatures 必须互斥；anchor 与 adjustment 禁止直接复用同一 claim。

`label` 与 `rationale` 只供 gate 审计，不是前台业务事实；compiler 只可投影 `reason_code + delta + claim_ids + typed_values`。入场价格触达概率、订单生命周期、盈亏比、主账户结论、历史胜率、旧报告、FedWatch、清算地图、资金费率单变量均不得成为 adjustment。Coinglass/Exocharts 的盘口与足迹、TradingView 的结构/位置已经属于 anchor 两轴，禁止再以 orderflow、footprint 或 chart adjustment 重复计入。

## 5. 复算与反证

1. Anchor 的 claim 只能来自 `shared|maker` 允许类型，禁止 observation ID、主账户 claim 或结论层 claim 混入。
2. 当前 Maker 最强反证必须通过 `adjustments[0].reason_code=maker_counter_current` 的负 adjustment 全量承接其全部 `current_basis` clause；不得省略、挑选、后移或声明无须调整。
3. 当前其它 adjustment 只允许 ETF 确认/削弱，且不得与 anchor 或彼此重复计证；基本面 v1 只作 observation-only，未来建立并认证 event-aligned price attribution basis 后才可重新申请基本面 adjustment。
4. `final` 必须机械等于 `anchor + Σ adjustments`，与报告中的计划时置信度一致并保持 0–100 整数。
5. 只有 final 落值后才与 60% 比较，再与总评分门槛共同计算 `threshold_eligible`；计划状态仍须独立通过 `plan_constructible`，不得反向改写 anchor 或 adjustment。
6. 报告必须同时展示两轴 anchor 依据、强制反证 adjustment、全部其它 adjustments、final、门槛比较与“非回测命中率”标签。

## 6. 运行边界

- 日常生产只使用当前 slot 的六源证据与 hash-bound 推理制品，不读取历史样本原稿。
- 风险数学与本置信度链严格分离：同账户 `invalidation_path` 必须在 reasoning 阶段用 exact `structural-noise-buffer-v2` 绑定其 support DAG 可达的本轮 TradingView observation、账户允许 timeframe、同周期截图、可机械定位的结构锚与图上 `noise_outer_boundary`。`status=certified` 时最终 stop 必须严格越过该边界并固定 `risk_budget_input_used=false`；证据不足只可密封 `status=insufficient` 并保持 `observe`。decision stop basis 中实际存在的 identity/anchor/distance 字段必须精确等于 reasoning owner，Gate 另读 status、visual evidence 与 boundary 验证；3%/8% 风险门不得反推或压缩，compiler 不得补算、猜测或重写。该 buffer 不是 anchor、adjustment 或门槛倒推的万能公式，也不存在固定最小点数或 ATR 公式。
- 历史报告数量只能在外置评估中检验方法稳定性；没有真实结局与同口径标签时，不得声称预测有效性成立。
