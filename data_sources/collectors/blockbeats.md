# BlockBeats Collector SOP

## 目标
采集当日加密行业重大新闻 → 写入 `inbox/<YYYY-MM-DD>/blockbeats_NNN.{png,txt}` + manifest

## 数据源
https://www.theblockbeats.info/newsflash

## 通道约束（硬性）
* 允许通道：**A**（Chrome MCP 自动截图）或 **C**（用户手动投递）
* 禁止通道：**B**（WebFetch 文本拉取）
* 理由：`data_sources/source_rules.md` 规定"必须截图，禁止 AI 总结替代"

---

## 通道 A 执行流（Chrome MCP）

1. `tabs_create_mcp` 拿新 tabId（或复用本会话已有 tabId）
2. `navigate` → `https://www.theblockbeats.info/newsflash`
3. `read_page` filter=interactive，定位新闻流容器
4. 对当日（按发布时间过滤）每条 "重要" 标记的新闻：
   * 滚动到该条卡片完整可见
   * 调用浏览器截图能力，保存为 `blockbeats_<NNN>.png`（NNN 从 001 起按时间倒序）
   * `get_page_text` 抽取该条文本，写 `blockbeats_<NNN>.txt`（仅作辅助索引）
5. 重要标准（任一即可）：
   * 标题含监管 / FOMC / SEC / 大额清算 / 鲸鱼地址 / 交易所事故
   * BlockBeats 自身打 "重要" / "深度" 标签
   * 涉及 BTC、ETH 价格异动 ±2% 以上
6. 写入 manifest：
   ```json
   "blockbeats": {
     "captured_by": "A",
     "captured_at": "<ISO>",
     "files": ["blockbeats_001.png", "blockbeats_001.txt", ...],
     "screenshot_count": <N>,
     "valid": true,
     "raw_summary": {
       "important_count": <N>,
       "headlines": ["...", "..."]
     }
   }
   ```

---

## 通道 C 执行流（用户手动投递）

用户责任：

1. 当日访问 BlockBeats
2. 对每条重要新闻截图
3. 命名：`blockbeats_001.png` / `blockbeats_002.png` ...
4. 配套 .txt 可选（写头条文字）
5. 放入 `data_sources/inbox/<YYYY-MM-DD>/`
6. 通知 Claude "BlockBeats 已投递" → Claude 扫描目录，写 manifest 条目（`captured_by: "C"`）

---

## 失败处理

* 站点 403/404 / 加载超时 → 标 `valid:false`, `error:"<原因>"`
* `screenshot_count = 0` → 视同失败
* news_agent 启动时会拒收 `captured_by != A && captured_by != C` 的记录

---

## 注意

* 严禁用 `get_page_text` 输出替代截图（违反宪法）
* 严禁基于历史新闻或 AI 推理生成"今日新闻"
* 如当日确无重要新闻，写 `screenshot_count: 0, valid: true, raw_summary.note: "今日无重要新闻"` —— 这是合法状态
