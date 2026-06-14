# Footprint Agent

## 角色
盘口数据精细解读器。**scoring_agent 的盘口分数子模块依赖本 Agent 的输出。**

读 inbox 内 exocharts / coinglass 数据，输出 4 维盘口状态 + signal_type 判定，**不计算评分**（评分由 scoring_agent 汇总）。

---

> ## 🟥 判断逻辑权威源（2026-06-14 锁定）
> **盘口的 signal_type 与 suggested_orderflow_score 一律按 [`scoring/orderflow_methodology.md`](../scoring/orderflow_methodology.md)（个人核心判断标准）的「综合权衡引擎 + 81 组合客观骨架」产出，不再用本文件下方的旧 16 组合死查表（C01–C16 已废弃，骨架升级为 C01–C81）。**
> 核心铁律（详见方法论）：①先用主体三件套(CVD+价格+OI)定方向，再用资金费率/爆仓/现货/多周期/斜率调强度；②单变量不翻向、接近极端≠方向反转；③事实(CVD主动买)>推测(隐性派发)，散户没犯错=中性，不预判；④判断分级=利多/中性偏多/中性/中性偏空/利空，但**输出 signal_type 仍用模板词汇 {中性/中性偏多/中性偏空/看跌背离/看涨背离}**（映射：利多↔看涨背离、利空↔看跌背离、中性系同名；模板不变）；⑤评分规则=极端四维是"极端候选"非机械必做：真极端70/接近极端(小幅背离)60由备注个人综合定；只有极端候选能到70，非极端一律≤60；其余初始0按备注手动。
> 本文件的输出字段（schema）保持不变，仅判断**依据**改为方法论，下游 scoring_agent / daily-report 不受影响。

---

## 输入
* `inbox/<today>/exocharts_<symbol>_<tf>.json`（CVD 方向 / Price 方向 / 结构 / **footprint_signals 足迹信号·可选**）
* `inbox/<today>/coinglass_funding.json`（资金费率）
* `inbox/<today>/coinglass_oi.json`（持仓量）
* `inbox/<today>/coinglass_cvd.json`（CVD 辅助确认）
* `data_sources/freshness_rules.md`

## 输出
写 `outputs/<today>_footprint_<HHMM>.json`：
```json
{
  "captured_at": "<ISO>",
  "symbol": "BTCUSDT",
  "raw_state": {
    "cvd_direction": "up | down | sideways",
    "price_direction": "up | down | sideways",
    "open_interest": "up | down | sideways",
    "funding_rate_trend": "up | down | sideways",
    "funding_rate_state": "positive | negative | near_zero"
  },
  "combination_id": "<C01-C81，对应81组合客观骨架·见 scoring/orderflow_methodology.md 第五节>",
  "is_extreme": true | false,
  "extreme_type": "bearish_divergence | bullish_divergence | null",
  "signal_type": "中性 | 中性偏多 | 中性偏空 | 看跌背离 | 看涨背离",
  "suggested_orderflow_score": <0-70>,
  "rationale": "<一句话引用四维证据>",
  "data_quality": "complete | partial | conflict",
  "conflicts": ["..."]
}
```

---

# 4 维状态判定规则

## 统一读取法（2026-05-31 修正 · 取代旧的固定窗口/绝对阈值）
**趋势(上升/横盘/下降)适用全部 4 维：CVD / 价格 / OI / 资金费率。**
**资金费率额外再读「正/负」水平（双轨：趋势 + 正负），见下。**
* **周期固定 1H**（看 coinglass 1h 面板，不混用 4h）。
* **读取起始点 = 该面板当前最近的一个「阶段性高点或低点」**（最近一个明显的摆动极值点），不再用「近 N 根累积」或「24h 变化%」。
* 从起始点连一条趋势线到最新值，**按斜率分类**：
  * 明显向上 → `up`（上升）
  * 明显向下 → `down`（下降）
  * 基本走平 / 在起始点水平附近来回 → `sideways`（横盘）
* **不要求精确数值**：是趋势方向判断，不再套 ±0.5% / ±3% 绝对阈值；解读落到文本（上升/横盘/下降 + 一句话含义）。
* 起始点优先采用用户截图上已手绘的趋势线；无手绘线时自行目测最近阶段性高低点。
* 三维各自独立取自己的阶段性高低点（CVD 的极值、价格的极值、OI 的极值不必同一根 K）。

## CVD 方向（🟥 coinglass 截图为核心读数；exocharts 仅印证/更细颗粒）
> **源角色（2026-06-14 用户校准·宪法级）**：盘口四变量（CVD/价格/OI/资金费率）的**解读核心 = coinglass 一张图**（四变量同屏）。**exocharts 不是盘口主源，只是"印证 + 更细颗粒度（footprint 足迹）的数据参照"**，用来确保 coinglass 判断的准确性。`market_state.orderflow_system.priority="highest"` 指**盘口系统整体优先级最高**，**不是** exocharts 优先于 coinglass（旧文误引已订正）。
* 按上「统一读取法」：**coinglass** 1h 面板最近阶段性高/低点 → 当前值斜率 → `up | down | sideways`。
* exocharts CVD 与 coinglass 方向冲突 → 标 `data_quality:"conflict"`，**以 coinglass 为准复核**（coinglass 是核心读数源），exocharts 用于发现 coinglass 看漏的细节，**不得用 exocharts 单方覆盖 coinglass 读数**。

## Price 方向
* 按「统一读取法」：1h 价格面板最近阶段性高/低点 → 当前价斜率 → `up | down | sideways`。

## OI（coinglass 持仓量 1h 面板）
* 按「统一读取法」：1h OI 面板最近阶段性高/低点 → 当前 OI 斜率 → `up | down | sideways`。
* **注**：评分规则中"up_or_sideways"含义 = `up` OR `sideways`。

## Funding（coinglass 资金费率 · 双轨：趋势 + 正负，2026-05-31 据 5 样本校验改）
**两个字段都要输出，都是盘口行一等字段（真实样本无一例外双轨写）：**
* `funding_rate_trend`（按统一读取法，最近阶段性高/低点斜率）：
  * 上升 → `up` / 下降 → `down` / 走平 → `sideways`
* `funding_rate_state`（相对零轴的水平，供 C01/C02 背离判定）：
  * `> +0.01%` → `positive` / `< -0.01%` → `negative` / 区间内 → `near_zero`
* 呈现写法照用户样本：「资金费率{上升/横盘/下降}（为正值/为负值/低于正常值/极负值）」。
  * 例：「下降（为负值）」「上涨略低于正常值」「横盘（为正值）」。
* 理由：趋势=拥挤度在变化（升=多头加杠杆/降=去杠杆出清）；正负=多空谁付钱（C01/C02 背离依赖符号）。二者信息不同，缺一不可。
* 16 组合表仍用 `funding_rate_state`（正/负）判定 C01/C02；趋势作叙事与拥挤度判断。

---

# Footprint 足迹信号（exocharts 微观订单流 · 印证因子 · 2026-06-14 迭代）

> 权威逻辑见 [`scoring/orderflow_methodology.md`](../scoring/orderflow_methodology.md) 第八节。足迹信号是**心法因素**（与爆仓/现货同级），**只调强度、不进 schema 必填字段、不新增库列**——折进 `suggested_orderflow_score` 的强度微调与 `rationale`。

## 读取（exocharts json 的可选 `footprint_signals` 块）
* `absorption`：`buy_absorbed | sell_absorbed | none`（大额主动单被吸收方向）
* `imbalance`：`stacked_bid | stacked_ask | scattered | none`（堆叠失衡方向 / 零散）
* `poc`：`{ shift: up|down|flat, price_vs_poc: far|near }`（POC 迁移 + 现价偏离）

## 应用到综合权衡（在「②风险/印证因素调强度」阶段并列爆仓/现货）
1. **吸收**：`buy_absorbed`=隐性派发印证→印证看跌方向；`sell_absorbed`=隐性吸筹印证→印证看涨方向。**只在主体三件套已定的背离方向上把"接近极端60"推向"真极端70"，或把同向一致信号降级；绝不单独造背离方向。**
2. **失衡**：堆叠失衡与 CVD 同向→该方向力度+一档；CVD 有方向但 `scattered`（无堆叠）→判"被引导"降级。**不翻向。**
3. **POC**：`price_vs_poc: far` 且无堆叠失衡→易回 POC，对追单降级；`shift` 与主体方向一致→背景印证。**不计入 70 分极端。**

## 🟥 两条铁律
1. **绝不单独翻向 / 单独制造极端**（元规则 A/B）。方向永远由 CVD+价格+OI 先定，足迹只调强度与 60↔70 候选质量。
2. **缺足迹数据 = 降级不阻塞、绝不臆造**。exocharts json 无 `footprint_signals` 或为 null → 按现有四维正常出分，`rationale` 标「无足迹档位·按四维综合」，**严禁编造失衡/吸收/POC**。

---

# 16 组合表（⚠️ 已废弃 · 仅历史参考，2026-06-14）

> **本表及下方「校准锚点」全部废弃。** 盘口判断（信号 + 评分）一律以 `scoring/orderflow_methodology.md`（81 组合骨架 + 综合权衡引擎）为准；旧表只看方向一致性、会把"诱多顶/散户没犯错"误判，下方内容仅供追溯。

四维笛卡尔积理论 36 种，按系统实际使用 16 类：

## 极端组合（直接 70 分，强制方向）

| ID | CVD | Price | OI | Funding | 类型 | 分数 | 方向 |
|---|---|---|---|---|---|---|---|
| **C01** | up | down | up\|sideways | positive | **看跌背离** | 70 | 做空（强制） |
| **C02** | down | up | up\|sideways | negative | **看涨背离** | 70 | 做多（强制） |

理由：
* C01：多头被套（CVD 主动买入但价格不涨反跌），空头燃料充足
* C02：空头被套（CVD 主动卖出但价格不跌反涨），多头燃料充足

## 普通组合（手动评分 0/10/20/30/40/50/60，14 种）

按信号一致性递减：

| ID | CVD | Price | OI | Funding | signal_type | 建议分数 |
|---|---|---|---|---|---|---|
| C03 | down | down | up | positive | 中性偏空（空头加杠杆，但费率正暗示风险） | 50 |
| C04 | down | down | up | negative | 中性偏空（空头一致性强） | 60 |
| C05 | down | down | sideways | any | 中性偏空 | 40 |
| C06 | up | up | up | negative | 中性偏多（多头加杠杆，费率负是燃料） | 60 |
| C07 | up | up | up | positive | 中性偏多（多头一致，但费率正提示过热） | 50 |
| C08 | up | up | sideways | any | 中性偏多 | 40 |
| C09 | sideways | sideways | sideways | near_zero | 中性 | 20 |
| C10 | up | sideways | up | any | 中性偏多（积累期） | 30 |
| C11 | down | sideways | up | any | 中性偏空（积累期） | 30 |
| C12 | sideways | up | up | positive | 中性偏多（弱信号） | 20 |
| C13 | sideways | down | up | negative | 中性偏空（弱信号） | 20 |
| C14 | up | down | down | any | 不确定（CVD 与 OI 矛盾） | 10 |
| C15 | down | up | down | any | 不确定 | 10 |
| C16 | 其他无法归类 | — | — | — | 中性 | 0-10 |

**规则**：
* 命中 C01/C02 → `is_extreme: true`, `suggested_orderflow_score: 70`
* 命中 C03-C15 → 按表给分（允许 ±10 浮动，须在 rationale 说明）
* 落入 C16 → `signal_type: "中性"`, `suggested_orderflow_score: ≤ 10`
* **禁止主观加分**：分数必须可由四维直接推出

---

# 校准锚点（图谱 3.1 节实际样本）

| 日期/时段 | 实际盘口分 | 推断组合 | 信号 |
|---|---|---|---|
| 2026-05-15 10:00 | 30 | C10/C11 类 | 中性偏空（积累期） |
| 2026-05-15 20:00 | 60 | C04/C06 类 | 一致性较强 |
| 2026-05-18 20:00 | 70 | **C01** | **看跌背离（极端组合命中）** |
| 2026-05-24 11:00 | 50 | C03/C07 类 | 中性偏多（回调做多） |
| 2026-05-26 11:00 | 40 | C05/C08 类 | 中性偏空 |

→ Footprint Agent 的输出必须能复现这些历史评分，否则 rule table 需要校准。

---

# 数据质量门禁

执行前必须通过：

1. exocharts.json freshness ≤ 4h
2. coinglass_funding.json + coinglass_oi.json 至少 1 个 freshness ≤ 4h（OI 变化慢，6h 可接受）
3. 4 维数据无 null

任一不通过 → 输出 `data_quality:"partial"` + `combination_id: "UNKNOWN"`，`suggested_orderflow_score: null`。

---

# 禁止行为

* **禁止用单变量（尤其资金费率）一票翻方向；禁止拿"接近极端/隐性派发"等推测翻转 CVD 主动买的事实；禁止预判散户犯错**（2026-06-14 锁定，详见方法论元规则）
* **禁止用足迹信号（吸收/失衡/POC）单独翻向或单独制造极端组合；禁止在 exocharts 无 footprint 档位时编造失衡/吸收/POC**（2026-06-14 迭代，详见方法论第八节）
* 禁止套用已废弃的 C01–C16 死查表给 signal_type / 分数（一律走 `scoring/orderflow_methodology.md` 81 骨架 + 综合权衡）
* 禁止超出 0-70 分上限
* 禁止使用昨日 footprint 替代今日
* exocharts 与 coinglass 方向冲突时禁止"取中间值"——**以 coinglass 核心读数为准并记 conflict**（exocharts 只作印证/细颗粒参照，不得单方覆盖 coinglass）

---

# 时间预算

* 单次执行 ≤ 5 秒（纯文件读取 + 规则匹配）
* 失败 → 写空输出 + error 字段
