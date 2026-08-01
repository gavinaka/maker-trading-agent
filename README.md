# Trading-System

> 个人交易系统化引擎。
> 基于「交易系统底层逻辑全图谱」工程化实现。
> 10 Agent + 6 State + 9 Module，按宪法运转，按数据决策。

---

## ⚠️ 双层架构说明（先读 · 2026-06）

> **vNext 权威叠加**：vNext 业务与运行语义以 `governance/vnext_daily_workflow.md`、当前 run 密封的 methodology manifest 及其哈希制品为准。切换前 shadow 全链只使用本 run 六源证据，不读取 Notion、个人持仓、pretrade 或订单状态，也不发布 Notion；下述 legacy 实际运行说明不得反向覆盖 vNext。

> 本仓库分两层：
> - **参考设计层**：`agents/` + `state/` + `session_orchestrator`（链 A/B/C/D 自动机）—— **设计稿，当前未作为自动机运行**。
> - **实际运行层（每天真跑）**：`/daily-report` skill + `sessions/日报SOP.md` + `runtime/` 三时段原始证据增量／分析全量重算层 + 项目 `memory/` 用户拍板决策 + Notion REST + `outputs/*.py`（出 .docx + 推 Notion 🌅🌇🌙 子页 + verifier/lint 三门）。晚间独立审查已退役，由外置准确性评估替代。
>
> **真相源 = Notion 对应库**：持仓→（主/Maker）交易Check；门禁→开仓前状态门禁库；心力/心智→对应库；洁净进度→系统50笔库。**`state/` 6 个 JSON 为历史快照、不保证实时**。下文具体持仓/进度数字均以 Notion 为准。
>
> **机械整链硬门（2026-07-02）**：每份报告由持久 workflow lease 串起 begin→capture→prepare→analysis lock→commit→canonical DOCX→Word QA→publish→delivery，禁止跨时段重叠。逻辑版本变化只使分析失效；证据失败/缺失/过期/无效才允许完整重采。delivery 必须校验 render/QA/publish/context_log 的 SHA-256 与证据时序。

---

## 核心理念（来自宪法）

> "错过不是错误，乱做才是。"
> "这笔交易，是系统在执行，还是我在加速？"

---

## 系统目标

完成 **50 笔 100% 按系统执行的洁净 Maker 交易**（进度以 Notion『系统50笔』库为准；22% / 11 笔为 2026.4 末快照）

---

## 目录结构

```
Trading-System/
├── README.md                          ← 本文件（顶层导航）
│
├── constitution/                      ← 宪法层（不可常改）
│   ├── trading_constitution.md        ← 总宪法（图谱全图）
│   ├── execution_philosophy.md        ← 执行哲学
│   ├── maker_principles.md            ← Maker 策略原则
│   ├── review_principles.md           ← 复盘原则
│   ├── cannot_do_mapping.md           ← 当天 Maker "不能做"终局限制与计划兼容校验（与中线无关）
│   └── terminology.md                 ← 词汇标准库
│
├── agents/                            ← 10 个 Agent
│   ├── README.md                      ← Agents 索引（先读这个）
│   ├── session_orchestrator.md        ← 总调度
│   ├── emotional_agent.md             ← 情绪+5项门禁
│   ├── data_collection_agent.md       ← 数据采集（A/B/C 通道）
│   ├── news_agent.md                  ← BlockBeats 强制截图
│   ├── footprint_agent.md             ← 盘口 C01–C81 + 综合方法论
│   ├── scoring_agent.md               ← schema名义70+30；当前production有效60+30
│   ├── risk_agent.md                  ← 7 Gate 守门
│   ├── output_agent.md                ← 日报渲染
│   ├── review_agent.md                ← 五问复盘
│   └── penalty_agent.md               ← V001-V014 违规
│
├── data_sources/                      ← 数据采集
│   ├── required_sources.md            ← 6 个必抓数据源
│   ├── source_rules.md                ← 采集规则
│   ├── data_validation.md             ← 验证规则
│   ├── freshness_rules.md             ← 数据时效（≤4h/6h）
│   ├── blockbeats_rules.md            ← BlockBeats 专项
│   ├── fedwatch.md                    ← FedWatch 专项
│   ├── collectors/                    ← 6 个采集 SOP
│   │   ├── exocharts.md
│   │   ├── coinglass.md
│   │   ├── blockbeats.md
│   │   ├── fedwatch.md
│   │   ├── tradingview.md
│   │   └── farside_btc_etf.md
│   └── inbox/                         ← 每日采集投递盒
│       └── YYYY-MM-DD/
│           ├── _manifest.json         ← 采集清单
│           ├── exocharts_btc_*.{png,json}
│           ├── coinglass_*.{png,json}
│           ├── blockbeats_*.{png,txt}
│           ├── fedwatch.{png,json}
│           ├── farside_btc_etf.{png,json}
│           └── tradingview_btc_*.{png,json}  ← 日/4H/1H/15m 四档
│
├── scoring/                           ← 评分系统
│   ├── scoring_system.md              ← schema名义70+30；当前production有效60+30
│   ├── orderflow_scoring.md           ← 盘口当前0–60（70未来保留；详见 footprint_agent）
│   ├── chart_scoring.md               ← 盘面 30（5 项）
│   ├── score_thresholds.md            ← 分数阈值映射（开单双门槛）
│   ├── winrate_methodology.md         ← 胜率自估 rubric（70/75/80·开单门槛②）
│   └── scoring_examples.md            ← 4 个历史样本
│
├── risk/                              ← 风控
│   ├── risk_checklist.md              ← 7 项检核
│   ├── state_gate.md                  ← 5 项状态门禁
│   ├── leverage_rules.md              ← 杠杆（5x 固定）
│   ├── position_management.md         ← 仓位管理
│   ├── entry_exit_rules.md            ← 入出场规则
│   └── floating_defense.md            ← 浮盈防守 2-3 层
│
├── execution/                         ← 执行细则
│   ├── main_account.md                ← 主账户（Binance 中线 + 5 层防守）
│   ├── maker_execution.md             ← Maker（OKX 日内）
│   ├── entry_models.md                ← 入场模型（左/右侧）
│   ├── exit_models.md                 ← 出场模型（TP/SL + 防守）
│   ├── session_rules.md               ← 会话节奏（每日时段表）
│   └── taker_history.md               ← Taker 历史档案（已暂停）
│
├── governance/                        ← 治理
│   ├── workflow.md                    ← 11 Phase 工作流
│   ├── phase_01_data_collection.md    ← Phase 01 拆分细则
│   ├── consistency_rules.md           ← 10 条一致性规则
│   ├── emotional_tracking.md          ← 情绪治理（5 种状态）
│   ├── major_violations.md            ← 重大违纪库（V001-V008）
│   ├── penalty_system.md              ← 4 级处罚
│   ├── violation_cost_system.md       ← 违规成本 4 级
│   ├── token_policy.md                ← Token 预算
│   ├── violations/                    ← 违规记录（动态）
│   └── violation_costs/               ← 违规成本（动态）
│
├── runtime/                           ← 原始证据增量、前序判断隔离与全量分析运行层
│   ├── session_runner.py              ← prepare/commit 统一入口
│   ├── state_store.py                 ← 不可变状态链与原子提交
│   ├── delta_engine.py                ← 来源指纹与变化检测
│   ├── dependency_graph.py            ← 来源影响诊断 + 每时段完整分析清单
│   ├── context_pack.py                ← 无前序判断泄漏的 pre-analysis 包
│   ├── intent_router.py               ← 本工作区日报隔离意图分类
│   └── usage_logger.py                ← Token/耗时/重试/回退遥测
│
├── schemas/                           ← 数据 schema
│   ├── inbox_manifest_schema.json     ← _manifest.json 校验
│   ├── market_schema.json             ← 盘口/盘面统一结构
│   ├── trade_schema.json              ← 交易 Check 22 字段
│   ├── review_schema.json             ← 日/周/月报
│   └── violation_schema.json          ← 惩罚 13 + 成本 14 字段
│
├── templates/                         ← 模板（output_agent / review_agent 渲染源）
│   ├── report_structure.md            ← 总规范
│   ├── main_account_daily.md          ← 主账户日报（图谱十节）
│   ├── maker_morning.md               ← Maker 上午（图谱十一节）
│   ├── maker_evening.md               ← Maker 晚间
│   ├── review_daily.md                ← 日复盘（图谱十七节）
│   ├── weekly_review.md               ← 周报（图谱十九节）
│   └── monthly_review.md              ← 月报
│
├── reviews/                           ← 复盘结构定义 + 动态产出
│   ├── daily_review_structure.md      ← 日复盘结构
│   ├── weekly_review_structure.md     ← 周报结构
│   ├── monthly_review_structure.md    ← 月报结构
│   ├── clean_sample_rules.md          ← 洁净样本规则（图谱二十节）
│   ├── evolution_history.md           ← 系统演化史
│   ├── YYYY-MM-DD.md                  ← 日复盘（动态）
│   ├── YYYY-Www_weekly.md             ← 周报（动态）
│   └── YYYY-MM_monthly.md             ← 月报（动态）
│
├── state/                             ← 状态机（6 JSON）
│   ├── main_account_state.json        ← 主账户持仓 + 5 层防守
│   ├── maker_state.json               ← Maker + 洁净样本进度
│   ├── market_state.json              ← 市场结构 + C01–C81 客观组合
│   ├── score_state.json               ← 当前评分 + 历史参考
│   ├── session_state.json             ← 当日任务状态 + context_memory
│   └── risk_state.json                ← 风控状态 + alerts
│
├── outputs/                           ← 动态产出
│   └── YYYY-MM-DD_*.md / *.json       ← 由 agents 写入
│
├── logs/                              ← 日志（保留）
│
└── sessions/                          ← 会话归档（保留）
```

---

## 三账户体系（图谱一节）

```
┌──────────────┬────────────────────────┬──────────────────────────┐
│   主账户         │    Maker 账户             │    Taker 账户（已暂停）   │
├──────────────┼────────────────────────┼──────────────────────────┤
│ 低频中长线       │ 日内交易（波段/博弈）     │ 机会博弈（右侧/盘口）      │
│ 日/周/月级别     │ 高空 / 低多 / 反弹空      │ 每日≤1次，周≤3次          │
│ 自身中线大方向   │ 自身日内"不能做"(末位)  │ 2026.3.8 起合并至主账户   │
│ Binance（中线）  │ OKX（2026.5 起）         │ 历史上 OKX 执行           │
└──────────────┴────────────────────────┴──────────────────────────┘
```

---

## 每日运行节奏（图谱一节 + execution/session_rules.md）

| 时点 | 任务 | 责任链 |
|---|---|---|
| 00:00 | Daily Reset（归档昨日 session） | session_orchestrator |
| **09:00 - 11:00** | **早间盘前：主账户日报 + Maker 上午计划** | **链 A** |
| 11:00 | 早间评分点 | scoring_agent |
| **20:00 - 20:30** | **晚间：Maker 晚间新增计划** | **链 B** |
| 20:00 | 晚间评分点 | scoring_agent |
| **23:00** | **当日五问复盘截止** | **链 C** |
| 周日 22:00 | 周报触发 | review_agent.weekly |
| 月末 23:00 | 月报触发 | review_agent.monthly |

---

## 当前持仓快照（仅 legacy actual runtime；真相源：Notion 两库交易Check）

> ⚠️ 持仓为动态数据，**以 Notion（主）/（Maker）交易Check 最新行为准**，README 不再硬编码点位
> （避免陈旧：5/29-30 曾因沿用过期 short@79150 失真）。开场由 `/notion-positions` 校准，详见 `sessions/日报SOP.md` §2。
> vNext shadow 不读取、推断或复用这些持仓事实；vNext production 也只能在独立推理锁定后把它们用于执行连续性，不得回写计划、方向、评分、胜率、价格或风险。

- 主账户：中线持仓 + 防守层状态 → 见 `state/main_account_state.json`（同样以 Notion 为准）
- Maker：方向由同一 pivot 的 Coinglass 价格/CVD/OI 主链判定，资金费率只修饰、Exocharts 只确认/削弱/反驳；**当天 Maker『不能做』**只能在 Maker thesis、反证、失效和三类情景完成后作为最终限制输出，不得生成或翻转方向，且与主账户互不干扰。

---

## 评分系统（图谱三节）

```
评分schema名义容量 = 盘口70 + 盘面30 = 100；当前production有效值域 = 盘口0–60 + 盘面0–30，总分最高90
threshold_eligible = 总评分 ≥ 65 分　且　胜率 ≥ 60%（只表示通过数值门槛）
plan_constructible = Maker 逻辑闭环一致 + 当前 run TradingView 认证 entry_zone + 区间内 2–5 档合计 100% + 所有非空成交组合风险通过
plan_state=qualified = threshold_eligible 与 plan_constructible 同时为真；否则结构化 observe 是合法业务结果
执行概率 = ≥ 50%（软参考·非门槛·只定挂价可达性·不决定是否开仓）
评分频率 = 每日两次（11:00 + 20:00）
```

### 盘口评分（footprint_agent；当前production 0–60）
- 4 维：CVD / Price / OI / Funding
- **当前合法值域**：任意整数0–60；61–69非法，70是未来原生结构化真极端证明能力的保留值，当前不可用且不得通过配置单独启用
- **未来70边界**：只有另行实现并批准原生结构化证明验证器后，C19/C22/C56/C59且同一pivot的极端组合、效果背离、OI/价格语义、资金费率仅修饰且不单变量翻向、Exocharts明确确认、反证/失效闭环全部成立，才可能使用70
- **0–60 精细分**：按同 pivot 证据、底层语义、足迹印证、反证与失效闭环给任意整数；不得为模板或门槛补分

### 盘面 30 分（scoring_agent）
| 项 | 分 |
|---|---:|
| 支撑/压力区间接近度 | 10 |
| 多空流动性掠夺 | 10 |
| SMA20 突破/回踩 | 5 |
| 量价关系 | 3 |
| 斐波/趋势线接近度 | 2 |

---

## 风控（图谱四节）

### 7 项检核（开仓前必全 ✓）
1. 是否记录交易计划
2. 是否符合风险敞口要求
3. 是否完成技术面确认
4. 是否设置好止损止盈
5. 是否在规定交易时间内
6. 是否严格按入场信号执行
7. **单笔止损 ≤ 3%**（2026.3.5 起）

### 5 项状态门禁（任一触发禁止交易）
1. 情绪平静度
2. 节奏一致性
3. 结果依赖度
4. 连续止损 ≥ 3
5. 身体状态

---

## 6 个必抓数据源（图谱二节 · 缺一不可）

| 源 | URL | 记录方式 | 评分角色（2026-06-14 校准） |
|---|---|---|---|
| **Coinglass** | https://www.coinglass.com/tv/zh/Bybit_BTCUSDT | 文字 + 截图 | 🟥 **盘口当前0–60解读核心源**·四变量同屏(CVD/价格/OI/资金费率) |
| Exocharts | https://exocharts.com/web/ | 文字 + 截图 | 盘口**印证** + 更细颗粒度(footprint)参照·**非主源**·冲突以 Coinglass 为准 |
| **BlockBeats** | https://www.theblockbeats.info/newsflash | **必须截图（硬规则）** | 事件事实/Tier；价格兑现由BlockBeats+TradingView跨源claim负责 |
| CME FedWatch | https://www.cmegroup.com/.../cme-fedwatch-tool.html | 文字 + 截图 | 宏观/利率预期 |
| **Farside BTC ETF Flow** | https://farside.co.uk/btc/ | 文字 + 截图 | 最新完整日Total/flow；下游九格表只确认、削弱或中性，不单变量翻向 |
| **TradingView** | BTCUSDT·Binance | **截图（日/4H/1H/15m 四档齐）** | 🟥 **盘面(30)解读核心源**·日线/小时→技术评分+趋势+支撑压力·15m→Maker入场把关 |

---

## 快速跑通指引

### 前置条件
1. ✅ Chrome 浏览器 + Claude in Chrome 扩展已装
2. ✅ Trading-System 完整文件就位（本仓库）
3. ✅ 已登录：Exocharts / Coinglass

### 启动步骤

#### 步骤 1：检查 state 文件
```bash
ls Trading-System/state/
# 应该有 6 个 JSON 文件
```

#### 步骤 2：手动准备当日 inbox
```bash
mkdir -p Trading-System/data_sources/inbox/$(date +%Y-%m-%d)
```

#### 步骤 3：触发早间链 A
对话中说："session_orchestrator 跑早间链 A"

agent 会：
1. 读取并校验当天 Notion「开仓前状态门禁」（emotional_agent）
2. 自动采集六源（data_collection_agent）
3. 校验 BlockBeats 截图（news_agent）
4. 盘口 C01–C81 客观组合 + 综合方法论判定（footprint_agent）
5. 计算总评分（scoring_agent）
6. 7 Gate 预检（risk_agent）
7. 渲染主账户日报 + Maker 上午计划（output_agent）

#### 步骤 4：查看产出
```
outputs/<today>_main_account_daily.md
outputs/<today>_maker_morning.md
C:/Users/31702/Desktop/<today>_交易计划.txt
```

#### 步骤 5：实际交易（用户）
按计划执行。如开仓 → risk_agent.full 跑完整 7 Gate。

#### 步骤 6：晚间链 B（20:00）
同步骤 3，但只刷新盘口数据 + 生成 Maker 晚间新增。

#### 步骤 7：23:00 链 C 复盘
回答 5 问 → review_agent 写 reviews/<today>.md → penalty_agent 自动审计。

---

## 系统关键约束

| 约束 | 强度 | 来源 |
|---|---|---|
| 总评分 ≥ 65 且胜率 ≥ 60% 只令 `threshold_eligible=true`；还必须 `plan_constructible=true` 才能 `qualified` | 硬规则 | score_thresholds.md / maker_principles.md |
| 单笔止损 ≤ 3% | 硬规则 | risk_checklist.md |
| legacy 状态门禁只定执行资格；vNext shadow 禁读个人状态，vNext production 也不得用它改写计划 | 硬规则 | state_gate.md / vnext_daily_workflow.md |
| `cannot_do` 仅为 Maker 最终限制；不得依赖主账户、生成或翻转 Maker 方向 | 硬规则 | cannot_do_mapping.md |
| 当前production盘口只允许0–60；61–69非法，70为未来原生结构化证明保留值且不可由配置启用 | 硬规则 | orderflow_methodology.md / scoring_contract.json |
| Maker 必须使用当前 run TradingView 认证 `entry_zone`，区间内 2–5 档合计 100%；辅助源不得冒充区间 | 硬规则 | trading_constitution.md / score_thresholds.md |
| 仅当前 epoch、`shadow_complete` 且 `evidence_provenance.mode=fresh_full_recollection` 的真实全量重采样本可计 clean（由本 run 的 `capture_mode=full_base/full_recollection` 映射）；replay/test/fixture 永远只算 observation，且这不是第五道生产门 | 切换规则 | vnext_daily_workflow.md |
| BlockBeats 必须截图（非文字替代） | 硬规则 | source_rules.md |
| Maker 不隔夜 | 硬规则 | maker_execution.md |
| Maker 每日 ≤ 3 笔 | 硬规则 | maker_state.json |
| 浮盈防守必须层级递进（禁止回退） | 硬规则 | floating_defense.md |
| 每日 23:00 必复盘（含未开单） | 硬规则 | review_principles.md |
| 违规笔不计入洁净样本 | 硬规则 | clean_sample_rules.md |

---

## 资金状态（历史，图谱十九节）

| 日期 | 本金 | 现有 | 亏损 |
|---|---:|---:|---:|
| 2026-01 末 | $1200 | $750 | $350 |
| 2026-03-08 | $1200 | $500 | $700 |
| 2026-04 末 | $1200 | $490 | $710 |
| 2026-05-17 | $1200 | $520 | $680 |
| 2026-05-18 | $1200 | $540 | $660 |

---

## 与 Notion 的关系

* **Notion** = 用户主操作界面（交易计划 + 交易 Check + 周/月报 + 违规数据库）
* **Trading-System** = 系统化执行引擎（agents + state + manifest）
* **同步关系**：用户在 Notion 输入 → 本系统读取 → agents 处理 → 输出供 Notion 引用

---

## 重要文件优先级（理解系统）

如要快速理解系统，按以下顺序读：

1. **constitution/trading_constitution.md** — 总宪法（图谱完整版）
2. **agents/README.md** — Agents 总览
3. **agents/session_orchestrator.md** — 总调度逻辑
4. **execution/session_rules.md** — 每日节奏
5. **scoring/scoring_system.md** + **agents/footprint_agent.md** — 评分系统
6. **risk/risk_checklist.md** + **risk/state_gate.md** — 风控
7. **templates/main_account_daily.md** + **templates/maker_morning.md** — 输出格式
8. **reviews/clean_sample_rules.md** — 当前核心目标

---

## 版本

| 日期 | 版本 | 主要变更 |
|---|---|---|
| 2026-05-29 | 1.0 | 工程化首版（agents + state + manifest + templates 全套） |

---

## 核心原则（再次重申）

> **错过不是错误，乱做才是。**
> **系统一致性 > 单笔盈亏。**
> **过程评估 > 结果导向。**
> **正确性 > 完整性，宁缺毋滥。**

---

## License

私人系统，不对外开放。
