# 输出报告总规范（图谱第十六节）

> 系统所有产出文件的统一规范。任何 agent 写文件前必须读本文件。
> ⚠️【已迭代·2026-05/06】实际交付格式 = **.docx（python-docx）+ Notion 子页（🌅/🌙/🔍）**，见 agents/output_agent.md 与 /daily-report skill。下文的 `.txt 桌面合并版` 为参考设计层旧格式、已停用。

---

## 1. 文件类型与命名

| 报告类型 | 文件名格式 | 触发时机 | 责任 Agent | 落盘路径 |
|---|---|---|---|---|
| 主账户日报 | `<YYYY-MM-DD>_main_account_daily.md` | 早间盘前 | output_agent | `outputs/` |
| Maker 上午计划 | `<YYYY-MM-DD>_maker_morning.md` | 早间盘前 | output_agent | `outputs/` |
| Maker 晚间新增 | `<YYYY-MM-DD>_maker_evening.md` | 20:00 - 20:30 | output_agent | `outputs/` |
| 桌面合并版 | `<YYYY-MM-DD>_交易计划.txt` | 早间 + 晚间 | output_agent | `C:/Users/31702/Desktop/` |
| 日复盘 | `<YYYY-MM-DD>.md` | 23:00 之前 | review_agent | `reviews/` |
| 周报 | `<YYYY-Www>_weekly.md` | 周日 22:00 | review_agent | `reviews/` |
| 月报 | `<YYYY-MM>_monthly.md` | 月末 23:00 | review_agent | `reviews/` |
| 新闻摘要 | `<YYYY-MM-DD>_news_summary.json` | 数据采集后 | news_agent | `outputs/` |
| 盘口分析 | `<YYYY-MM-DD>_footprint_<HHMM>.json` | 每次评分前 | footprint_agent | `outputs/` |
| 情绪日志 | `<YYYY-MM-DD>_emotional_log.json` | 链 A 第 1 步 | emotional_agent | `outputs/` |
| 风控决策 | `<HHMMSS>_<mode>.json` | 每次开仓/precheck/modify | risk_agent | `outputs/<YYYY-MM-DD>_risk_decisions/` |
| 交易 Check | `<YYYY-MM-DD>_check_records.json` | 日复盘时 | review_agent | `outputs/` |
| 违规记录 | `<YYYY-MM-DD>_<NNN>.json` | 违规识别时 | penalty_agent | `governance/violations/` |
| 违规成本 | `<YYYY-MM-DD>_<NNN>.json` | 违规识别时 | penalty_agent | `governance/violation_costs/` |
| Session 日志 | `<YYYY-MM-DD>_session_log.json` | 每条链结束 | session_orchestrator | `outputs/` |
| 数据采集清单 | `_manifest.json` | 数据采集后 | data_collection_agent | `data_sources/inbox/<YYYY-MM-DD>/` |

---

## 2. 桌面合并文件结构（图谱十六节）

`C:/Users/31702/Desktop/<YYYY-MM-DD>_交易计划.txt`：

```
═══════ 主账户日报 ═══════
{{outputs/<today>_main_account_daily.md 内容}}

═══════ Maker 上午计划 ═══════
{{outputs/<today>_maker_morning.md 内容}}

═══════ Maker 晚间计划 ═══════（若已生成）
{{outputs/<today>_maker_evening.md 内容}}
```

注：
* 桌面版为 .txt（图谱十六节"格式：记事本（.txt）"）
* outputs/ 下为 .md（便于 Markdown 渲染查看）
* 内容来自源文件，桌面版只做合并，不做修改

---

## 3. 严格要求（图谱十六节）

1. **不推理、不预判**——数据不足直接询问用户（或标"待补充"）
2. **BlockBeats 新闻必须截图**——不得用文字生成替代
3. **所有判断词汇必须使用标准库**（`constitution/terminology.md`）
4. **数据来源必须基于当日实时抓取**——不得使用历史数据替代
5. **准确性是第一优先级，宁缺毋滥**
6. **如任何数据未能抓取，明确标注"待补充"并询问用户**

---

## 4. 时间戳与编码

* **时间格式**：ISO 8601 + GMT+8 时区（如 `2026-05-29T10:55:00+08:00`）
* **日期格式**：`YYYY-MM-DD`（如 `2026-05-29`）
* **文件名时段**：`<HHMM>`（4 位）或 `<HHMMSS>`（6 位，risk_decisions）
* **文本编码**：UTF-8 无 BOM
* **JSON 编码**：UTF-8 + 2 空格缩进
* **Markdown 编码**：UTF-8 + 标准 GFM（GitHub Flavored Markdown）

---

## 5. 写入原子性

所有文件写入必须原子：
1. 先写 `<filename>.tmp`
2. 校验完整性（字节数 > 0，必含字段存在）
3. 重命名为目标文件名
4. 失败 → 删除 `.tmp`，不留半文件

state JSON 文件写入额外要求：
* 写前必须备份到 `state/archive/<YYYY-MM-DD>/<file>.<HHMMSS>.json`
* 失败可回滚

---

## 6. 跨平台路径

* 项目根：`C:/Users/31702/Desktop/Trading-System/`
* 桌面：`C:/Users/31702/Desktop/`
* 用正斜杠 `/`（Windows 也支持），避免反斜杠转义陷阱

---

## 7. 文件大小规范

| 类型 | 大小上限 | 超出处理 |
|---|---|---|
| 单个 .md 报告 | 50 KB | 拆分子文件 |
| 单个 .json 数据 | 200 KB | 拆分按日期 |
| 截图 .png | 5 MB | 压缩到 jpeg |
| 桌面合并 .txt | 100 KB | 警告但不阻塞 |

---

## 8. 报告生命周期

| 阶段 | 动作 |
|---|---|
| 当日 | 在 outputs/ 与桌面 |
| 7 日后 | session_orchestrator daily reset 时不动 |
| 30 日后 | review_agent 月报后归档到 `outputs/archive/<YYYY-MM>/` |
| 90 日后 | 归档目录压缩 ZIP，保留索引 |

---

## 9. 禁止行为

* 禁止 agent 之间互写文件（每个文件有唯一责任 agent）
* 禁止跨日修改已生成报告（错就标"修订版"另存）
* 禁止删除 outputs/ 或 reviews/ 历史文件
* 禁止文件名含空格、特殊字符（限 ASCII 字母数字 + `_` + `-` + `.`）
* 禁止用 emoji 文件名

---

## 10. 校验清单

每次写入后 session_orchestrator 必须 verify：

```
□ 文件存在
□ 字节数 > 0
□ UTF-8 解码无错
□ Markdown：含 H1 标题
□ JSON：parse 成功
□ 必含字段全部出现
□ 路径符合本规范
□ 时间戳格式 ISO 8601
□ 词汇白名单内
```

任一失败 → 写 `outputs/<today>_session_errors.json` 记录，session_orchestrator 标 ERROR 中止链。
