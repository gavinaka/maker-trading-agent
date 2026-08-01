# 推理深度纪律 —— 出稿前自读清单（思考层 + 局部机械门）

> **状态：vNext 推理纪律层。** 本文件不改变模板、评分、胜率、块结构或配色。
> 文字命中本清单不等于通过。当前六源观察、视觉判断替代解释、承重 claim、支持/反证引用、评分来源（schema 名义70/30；当前 production 有效盘口0–60+盘面0–30）、计划时置信度和残余不确定性必须先进入当前引擎的 hash-bound 结构化推理制品，并完成独立的第二遍对抗性反证。Markdown 只负责可读表达，不能替代结构化合同。
> 当前引擎还必须机械验证胜率 rubric 全链、总分/盘口/盘面合成链、方向主判与反证链、承重点证据颗粒度。其余内容仍是动笔前自读纪律。
>
> **核心前提（先对齐）**：要的不是"输出更长"，而是"推理更深"。
> 正文必须精炼干净、细节全进③后附（见 `fundamentals-brief-core-priority`）。
> 所以"极致颗粒度/逻辑深度"只能活在 **① 内部思考层 + ② ③后附的推导留痕**，
> **绝不允许让正文膨胀**。深度 ≠ 字数。

---

## 机械硬门边界

严格推理留痕只检查因果链，不检查灌水长度：

1. 置信度顺序固定：`Coinglass+Exocharts 盘口轴 + TradingView 结构轴 → anchor → adjustments[0] 覆盖全部 current_basis 的当前 Maker 最强反证负调 → 独立 ETF/基本面兑现调节 → final → 比 60`；不得跳步、后移或重复。`anchor_rationale` 只用 authority canonical 文本；市场事实只认 typed claim/source。
2. 总分/盘口/盘面必须有 `证据读数 → 分项落值 → 合成总分`。
3. 方向必须有 `主判 → 最强反证 → 失效/情景路径`。
4. ③后附至少覆盖 pivot/结构锚、CVD、SMA20、用户手绘成交量分布区域（或明确证据不足边界）四类承重点中的三类。
5. FOMC 利率预期插槽先认证 provider 再读概率：CME 有效时只认真实 UI；只有 sealed
   closed-code 技术故障才可进入 Kalshi Plan C。Plan C 必须保留 `other_unlisted`、
   `>25bp` 尾桶、同口径 current/1d/1w/30d 与 non-equivalent/observation-only 边界。
   这些是证据真实性条件，不是方向、评分或 conviction adjustment。

### pre-report 顺序门

严格留痕不允许变成报告生成后的补丁。正式报告编译前，必须先密封当前 slot 的六源 observation、独立推理、对抗性反证与决策制品：

- 独立推理制品必须先于正式报告。
- 对抗性反证与决策锁定必须先于正式报告。
- 后补理由、后补 rubric、后补任何推理均禁止。
- Word、PDF 与逐页 PNG 必须依赖已锁定且 hash-bound 的报告制品，不能直接消费未锁定文本；vNext 切换前不得发布 Notion。Word QA 只有 exact `word-qa-vnext-v2` 可通过，且 passed checklist 必须使用 `review_checklist_version=word-qa-semantic-review-v1`，exact 键集合为 `all_pages_inspected`、`no_clipping_overlap_or_missing_glyphs`、`no_orphan_semantic_headings`、`critical_price_blocks_not_split`、`six_source_sections_readable`、`arabic_price_digits_preserved`，并全部为 boolean `true`。

---

## 一、把算力压在"承重数据"上，不均摊（聚焦关键数据极致）

"聚焦关键数据"的真义 = 识别**哪几个数据点一旦读错就翻转决策**，90% 推理算力压在那几个点，其余据实快速落值。
本系统的承重点固定就这四个，每份用极致颗粒度优先解决它们：

1. **价格摆动 pivot 的选取**（下跌腿 vs 误当新上涨腿）—— 两次复犯的根源。
   先只回答一件事：**主导趋势线破没破**？未破 → 锚仍留在启动腿的摆动高/低，腿内小反抽是噪声不重置锚。
   权威：`orderflow_methodology.md` §一 · `orderflow-price-anchor-reading`。
2. **CVD 净斜率的符号**（横盘 vs 下降 · 被套的是哪一方）。
   权威：`orderflow_methodology.md` §二 · `orderflow-divergence-synthesis`。
3. **SMA20/均线的当下实测值**（每份从当时那批图重测、禁沿用早间/前序）。
   权威：`sma-values-remeasure-each-report`。
4. **置信度 rubric 锚**：按①固定顺序；anchor 由 Coinglass+Exocharts 盘口轴与 TradingView 结构轴联合形成。
   权威：`winrate_methodology.md` · `winrate-anchoring-bias`。

> 这四点值得每个写满"颗粒度极致"的内部推导；其余分项据实快速落值即可，不必平均用力。

> **执行**：vNext sealed effort exact `xhigh`，集中上述四点；其它据实。实际 `max|ultra` 只证明 `>=xhigh`，不改请求且非正确性依赖。
> - 衡量标尺修正：**context 占用 ≠ 推理深度**（那多是静态载入的记忆/方法论/历史）；真深度 = **承重点上花的思考 token + 对同一证据的独立 pass 次数**。
> - 🟥 **加深的反效果区**：token 越多 ≠ 越准。加深必须被夹住——**只压承重点（非均摊）** + 产出仍受三道机械门与精炼正文铁律约束（守 `judgment-synthesis-not-extreme`：禁臆造精度/禁走极端）。**否则更深 = 更漂移。**
> - 本指令仍是只读纪律：不接门、不改模板/评分/框架。（已评估但未采纳的更大增益项 = 每源派独立子代理、N轮冷读+多空对抗辩论；如日后要更深可再开。）

---

## 二、锁死推理顺序，从源头杜绝锚定/逆推

深度最容易被"逆推结论"污染。每份在思考层**显式走一遍**：

> 读六源证据 → 各分项读**绝对真实值** → 总分/胜率**自然涌现** → **之后**才比 65 / 60 门槛 → 决策自然落出。

打分那一刻，门槛与结论应在视野之外。这不是新规则，是把已有底层逻辑（`scores-are-absolute-not-anchored`）在思考时机械执行一遍。
**自检**：这个分是从证据读出来的真实值，还是盯着某个数倒推凑的？

---

## 三、对每个关键判断做"对抗性反证"（治走极端的元问题）

治 Claude 易走极端（`judgment-synthesis-not-extreme`）最有效的深度工具：
**每定一个方向，先显式构造被套那一方的最强反驳，再权衡谁赢、为什么。**

- 把"我看跌" 升级成 → "看跌理由 X；但看涨的最强反证是 Y；Y 为何不足以翻向"。
- 反证不成立才落向；事实（CVD 主动买卖）> 推测（隐性派发）。
- **此步只在思考层 + ③后附做**，正文只给结论本质。

---

## 四、对模糊数据做"竞争读法并列"，不直接拍单解

遇到一数多解的点（典型：CVD 横盘 = 隐性派发 / 吸收 / 噪声），
**不要直接拍一个解释**，而是在③后附把 2–3 种合法读法并列，标注哪个胜、依据是什么。
把"幻觉式单解"换成"加权式判读"，深度与留痕一举两得。

---

## 五、显式写出每条关键结论的推导链（写得出 = 真想清楚了）

计划时置信度已要求写链（`两轴 anchor → adjustments[0]=当前 Maker 最强反证强制负 adjustment → 独立 ETF/基本面 adjustments → final → 比 60`）。其中 anchor 只允许 `shared|maker` 的 `orderflow_interpretation` 与 `chart_interpretation|invalidation_path` 两轴 claim；主账户、thesis/regime/counter/cannot-do、基本面/ETF claim 禁止充当 anchor。`anchor_rationale` 精确等于 authority 的 `anchor_policy.canonical_rationale`，不得承载市场事实自由文本；compiler 只能结合机械验证的 claim/source 投影。`adjustments[0].reason_code` 必须为 `maker_counter_current`，按顺序覆盖当前最强反证全部 `current_basis` clause，`counter_resolution` 固定 `disposition=adjusted`、`resolution_claim_ids=[]`，不存在 `resolved_no_adjustment`；FedWatch、footprint/orderflow/chart/structure 和清算地图不得作为额外 adjustment。把这条**留痕纪律扩展到方向与总分**：

> 方向 = 主体趋势证据(CVD斜率 + 价 + OI)定向 → 风险变量(费率等)只调级不翻向 → 落向。

链子写进③后附即可，不进入精炼正文。**写不出链 = 还没到深度，必须在锁定前重新推理；锁定后不得补写。**

---

## 六、跨源三角验证当深度抓手

每个承重结论要求 **≥2 个独立源印证**；**源冲突时，冲突本身就是信号** —— 去推理"为什么冲突"，
而不是挑顺的那个源。这天然防"各维各取局部极值"。
（与 `data_sources/required_sources.md` 的六源齐备合同互补：齐备是前置，三角验证是用法。）
同一逻辑插槽内的 CME primary 与 Kalshi Plan C 不构成两个可并列挑选的独立源：
状态机每轮只能选择一个 provider，且 CME 有效时 Kalshi 不得被调用或进入推理。

---

## 七、颗粒度数据源映射（推理注意力权重 盘口50 / 盘面30 / 基本面20）

> 🟥 **先分清两套权重，禁混淆**：
> - **评分 schema 名义容量（产出层）** = 盘口70 + 盘面30 = 100；当前 production 有效值域 = 盘口0–60 + 盘面0–30，总分最高90。盘口61–69非法，70为未来原生结构化证明保留值且当前不可用。**基本面不进总分公式**（`scoring/scoring_contract.json`）。
> - **推理注意力权重（过程层·本节）** = 盘口50% / 盘面30% / 基本面20%，= **深度推理的颗粒度算力如何分配**。
> - 两套并存不冲突。基本面虽不计分，仍占 20% 推理，因为它是**背景门控**（决定盘口/盘面读法是否成立），不是计分项。
> - 改本节 = 调推理算力分配，**零触碰评分 schema 与当前有效值域**。

### 盘口 · 注意力 50% ← ②Coinglass(主体四维) + ③Exocharts(足迹·只调强度不翻向)
颗粒度数据(价格锚点法/1H摆动pivot单锚) → 产出：
- CVD：方向 + **净斜率**(pivot→现价)〔承重①〕
- 价格：方向 + 速度(缓慢=虚弱／急速放量=真实)
- OI：增/减/横(燃料装填/撤离)
- 费率：正/负/近0 + 斜率(反指·越极端反转概率越高)
- 足迹：吸收/失衡/POC(只调强度不翻向)
- **→ 81组合(3⁴)=当前 production 盘口评分0–60 + 背离合成=signal_type方向(读被套那一方)；70仅为未来保留能力**
- 🟥 极致承重点：pivot腿选(趋势线破否) + CVD净斜率符号。权威 `orderflow_methodology.md`。

### 盘面 · 注意力 30% ← ⑥TradingView 四档(1D/4H/1H/15m·周线仅周一)
颗粒度数据 → 产出：
- 日线：道氏HH-HL=大方向 + SMA20/通道/结构形态
- 4H+1H综合：结构细化/入场上下文
- 15m：日内支撑压力（手绘线/可读用户手绘成交量分布区域）·仅Maker·不进趋势分
- 5项：支撑压力接近度0-10 / 多空流动性掠夺0-10 / SMA20交互0-5 / 量价0-3 / 斐波趋势线0-2
- **→ 5项合计=盘面评分0–30(机会质量·与方向无关) + 道氏=结构性趋势(短线/中短线) + 15m=日内支撑压力区间**
- **流动性猎杀**(`chart_methodology.md §九`)：各周期高/低=候选猎杀位 → 可读的用户手绘成交量分布区间读猎杀**概率**（主判）→ Coinglass 清算热力图**辅助印证**（周末3天/周中48H+24H·阈值0.85）；手绘区域不足时不落概率位置、该分项0分，清算图不得补位或翻向。
- 🟥 极致承重点：SMA20数值每份重测 + **流动性猎杀概率(主判=成交量结构·热力图仅辅助·禁单凭插针预判反转)**。权威 `chart_methodology.md`。

### 基本面 · 注意力 20% ← ①BlockBeats(快讯) + ④FedWatch(宏观事件概率) + ⑤Farside BTC ETF Flow(现货侧确认)
颗粒度数据 → 产出：
- BlockBeats：`observation.metrics`只承载 `tier`、`event_window_hours`、`selected_event_count`、`selected_event_sha256` 的事件事实与层级；价格兑现只由BlockBeats+TradingView共同支持的 `fundamental_price_realization` 跨源claim产生
- FedWatch：降/加息概率 → 宏观事件窗口
- Farside：`observation.metrics`只承载 `latest_complete_date`、`latest_total_usd_m`、`flow_direction`；价格×流向关系由下游typed claim按3×3表确定：上涨+流入/下跌+流出=`confirm`，上涨+流出/下跌+流入=`weaken`，其余5格均=`neutral`。只作现货侧确认/削弱/中性，不计分、不可单变量翻向
- **→ 基本面定性(进正文括号·核心本质·不进评分公式) + 事件门控(重大事件是否改变背景) + 跨源价格兑现 claim + ETF 现货侧 confirm/weaken/neutral**
- 🟥 极致承重点：是否存在"改变背景"的重大事件；若无 → 20%注意力≠喧宾夺主翻向(守 `judgment-synthesis-not-extreme`：基本面只调背景、不单变量翻向)。

> **下游合成（不是额外数据源）**：六源按各自边界读完 → 当前盘口0–60+盘面0–30自然涌现总分 → 胜率按方法论独立估值 → **之后**才比65/60(守 `scores-are-absolute-not-anchored` / `winrate-anchoring-bias`)。

---

## 收口

> **深度 = 思考层把承重数据嚼到极致 + ③后附留全推导链；正文保持精炼。**
> 这样既满足"颗粒度 / 逻辑 / 聚焦极致"，又**零触碰框架**、零违反 `fundamentals-brief-core-priority` 与三道机械门（`stability-contract`）。
> 上述方法说明用于理解；下方生产级语义门负责机械执行，不能再只靠主动套用。

---

## 生产级语义执行合同

以下内容必须由 `scoring_contract.json.gold_methodology` 与当前推理制品结构化、hash 绑定：

1. 独立压缩结论：阶段、主导腿、主要证据、最强反证、最终动作。
2. 同一 1H pivot 三问：腿是否选对、回调是否错误重置锚、价格/CVD/OI/费率是否同锚。
3. Exocharts OHLC/POC/Delta/CVD/Volume 对 Coinglass 的确认、削弱或冲突。
4. 1D/4H/1H/15m 的价格、SMA20、结构与状态转换。
5. 用户手绘成交量分布区域主判位置/概率、猎杀位的周期/用途、清算地图只作辅助；若手绘区域不可读，则必须结构化写 `insufficient`、空区域与不推断边界。
6. ETF 价格×流向 typed claim 只按确定性3×3表输出 `confirm` / `weaken` / `neutral`，不污染当前盘口0–60/盘面0–30。
7. 主账户与 Maker 优先级分离，允许冲突，不强制同向叙事。
8. Contract assigns all 54 methodology leaves exactly once: server deterministic; model business (8); key=`selected_event_sha256`. Unclassified=preflight hard stop. Runtime may bind same-hash realization, never alter/infer/reorder key.
9. `scenario-ownership-v1`：Main/Maker 各有 base/counter/invalidation，只提交 exact row，owner／methodology `claim_id`／closed `action` 对齐。`account-trigger-logic-v5`：只用可达 typed field；`any` 每条独立同向且当前均 false；`all` 同极性、同 field target 交集非空且当前至少一条 false；`one_of_at_trigger` 单极性；invalidation=`all`。唯一 Coinglass/Exocharts `all` 对：reference target=current → `equals_at_trigger`，否则 `becomes`；relation=`equals_at_trigger`。runtime 只投影这两个 operator；绑定／真值／方向无效即失败。compiler 由 typed owner/code 投影附录 D；lifecycle 只认 Decision/continuity。
10. “不能做”在全文推理后回填且严格 output-only；任何 observation、claim、反证、失效、方法论情景或账户情景均不得引用它。
11. 置信度执行 claim/typed-owner 去重：anchor 与 adjustment 不复用 claim；reason code、单项 claim IDs 唯一；跨 adjustment 的 claim IDs/owner signatures 互斥。compiler 仅投影 `reason_code+delta+claim_ids+typed_values`，`label/rationale` 只供 Gate 审计。先复算 `final=anchor+Σadjustments`，再比较门槛和形成计划状态。
12. 两账户 `invalidation_path` 在 reasoning 密封 exact `structural-noise-buffer-v2`。`certified` 仅用于 `long|short`，绑定本轮可达 TradingView、允许 timeframe、同周期截图、结构锚/噪声外边界；stop 严格越界且 `risk_budget_input_used=false`。图像不足=`visual_noise_envelope_not_readable`，Main `neutral`/Maker `observe`=`not_applicable_non_directional_thesis`；均为 `insufficient` 且 anchor/boundary/distance 为空。decision identity/anchor/distance 等于 reasoning owner；Gate 另核 status/截图/boundary。3%/8% 与 R:R 仅后验；禁止 compiler 或固定点数/ATR/风险门槛倒推。

承重结论按 typed claim 专属 ancestry 计来源，不用全局“双源最低数”。`strongest_counterevidence` 至少一个真实 counter；每 clause 相对同账户 thesis 为 counter，禁止 support/neutral 填充。正文与③后附须通过确定性投影，证明 Word/PDF/逐页 PNG 无语义丢失。
历史 AI 底稿只在维护期一次性学习 2026-06-22 至 2026-06-26 的逻辑链与交易方法论，
日常生产不得重新读取；手工报告只在维护期校准用户意图与字段语义。
