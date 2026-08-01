# Token Governance System

## Core Principle

* Token 优化只作用于确定性采集、文件处理、纯算术、lint、verifier、渲染、发布等机械层
* 从源有效性验真、图表阅读和指标转录开始，全部属于宪法级完整推理区
* 完整推理区固定 `gpt-5.6-sol`：vNext 请求 exact `xhigh`，legacy 请求 exact `high`；宿主只证明对应 `>= minimum`，不改变请求值，也不是正确性依赖；始终加载全部 authority
* 完整推理区禁止低于所选引擎的 sealed minimum、截断、复用前序推理、只重算变化节点或因省 Token 省略资源
* 推理资源不足时硬停，不允许降质继续
* 权限不足时必须明确提示，不允许 AI 自行绕过
* 所有操作必须被追踪和记录

---

## Token Consumption Rules

0. **双层预算**

   * 机械层：以减少重复采集、重复解析、重复发布和无意义上下文为目标
   * 推理层：不设节省 Token 的质量上限；质量、独立性和完整工作流深度优先
   * 早／午／晚三份报告的源验真、图表阅读、反证、情景、决策和解释属于推理层；评分schema名义70+30（当前production有效盘口0–60+盘面0–30）、胜率调整求和、风险收益算术必须由决策门机械复算，不能用推理深度替代算术正确性

1. **每日操作预算**

   * Codex 宿主的实际 token/轮次由 session JSONL 记录，仓库不得自造限额或用字符数估算
   * 每次执行任务消耗 Token，必须实时更新 Token 状态

2. **高优先级任务**

   * 自动生成主账户日报
   * Maker 日内策略更新
   * 风控检核
   * Score 系统更新
   * 交易复盘

   **必须以完整工作流深度执行且宿主 effort 不低于所选引擎的 sealed minimum；资源不足则硬停，禁止降档或缩减推理**

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

### 运行实现（2026-06-29）

* 唯一运行日志：`runtime_state/<YYYY-MM-DD>/usage.jsonl`
* 写入器：`runtime/usage_logger.py`
* 每个早／午／晚节点至少记录 `prepare`、`analysis_lock`、`post_lock_finalize`、`commit`、`render_docx`、`word_export`、`visual_qa`、`publish` 和 `delivery`。
* 必记：耗时、工具调用、重试、完整回退次数；Token 仅记录宿主真实返回值。
* 宿主不提供 Token 计数时写 `null`，禁止根据字符数或感觉伪造 Token。
* 每条记录必须有稳定 `event_id`；同一阶段重放不得产生重复记录。早报正常全量基线不计作 fallback。
* 逻辑／方法论版本变化只使分析失效，不属于采集 fallback；完整重采仅限证据失败、缺失、过期或无效。
* DOCX 同输入哈希复用；Word 导出固定 Word COM 后端；渲染/导出最多两次，第三次硬停。该限制只约束机械试错，不限制完整推理深度。
* 优化效果以同类节点 7 日移动中位数比较，不以单次波动下结论。

### 宿主真实用量与效率目标（2026-07-10）

* 交付后使用 `runtime/host_usage_import.py` 从当前 `CODEX_THREAD_ID` 对应 JSONL 导入真实 `last_token_usage`、模型轮次、工具调用和 compaction 数；不再依赖仓库内长期为 `null` 的占位计数。
* 方法论按 `context_pack.authority_read_plan` 分阶段加载；同一阶段先由 `runtime/phase_contract.py` 合并为 hash-bound bundle，只读一次。always-read 总量硬限 40KiB，并由真实仓库集成测试保留至少 15% 余量。
* 报告质量门禁止使用字符数、价格引用次数或工具调用次数作为“推理深度”代理。
* 初始效率目标：模型轮次 ≤80、非缓存输入 ≤800,000。目标超限只触发工程复盘，不得删减六源、完整推理、反证、风险或证据门来“达标”。

---

## Principle

Token 是系统资源，不允许浪费。

* 优先保障核心交易与风控任务
* 次要任务可延迟或合并
* 机械层追求效率，推理层追求最大能力与完整质量
