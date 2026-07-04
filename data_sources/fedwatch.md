# CME FedWatch 数据规则

## 数据源
https://www.cmegroup.com/cn-s/markets/interest-rates/cme-fedwatch-tool.html

---

## 核心用途
- 判断美联储利率预期
- 辅助宏观流动性判断
- 辅助主账户与Maker操作决策

---

## 输出要求
- 使用文字记录，不允许截图替代
- 必须记录以下信息：
  - 利率概率分布
  - 预期变化方向（加息/降息/维持）
  - 对市场流动性潜在影响

---

## 时间规则
- 数据必须为当日实时数据
- 禁止使用历史概率数据
- 禁止使用过期预测

---

## 异常处理
- 浏览器截图为错误页、空白页或 iframe 未渲染：
  1. 重试截图 1 次；
  2. 仍失败时，改用全网权威数据回退，不因截图渲染故障单独硬停。
- 权威来源优先级：
  1. CME Group 官方 FedWatch 页面、API 或官方发布；
  2. Federal Reserve 官方资料；
  3. 明确引用 CME FedWatch 且标注数据时点的主流金融数据源。
- 关键数字至少双源交叉核验；必须记录 URL、采集时间、下次 FOMC 日期、各目标区间概率以及 1日/1周/1月变化。
- 回退结果写入 `fedwatch.json`，标记：
  - `capture_mode: "authoritative_web_fallback"`
  - `screenshot_valid: false`
  - `screenshot_error`
- 若权威数据也无法取得或无法核对：
  - 输出标注“FedWatch数据待补充”
  - 禁止任何主观推测，并停止生成可执行计划。

---

## Agent限制
- 不得编造利率概率
- 不得推测未来利率影响
- 仅允许客观记录并传递给评分系统
- 评分和执行决策必须基于真实数据

---

## 核心原则
- 数据真实性优先于完整性
- 实时性高于可读性
- 宁可缺失，也不得伪造
