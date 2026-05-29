# Phase 01 — Data Collection（拆分细则）

> 本文件细化 `governance/workflow.md` 的 Phase 01。
> 原 Phase 01 仅描述"读取 4 个数据源"，未定义采集失败、数据时效、降级路径。
> 本文件补齐采集流程契约。

---

## Phase 01a — Pre-check

执行：scoring_agent / output_agent 在自己启动前**必须先**调用此步骤。

```
1. 读 data_sources/inbox/<today>/_manifest.json
2. 若不存在 → 进入 Phase 01b
3. 若存在：
   a. 校验通过 schemas/inbox_manifest_schema.json
   b. 对每源动态计算 freshness_minutes = now - captured_at
   c. 按 data_sources/freshness_rules.md 判断时效
   d. all_complete:true 且全部新鲜 → 跳到 Phase 01c
   e. 任一源失效 → 进入 Phase 01b（仅采集失效源）
```

---

## Phase 01b — Collect

执行：data_collection_agent

```
1. 对每个待采集源（按 collectors/<source>.md SOP）：
   * 按通道优先级（A → B → C）尝试
   * BlockBeats 跳过 B
2. 单源完成后原子更新 manifest
3. 失败 → 记 valid:false + error
4. 超时（默认 30 分钟整体预算）→ 中止
```

降级触发条件：

| 现象 | 动作 |
|---|---|
| Chrome MCP 未连接 | A 整体降级到 C |
| 站点 403 / Cloudflare | A 该源降级到 B（如允许）或 C |
| 站点登录墙 | A 该源降级到 C |
| 页面结构变化导致选择器失效 | A 该源降级到 C，记 `collector_sop_needs_update: true` |
| WebFetch 限流 | B 该源降级到 C |
| 用户未在 30 分钟内投递 | C 失败，该源 `valid:false` |

---

## Phase 01c — Validate

执行：data_collection_agent 收尾步骤

```
1. news_agent 校验 BlockBeats 合规（captured_by ∈ A|C，screenshot_count > 0）
2. 重算 all_complete + missing
3. 写 session_state.tasks.data_collection_done = <derived>
   （注：当前 session_state.tasks 无此字段，下版本增）
4. 触发下游：
   * all_complete:true → 通知 scoring_agent 启动
   * all_complete:false → 通知 scoring_agent："仅 [missing] 缺失，可降级评分（仅基于现有数据）"或"全部缺失，禁止评分"
```

---

# 完整调用链

```
session_state.current_day 触发 →
  data_collection_agent.run()
    ├─ Phase 01a Pre-check (读 manifest)
    ├─ Phase 01b Collect (按通道降级)
    └─ Phase 01c Validate (写 manifest + 通知)
  ↓
  scoring_agent.run() (Phase 02)
  ↓
  状态门禁 (Phase 04)
  ↓
  ... 后续 Phase 同 workflow.md
```

---

# 失败传播规则

* Phase 01b 全部 4 源失败 → scoring_agent 直接退出，写 `current_score.result = "数据完全缺失"`
* Phase 01b 部分失败 → scoring_agent 仍可运行，但 result 自动降级（缺 exocharts → orderflow_score 不可算 → total 必 < 70 → 强制观望）
* output_agent 永远可以生成日报；缺失字段标"待补充（数据源失败）"

---

# 与 source_rules.md 的对齐

本文件不修改 `source_rules.md`，只补充其未定义的工作流：

* `source_rules.md` 说"数据真实性高于完整性" → 本文件用 manifest + freshness 强制实现
* `source_rules.md` 说"BlockBeats 必须截图" → 本文件用通道白名单 + news_agent 校验强制实现
* `source_rules.md` 说"读取失败标记待补充" → 本文件定义"待补充"在数据流中如何传播
