# Maker 早间盘前模板（图谱第十一节）

> 由 `agents/output_agent.md` 渲染，时段：早间盘前（09:00 - 11:00）
> 模板核心：观望 OR 有计划，二选一。无中间状态。

---

## 模板：观望版

```
【早间盘前】{{YYYY-MM-DD}}

BTC（策略）：[观望]
  理由（按优先级，至少 1 条，至多 3 条）：
    {{- 总评分 X 未达 70 门槛}}
    {{- 主账户限制方向不匹配}}
    {{- 状态门禁阻断：[项]}}
    {{- 数据源失效：[列表]}}
    {{- 震荡结构 / 个人状态}}

  执行概率：0%
  注意事项：{{若 11:00 评分点重评后达标且方向匹配，可重新生成计划}}
```

---

## 模板：有计划版

```
【早间盘前】{{YYYY-MM-DD}}

BTC（策略）：[有计划]
  执行概率 {{X}}% 胜率 {{X}}%（已执行 {{X}}%）
  {{高空 | 低多 | 反弹空}}：{{价格区间}} 持仓 {{金额}}刀 [OKX] {{左侧 | 右侧}} 盈亏比 1:2.5 以上
  止盈：{{价格}}（TP1）减仓 {{X}}%
  止损：{{价格}}
  浮盈防守计划：
    第一层：{{触发条件}} → {{操作}}
    第二层：{{触发条件}} → {{操作}}
    {{第三层（可选）：触发条件 → 操作}}
  注意事项：若价格优先触及 {{价格}} 则取消此策略
```

---

## 字段来源

| 字段 | 来源 |
|---|---|
| 是否观望 | `state/score_state.json.current_score.total_score >= 70` AND `risk_agent.precheck.decision == "allow"` |
| 总评分 | `state/score_state.json` |
| 当天 Maker 不能做（市场推导，非主账户） | footprint signal_type 推导：禁追最拥挤一边（见 `constitution/cannot_do_mapping.md`） |
| 状态门禁阻断项 | `outputs/<today>_emotional_log.json.blocked_reasons[]` |
| 数据源失效 | `inbox/<today>/_manifest.json.missing[]` |
| 执行概率 / 胜率 | 用户输入（基于历史样本） |
| 已执行 % | `state/maker_state.json.clean_sample_system.current_progress_pct`（参考） |
| 策略方向 | footprint signal_type + 当天 Maker 不能做（禁追最拥挤一边）推导 |
| 价格区间 | `inbox/<today>/exocharts_btc_1h.json.key_levels` |
| 持仓金额 | `state/maker_state.json.position_rules.default_position_size_usd.BTC` 区间 |
| 入场方式 | `state/maker_state.json.default_entry_type` 默认 left_side（左侧） |
| 盈亏比 | 用户填写，必须 ≥ 1:2.5（`state/maker_state.json.entry_rules.require_risk_reward_ratio`） |
| 止盈/止损 | 用户填写，risk_agent Gate 4 校验 R:R + Gate 2 校验 ≤ 3% |
| 浮盈防守 | 用户填写，risk_agent Gate 6 校验层级递进合法 |
| 取消价格 | **强制字段**，用户填写，缺失则 output_agent 拒绝渲染 |

---

## 示例：观望（2026-05-29 真实场景）

```
【早间盘前】2026-05-29

BTC（策略）：[观望]
  理由：
    - 总评分 50 未达 70 门槛（数据陈旧 3 日，待 11:00 重评）
    - 当天 Maker 不能做多（拥挤侧）→ 仅偏空，但分数未达
    - 4 个数据源全部待采集（Exocharts / Coinglass / BlockBeats / FedWatch）

  执行概率：0%
  注意事项：若 11:00 评分点重评后达标且方向匹配（做空），可重新生成计划
```

---

## 示例：有计划（参考历史样本 2026-05-18）

```
【早间盘前】2026-05-18

BTC（策略）：[有计划]
  执行概率 70% 胜率 75%（已执行 22%）
  高空：68500-69200 持仓 800 刀 [OKX] 左侧 盈亏比 1:3.5
  止盈：65800（TP1）减仓 40%
  止损：69500
  浮盈防守计划：
    第一层：价格触及 67000 → 止损移至 68500（开仓均价）
    第二层：价格触及 66200 → 止损移至 67000（保本+小幅锁利）
    第三层：价格触及 65800（TP1）→ 减仓 40%
  注意事项：若价格优先触及 69500 则取消此策略
```

---

## 渲染规则

1. **二选一**——观望 OR 有计划，禁止"部分观望 + 部分计划"
2. **取消价格强制**——有计划版必含"注意事项"段，缺失则拒绝渲染
3. **R:R 强制**——盈亏比文字必须出现 "1:2.5 以上"，且实际值需 ≥ 1:2.5
4. **仓位区间**——BTC $500-$1000，超出由 risk_agent 拒绝
5. **杠杆**——5x 是默认，不在模板显式写（避免误改）；维护在 state 文件
6. **入场方式**——左侧优先，右侧需用户在备注说明理由
