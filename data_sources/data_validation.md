# 数据验证规则

## 核心目标
确保所有输入数据：
- 真实
- 完整
- 实时
- 格式正确

禁止：
- AI推测或补全缺失数据
- 使用历史缓存替代当日数据
- 任何形式的数据造假

---

## 验证流程

### 1. 数据完整性
- 检查每个数据源是否返回数据（🟥 六源缺一不可）
  - ExoCharts
  - Coinglass
  - BlockBeats
  - FOMC 利率预期逻辑插槽（CME primary；仅 closed technical failure 可用 Kalshi Plan C）
  - Farside BTC ETF Flow（`farside_btc_etf.png` + `farside_btc_etf.json`，latest Total 必须为数值）
  - TradingView（日/4H/1H/15m 四档齐·2026-06-14 补）
- 若数据缺失（含 TV 任一档或 Farside JSON 无效）→ 立即停止，禁止继续生成计划或以“待补充”占位。
- CME 有效时必须有真实 `fedwatch.png`、sealed attempt 与 provider provenance，且不得
  调用或混入 Kalshi。只有同 run 的 eligible CME 技术失败可使用一次 Kalshi Plan C；
  此时必须同时存在并校验 `cme_fedwatch_result.json`、`kalshi_feddecision_raw.json`、
  `fedwatch.json` 与 `rate_expectation_provenance.json`。这不是泛化网络回退，也不是
  “关键数字双源择优”。

### 2. 数据格式验证
- 数值型字段（价格、CVD、资金费率、持仓量）：
  - 确保可解析为浮点数
  - 范围合理（如资金费率±5%以内）
- 日期/时间字段：
  - 格式 YYYY-MM-DD 或 HH:MM
  - 与计划时间对应

### 3. 数据一致性
- 同一时间段不同来源数据需按各自方法边界交叉比对；CME 与 Kalshi 不得混算或择优
- CVD、价格行为、持仓量等互相验证逻辑一致
- 异常差异需标注“待复核”

### 4. 异常标注
- 网站无法访问或数据异常：
  - 标记“待补充”
  - 禁止使用默认或历史值代替
- FedWatch 插槽仅允许合同闭集 CME 技术故障触发 Kalshi public API
  `KXFEDDECISION`；不得把搜索摘要、旧闻、无日期转载、其它 API/series 或模型估算
  视为有效数据。Kalshi 必须标为非 CME 方法等价和 observation-only。
- 数据读取错误：
  - 输出错误类型
  - 停止对应模块

### 5. Agent行为限制
- 不得自动修正异常数据
- 不得预测缺失字段
- 不得使用模糊描述替代真实数据
- 所有输出必须明确标注状态（有效/待补充/异常）

---

## 核心原则
1. 数据真实性高于完整性  
2. 实时性高于可读性  
3. 宁可缺失，也不得伪造
