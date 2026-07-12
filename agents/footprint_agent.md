# Footprint Agent

## 角色
盘口数据精细解读器。**scoring_agent 的盘口分数子模块依赖本 Agent 的输出。**

读 inbox 内 exocharts / coinglass 数据，输出 4 维盘口状态 + signal_type 判定，**不计算评分**（评分由 scoring_agent 汇总）。

---

> ## 🟥 判断逻辑权威源（2026-06-14 锁定）
> **盘口的 signal_type 与 suggested_orderflow_score 一律按 [`scoring/orderflow_methodology.md`](../scoring/orderflow_methodology.md)（个人核心判断标准）的「综合权衡引擎 + 81 组合客观骨架」产出。旧 C01–C16 死查表已从本文件删除，骨架以 C01–C81 为唯一口径。**
> 核心铁律（详见方法论）：①先用主体三件套(CVD+价格+OI)定方向，再用资金费率/爆仓/现货/多周期/斜率调强度；②单变量不翻向、接近极端≠方向反转；③事实(CVD主动买)>推测(隐性派发)，散户没犯错=中性，不预判；④判断分级=利多/中性偏多/中性/中性偏空/利空，但**输出 signal_type 仍用模板词汇 {中性/中性偏多/中性偏空/看跌背离/看涨背离}**（映射：利多↔看涨背离、利空↔看跌背离、中性系同名；模板不变）；⑤评分规则=极端四维是"极端候选"非机械必做：真极端70/接近极端(小幅背离)60由备注个人综合定；只有极端候选能到70，非极端一律≤60；其余初始0按备注手动。
> 本文件的输出字段（schema）保持不变，仅判断**依据**改为方法论，下游 scoring_agent / daily-report 不受影响。
> 🟥 **2026-06-20 单一权威收敛**：下方 §统一读取法 / §四维合成背离引擎 = `orderflow_methodology.md` 的**镜像副本（非权威）**，仅供本文件 schema 语境参考；与方法论冲突时**一律以 `orderflow_methodology.md` 为准**。daily-report 运行时读法**直指** `orderflow_methodology.md §一/§二`、**不再二跳本文件**（消除同一读法多副本漂移·6/17·6/19 锚错腿教训）。

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

## 统一读取法（🟥 2026-06-17 重大订正 · 价格锚点法 · 取代旧的「各维独立取极值」）
**趋势(上升/横盘/下降)适用全部 4 维：CVD / 价格 / OI / 资金费率。**
**资金费率额外再读「正/负」水平（双轨：趋势 + 正负），见下。**
* **周期固定 1H**（看 coinglass 1h 面板，不混用 4h）。

### 🟥 核心铁律：以 1H 价格的摆动高/低点为「唯一锚点」，四维共享同一时间锚
> **底层逻辑（2026-06-17 用户纠正后锁死）**：CVD/OI/资金费率存在的唯一意义 = 判断当前这一段**价格运动**是否被「确认 / 背离」。确认与背离都是**相对价格**的概念，脱离价格参照点单独读某指标的涨跌没有交易含义。所以**必须先用价格定锚，再看指标在同一段内的配合**——这正是经典背离分析（RSI/MACD/CVD 背离都锚定价格 pivot）的本质。

1. **第一步 · 定唯一锚点 = 主导的 1H 价格 pivot**：当前这一段「腿」的起点——
   * 下跌腿 → 锚 = 最近一个明显的 **1H 价格摆动高点**；
   * 上涨腿 → 锚 = 最近一个明显的 **1H 价格摆动低点**。
   * 锚点优先采用用户截图上已手绘的趋势线端点；无手绘线时自行目测最近的 1H 价格摆动极值。

   > 🟥🟥 **第一步之前先跑「腿选择 = 确定性程序·趋势线破位判定法」（2026-06-19 二次锚错腿后补·堵死 6/19 空隙·凌驾"找最近转折"的直觉）**：判断"当前在哪条腿"**不靠"最近一个转折点"**（会被 counter-trend 反弹/回撤噪声骗），而靠**主导趋势线有没有被结构性破位**——
   > 1. 看主导 1H 趋势线（优先用户手绘下行/上行线）。**价格仍在趋势侧**（下行线之下 / 上行线之上）→ 趋势未破 → 锚仍 = 启动该腿的摆动**高**(下跌腿) / **低**(上涨腿)；**腿内的 counter-trend 小反弹/小回撤不重置锚点**（它只是腿内噪声，不是新腿）。
   > 2. **仅当主导趋势线被决定性突破**（收盘明确越过该线 + 结构翻转：下行转 HH/HL / 上行转 LH/LL）→ 才重新锚定到新腿起点。
   > 3. 一句话：**选 pivot 看「主导趋势线是否被破」，不是看「最近 N 根有没有回弹」**。把"未破下行线的小反抽"误当"新上涨腿"去读「四维上升」＝2026-06-19 锚错腿错误（与 2026-06-17「用指标自身局部极值」并列为两类锚错·二者都属"错锚")。
   > 4. **示例（6/19 早）**：价自 6/16 摆动高 ~66,950 沿下行线下挫至现 ~62,950，末段几小时小反抽 62,000→63,020 **未破下行线** → 腿仍是下跌腿、锚仍 = 66,950 → 四维读「CVD横盘/价格下降/持仓横盘/费率上升为正」= 小幅看跌背离·55。❌ 错读 = 锚在 62,000 低读成「CVD上升/价格上升」。
2. **第二步 · 价格方向** = 从该 pivot 连到现价的斜率（up/flat/down）。
3. **第三步 · CVD / OI / 资金费率都在「同一段」(price pivot → 现值) 内读净变化斜率**，问的是「相对这段价格运动，它 confirm 还是 diverge」：
   * 明显向上 → `up`（上升）／明显向下 → `down`（下降）／基本走平、净变化很小 → `sideways`（横盘）。
4. **🟥 四维共享同一时间锚（= 价格 pivot），绝不各取各的局部极值。** 指标末端 2-3 根的微动是噪声，只看从价格 pivot 起的**净变化**；末端微跌/微涨 ≠ 趋势（2026-06-17 教训：把 CVD 末端 -13K→-14.6K 微跌误读为「下降」，而锚定 6/16 价格高点 CVD 近水平=横盘=卖压未放大→隐性派发=小幅看跌背离·看跌，**非"吸收=看涨"**）。
5. **不要求精确数值**：是趋势方向判断，不套 ±0.5% / ±3% 绝对阈值；解读落到文本（上升/横盘/下降 + 一句话含义）。

> **横盘 vs 下降/上升 的交易含义天差地别（务必锚准）——方向结论一律以下方 §四维合成「背离合成引擎」+ `orderflow_methodology.md §二` 为准，本表只描述"力度放没放大"、不得自行得出与引擎相反的方向**：
> * CVD **下降** + 价格下降 = 主动卖盘放大、**卖压坐实**（单边偏空确认·燃料已烧）；CVD **横盘** + 价格下降 = 主动卖压**没放大**（价靠缺买盘 + 现货真供给压下）。
> * CVD **上升** + 价格上升 = 主动买盘放大、买盘坐实（单边偏多确认）；CVD **横盘** + 价格上升 = 主动买盘**没放大**。
> 🟥🟥 **"卖压/买盘没放大" ≠ relief/反向——务必按投入产出比定方向（见 §四维合成 锁死）**：CVD横盘(0) + 价跌(负)（0>负）= 隐性派发 = **看跌**（小幅看跌背离·被套多头，**绝非"吸收=轻微看涨/relief"**，此为 2026-06-17 误读根 + 2026-06-19 复发框架）；CVD横盘(0) + 价涨(正)（0<正）= 隐性吸筹 = **看涨**（小幅看涨背离·6/10 真值锚 横盘/上升/...=55，**非"诱多=轻微看跌"**）。
> 错锚（用指标自身局部极值代替价格 pivot，或把 counter-trend 小反抽误当新腿）会系统性高估方向力度、把噪声当趋势，是 2026-06-17 把 C52 误读成 C79、2026-06-19 把下跌腿误读成"四维上升"的根因。

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
* `funding_rate_state`（相对零轴的水平，作为 C01–C81 第四维与强弱修正）：
  * `> +0.01%` → `positive` / `< -0.01%` → `negative` / 区间内 → `near_zero`
* 呈现写法照用户样本：「资金费率{上升/横盘/下降}（为正值/为负值/低于正常值/极负值）」。
  * 例：「下降（为负值）」「上涨略低于正常值」「横盘（为正值）」。
* 理由：趋势=拥挤度在变化（升=多头加杠杆/降=去杠杆出清）；正负=多空谁付钱。二者信息不同，缺一不可，但都只能调节主体三件套结论的风险与强度，不能单变量翻向。
* C01–C81 组合编号只由 `CVD方向 × 价格方向 × OI方向 × funding_rate_state` 确定；不得使用旧 C01/C02 合并签名。

### 🟥 四维合成看涨/看跌＝背离合成引擎（2026-06-17 锁死·权威全文见 `scoring/orderflow_methodology.md`§二·补）
> 把四维合成成 看涨/看跌/中性 信号时，**背离读"被套的那一方"，不是 CVD 对价格**（违反即把偏空读成偏多）：
> 1. **主体三件套先定方向**：先联合解释 CVD、价格与 OI；资金费率只调风险与强度，不得单独翻转结论。
> 2. **效果背离必须对照新高/新低**：CVD 创新高而价格未同步创新高＝买力未兑现＝看跌背离；CVD 创新低而价格未同步创新低＝卖力未兑现＝看涨背离。价格反抽、普通上涨或跌破小级别位置，不等于创新高/低。
> 3. **OI 下降必须结合价格兑现分类**：价格上涨并真正突破/创新高时，可解释为空头回补 squeeze；价格反抽但滞涨、未创新高时，应保留“获利空头止盈＋现货供给仍在”的解释。禁止机械把 `价格↑+OI↓` 一律读成偏多。
> 4. **足迹只复核**：Exocharts 只能确认、削弱或反驳 Coinglass 主判断；不能独立翻向或独立制造极端。

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

# C01–C81 组合与评分（唯一有效口径）

本 Agent 不再保留旧 C01–C16 死查表，避免模型把已废规则误当当前指令。唯一权威是 [`scoring/orderflow_methodology.md`](../scoring/orderflow_methodology.md) 与 `scoring/scoring_contract.json`：

* 组合编号由四维状态确定性推导，不接受模型自填编号覆盖。
* C19/C22/C56/C59 只是极端候选；整体证据确认才是 70，接近极端为 60。
* 非极端最高 60；0–60 内允许有完整方法论依据的任意整数精细分。
* 历史样本只校准方法与强弱，不把历史方向、组合编号或分数带入当前时段。

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
