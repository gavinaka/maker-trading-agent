# Trading-System 日报质量事故取证审计与修复报告（2026-07-04）

## 结论

本次质量退化不是模板问题，而是工作流权威链断裂、分析前上下文污染、证据不可变性不足和机械门缺失共同导致。

已经完成的修复目标：

1. Maker 浮盈防守第一层从 4H 极点漂移到 1H/15m 的路径已被规则与 lint 双重锁死。
2. Notion 实际持仓不得影响 Maker/主账户独立判断，已从依赖图、SOP、状态抽取、lint、测试中切断。
3. Exocharts 旧 K 线十字光标误读已在采集层降低概率，并在报告层用 OHLC/当前价自洽门硬拦。
4. ③后附推理深度退化已建立结构化深度门，短摘要型报告不能再通过。
5. 每次采集已绑定不可变 evidence snapshot，`prepare_transition` 不再读取可覆盖的 `data_sources/inbox/<date>` 作为报告证据。
6. `lock-analysis` 不再只依赖 CLI 布尔确认，commit 要求 lint/report_state/source/position-coupling 机器验证证据。
7. SOP/skill 引用的 memory 文件已恢复并纳入逻辑版本；缺失引用或未纳入 `LOGIC_FILES` 会硬停。
8. 已新增 2026-06-22..26 本地黄金样本质量回归门，未来报告低于该批样本的推理承载量、数值锚点和 rubric 推导链下限会硬停。

## 关键证据

### Maker 第一层规则漂移

- 2026-06-21 至 2026-06-26 稳定高质量样本使用 `4H 级别极点高点/低点`。
- 2026-06-27 起开始出现 `1H 级别极点`。
- 2026-06-29 与 2026-07-02 出现 `15m/15分钟级别极点`。
- Claude 项目 memory 中存在 `defense-layer2-vs-tp1-conflict.md`，但仓库 `memory/` 当时缺失该规则文件。

### 持仓污染

`outputs/2026-07-03_morning_combined.md` 中出现：

- `持仓校准：主账户无持仓；Maker账户BTC空单计划...已成交50%`
- `观望·不挂单（Maker账户已有BTC空单成交50%...禁止新增或补仓）`
- `评分与胜率满足开单条件，但Maker账户已有方向相反的空单持仓...风控门阻断新增挂单`

这违反“独立报告必须由五源、评分、胜率和风控规则推出，不得由 Notion 实际持仓改写 Maker 策略”的边界。

### Exocharts 数据自洽错误

`outputs/2026-07-03_morning_combined.md` 声明：

- 当日未完成 K：高 `60,649.9`
- 当前图面价格：`61,437.9`

当前价高于所称当日 K 线最高价，说明顶部 OHLC 很可能来自旧 K 线十字光标，而不是当前当日 K 线。

### 推理深度退化

基线与当前报告的 ③后附长度差距：

- `outputs/2026-06-26_morning_combined.md`：③后附约 10k 字符。
- `outputs/2026-06-25_morning_combined.md` 与 `outputs/2026-06-26_morning_combined.md`：黄金质量门 0 命中。
- `outputs/2026-06-27_morning_combined.md`：黄金质量门命中 4 项：总承载量 5795 chars、③后附 3607 chars、数值锚点 88、rubric=1。
- `outputs/2026-07-02_morning_combined.md`：③后附约 2.8k 字符。
- `outputs/2026-07-03_morning_combined.md`：黄金质量门命中 4 项：总承载量 3658 chars、③后附 2930 chars、数值锚点 66、rubric=0。

这与“正文精炼但推理转入 ③ 后附，不得缩减”的宪法要求冲突。

## 根因

1. **规则权威缺口**：SOP/skill 引用多个 `memory/*.md`，但仓库缺失这些文件；模型无法从工作区读取完整规则，只能靠残缺上下文和记忆。
2. **依赖图污染**：`source:notion_positions` 原先能传导到 `decision:maker`，把实际持仓变成 Maker 决策输入。
3. **lint 覆盖不足**：旧 lint 没有硬拦 1H/15m 首层、持仓污染决策、Exocharts OHLC 自洽、③后附深度。
4. **证据可覆盖**：早/午/晚共享 `data_sources/inbox/<date>`，后续采集可覆盖前序报告证据。
5. **分析锁布尔自证**：旧 `lock-analysis` 会在报告结构很浅时把所有分析节点标成完成。
6. **采集十字光标状态未复位**：Exocharts LIVE takeover 固定点击后，截图前没有确保十字光标回到最新 K 线。

## 已实施修复

- `memory/defense-layer2-vs-tp1-conflict.md`：恢复 Maker 防守层金标规则。
- `risk/floating_defense.md`、`constitution/maker_principles.md`、`.agents/skills/daily-report/SKILL.md`、`sessions/日报SOP.md`：明确第一层必须 4H 极点，持仓只允许锁后校准。`.claude/skills/daily-report/SKILL.md` 仅保留为本机兼容镜像，不作为 Codex committed 权威。
- `runtime/dependency_graph.py`：`notion_positions` 不再触达 Maker/主账户决策、分数或胜率。
- `outputs/report_lint.py`：新增持仓污染门、Maker 防守层门、Exocharts 自洽门、分析深度门、黄金样本质量回归门。
- `runtime/report_state_extract.py`：去掉 position_summary 锁前强依赖，并对持仓污染锁硬停。
- `tools/browser_capture/capture_exo.js`：截图前 hover 最新 K 线区域。
- `tools/browser_capture/capture_lock.js`、`capture_all.js`、`capture_delta.js`：采集后生成不可变 evidence snapshot。
- `runtime/state_store.py`：`prepare_transition` 只扫描 manifest 绑定的 snapshot；commit 要求 `analysis_validation`。
- `runtime/session_runner.py`：`lock-analysis` 写入 lint/report_state/source/position-coupling 验证证据。
- `runtime/context_pack.py`：校验权威文件和 memory 引用完整性；`memory/MEMORY.md` 作为禁止读取项不进入 pre-analysis authority。
- `.agents/skills/daily-report/SKILL.md`：Codex 入口改为以已提交的 `sessions/日报SOP.md` 为主权威；`.claude/skills/daily-report/SKILL.md` 仅作为本机 Claude Code 兼容镜像，避免 Codex 新入口依赖被 git 忽略的 `.claude/`。
- 回归测试覆盖上述事故路径。

## 追加迁移审计：Claude Code 清理机制与旧能力平移

用户补充要求核实 Claude Code 时期的清理机制并将旧工作流能力完整平移到 Codex。核实结果：

- 清理机制确实存在：`tools/browser_capture/cleanup.js`，由 `capture_all.js` 开头自动调用；只删过期 `data_sources/inbox/<date>/` 截图与 `outputs/blockbeats/<date>_*.png` 快讯卡，默认保留最近 `CLEANUP_KEEP_DAYS=2` 天，绝不碰当天图。
- committed SOP 已有自动清理条款，但 Codex 入口原先未显式继承；已补进 `.agents/skills/daily-report/SKILL.md`，并写明不得删除当日动态图、锁定 evidence snapshot 或任何 manifest。
- 旧 `.claude/skills/daily-report/SKILL.md` 中 4 个关键 memory 引用未显式出现在 committed SOP/Codex 入口：`memory/independent-report-no-user-reference.md`、`memory/precise-numbers-no-fuzzy.md`、`memory/report-chinese-only-narrative.md`、`memory/notion-publish-checklist.md`。底层 `LOGIC_FILES` 已包含这些文件，但触发层引用不完整；已补进 SOP 与 Codex 入口。
- SOP 中两处旧口径把命令权威指向 `.claude/skills/daily-report/SKILL.md`。由于 `.claude/` 被 gitignore，Codex 不得依赖它作为 committed authority；已改为 `sessions/日报SOP.md` + `.agents/skills/daily-report/SKILL.md` 为准，`.claude` 仅作兼容镜像。
- 新增 `tests/test_codex_claude_parity.py`，机械检查旧 Claude guardrail refs、cleanup 条款、以及 Codex 不得把执行权威委托给 ignored `.claude` 镜像。

## 可复现验证

已通过：

```powershell
py -m unittest discover -s tests -p 'test_*.py' -v
```

结果：59 个测试全部通过。

已通过：

```powershell
node --check tools/browser_capture/capture_lock.js
node --check tools/browser_capture/capture_all.js
node --check tools/browser_capture/capture_delta.js
node --check tools/browser_capture/capture_exo.js
```

样本验证：

- `py outputs/report_lint.py outputs/2026-06-26_morning_combined.md`：通过。
- `report_lint.golden_quality_check(outputs/2026-06-25_morning_combined.md / 2026-06-26_morning_combined.md)`：0 命中。
- `report_lint.golden_quality_check(outputs/2026-06-27_morning_combined.md / 2026-07-03_morning_combined.md)`：各命中 4 项，证明 6/26 后质量断崖会被硬拦。
- `py outputs/report_lint.py outputs/2026-07-02_morning_combined.md`：失败，命中持仓污染、15分钟首层、分析深度不足。
- `py outputs/report_lint.py outputs/2026-07-03_morning_combined.md`：失败，命中持仓污染、Exocharts OHLC/当前价矛盾、分析深度不足。

## 当前边界

- 本次修复面向未来工作流和发布门禁；没有重写或重新发布历史错误 Notion 页面。
- 仓库原本存在大量未提交/未跟踪文件；本次没有执行 git commit，也没有清理用户历史产物。
- 下一次实际跑日报时，应按新流程重新采集五源并由 snapshot 绑定证据，旧的 7/2、7/3 runtime 产物不应被当作合格样本继续使用。
