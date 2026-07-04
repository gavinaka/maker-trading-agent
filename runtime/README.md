# 三时段原始证据共享与全量分析运行层

本目录只优化确定性采集、证据装配与上下文隔离，不定义交易方法论，也不缩减推理。

## 固定不变量

- 早报、午报、晚报均独立输出，时间与 Notion 结构不变。
- 早报建立原始证据来源基线；午报、晚报只在采集层复用有效原始证据。
- 每时段完整重算全部特征、评分、胜率、风险、情景、决策与报告。
- `current.json` 不含分析结论；分析和决策仅归档为 post-lock only。
- pre-analysis 禁止读取前序方向、分数、胜率、风险和 Maker 结论。
- 从验真／读图／转录开始使用最高可用模型能力与 MAX 思考预算，资源不足即硬停。
- 缺源、无基础状态、方法论哈希变化、时段乱序或状态损坏时完整采集回退。

## 标准流程

```powershell
# 1. 无前序判断泄漏的 pre-analysis 上下文
py runtime/context_pack.py --date 2026-06-29 --slot midday

# 2. 取得整链租约
$lease = py runtime/session_runner.py begin-session --date 2026-06-29 --slot midday | ConvertFrom-Json
$token = $lease.token

# 3. 数据采集，保存输出中的 DELTA_MANIFEST/FULL_CAPTURE_MANIFEST 精确路径
node tools/browser_capture/capture_delta.js --lease-token $token
# 晚报用：
# node tools/browser_capture/capture_delta.js --evening --lease-token $token
# 早报用：
# node tools/browser_capture/capture_all.js --slot morning --lease-token $token

# 4. 生成来源变化诊断 + 完整分析任务清单
py runtime/session_runner.py prepare `
  --date 2026-06-29 `
  --slot midday `
  --capture-manifest <DELTA_MANIFEST精确路径> `
  --lease-token $token `
  --max-reasoning-confirmed

# 5. 完成 MAX 独立分析、combined.md 与 lint 后锁定
py runtime/session_runner.py lock-analysis `
  --date 2026-06-29 `
  --slot midday `
  --report outputs/2026-06-29_midday_combined.md `
  --lease-token $token `
  --confirm-five-source-validation `
  --confirm-full-analysis `
  --confirm-no-prior-judgment `
  --confirm-max-through-analysis

# 6. 锁后读取前序计划，完成撤旧挂新／漂移对照
py runtime/session_runner.py finalize-post-lock `
  --date 2026-06-29 `
  --slot midday `
  --lease-token $token `
  --confirm-prior-plan-continuity-reviewed `
  --confirm-max-through-post-lock

# 7. 归档锁定结果
py runtime/session_runner.py commit `
  --date 2026-06-29 `
  --slot midday `
  --report outputs/2026-06-29_midday_combined.md `
  --lease-token $token

# 8. Notion 唯一页、冻结 verifier、Word 视觉 QA 与 context_log 全部 PASS 后
py runtime/session_runner.py deliver `
  --date 2026-06-29 `
  --slot midday `
  --page-id <page_id> `
  --lease-token $token
```

禁止使用不能携带整链租约的旧 `npm run all` / `npm run delta` 快捷入口。

## 文件职责

- `context_pack.py`：只提取交付连续性，不复制前序分析或决策。
- `delta_engine.py`：源文件 SHA-256 与变化集合。
- `dependency_graph.py`：记录来源影响范围，同时强制每时段完整分析。
- `state_store.py`：不可变证据状态、post-lock 分离归档和完整采集回退。
- `report_state_extract.py`：锁定后归档报告分析，禁止下时段复用。
- `intent_router.py`：本工作区早／午／晚日报的隔离意图分类。
- `usage_logger.py`：记录耗时、重试、回退和真实 Token。
- `session_runner.py`：prepare／lock-analysis／finalize-post-lock／commit／deliver 统一入口。

运行产物位于 `runtime_state/<YYYY-MM-DD>/`，已加入 `.gitignore`。
