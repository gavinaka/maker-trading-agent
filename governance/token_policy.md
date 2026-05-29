# Token Governance System

## Core Principle

* 系统所有操作必须控制 Token 消耗
* Token 不足时禁止非必要操作
* 权限不足时必须明确提示，不允许 AI 自行绕过
* 所有操作必须被追踪和记录

---

## Token Consumption Rules

1. **每日操作预算**

   * Claude Code 每日 Token 限额由系统定义
   * 每次执行任务消耗 Token，必须实时更新 Token 状态

2. **高优先级任务**

   * 自动生成主账户日报
   * Maker 日内策略更新
   * 风控检核
   * Score 系统更新
   * 交易复盘

   **仅在 Token 足够时执行**

3. **低优先级任务**

   * 历史数据分析
   * 数据可视化
   * 非关键通知

   **Token 不足时可延迟**

---

## Permission Rules

* 所有外部网站访问必须基于授权 Token

* 权限不足时：

  * 标记 `待手动处理`
  * 禁止 AI 自行跳过或推测结果

* BlockBeats 新闻必须截图，禁止 AI 自行生成或替代

---

## Token Logging

* 每次任务执行必须记录：

  * 时间戳
  * Token 消耗数量
  * 任务类型
  * 执行状态（成功/失败/待处理）

* Token 使用数据用于：

  * 调整每日预算
  * 优化任务优先级
  * 检测异常消耗

---

## Principle

Token 是系统资源，不允许浪费。

* 优先保障核心交易与风控任务
* 次要任务可延迟或合并
* 严格遵守 Token 消耗规则保证系统稳定
