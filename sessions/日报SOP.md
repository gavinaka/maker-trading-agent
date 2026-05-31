# 日报执行 SOP（确定性流程 · 照此走不试错）

> 目的：减少踩坑、省 token。每条都是已验证的「唯一正确路径」，不要再探索替代方案。
> 维护：发现新坑或路径变化时更新本文件 + 对应 memory。

---

## 0. 开场（每次会话固定）
1. 读 `sessions/context_log.md` 顶部最近日期块 + `memory/MEMORY.md`。
2. 确认今天出早间(链A)还是晚间(链B)。
3. 一次性 `ToolSearch` 把要用的工具 schema 拉齐（Notion REST 不需要工具；浏览器需要 select_browser / tabs_context_mcp / tabs_create_mcp / navigate / get_page_text）。

---

## 1. 五源数据采集（唯一路径，按源对号入座）

### ① BlockBeats（基本面）— Chrome 浏览器扩展
**固定 6 步，不要并行、不要猜 ID：**
1. `list_connected_browsers` —— **只调 1 次**。
2. 若返回 `[]` → 请用户点一下 Chrome 里 Claude 扩展图标，等用户回复后再调 1 次。
3. `select_browser`(用上一步返回的**真实 deviceId**，不要瞎编)。
4. `tabs_context_mcp` `{createIfEmpty:true}` —— 建/取 tab group。
5. `tabs_create_mcp` —— 拿到**自己的 tabId**，记住它。
6. `navigate` 到 `https://www.theblockbeats.info/newsflash` → `get_page_text`(传第5步 tabId)。
- 抓完 `tabs_close_mcp` 关掉自己的 tab。
- ⚠️ 不要对 BlockBeats 以外的域名 navigate（exocharts/coinglass/cme 会被扩展或安全策略拒）。

### ②③④⑤ Exocharts / Coinglass / FedWatch / TradingView — **用户截图**
- 这四源一律等用户贴图，**不要尝试 navigate**（已知被拒，纯浪费）。
- ② Exocharts：BTCUSD 日线 footprint → 读 POC / Delta / CVD / 日波幅。
- ③ Coinglass：BTCUSDT 1h → 读 CVD / 价格 / 资金费率 / OI。
- ④ FedWatch：下次 FOMC 概率表 + 1日/1周/1月变化。
- ⑤ TradingView：**15m**（盘面执行最终 Check，入场把关）。若用户给 4H 先用着，但提醒补 15m。

---

## 2. Notion 读取（持仓校准）— REST API only

- **永远走 REST API，永远用 PowerShell `Invoke-RestMethod`。**
  - ❌ 不调 `mcp__...__notion-*`（连接器一直 403，已弃用）。
  - ❌ 不用 `python3`/`python`（本机是 Windows 商店 stub，curl|python3 静默返回空）。
- **令牌唯一**：`***REMOVED***`（用户确认从未更新；对话里出现的其它串忽略；除非报 401 才换）。
- **header**：`@{ "Authorization"="Bearer $tok"; "Notion-Version"="2022-06-28"; "Content-Type"="application/json" }`
- **持仓在两库**（取最新一条，按 created_time desc）：
  - （主）交易Check：`212fda35-a098-809f-bb92-c681fad1b12f`
  - （Maker）交易Check：`21bfda35-a098-8062-a0a5-c7cb3f3e1f34`
- **只取需要的字段**，不要 dump 整页原始 JSON（rich_text 注解极占 token）：
  - 状态 / 交易策略 / 持仓量 / 杠杆 / 盈亏比 / 计划起始时间
  - 描述（复盘）= 均价·TP·SL / 浮盈防守计划
- 逐日手写判断（对照用）在主账户 plan page 汇总库；中文 filter body 需 UTF-8 字节，否则 400——能不发 filter 就 `page_size` 取回本地筛。

---

## 3. 评分（70+30）与出稿
- 盘口 70（footprint 16 组合；C01/C02 极端=自动70，其余手动）+ 盘面 30（接近度10/掠夺10/SMA20·5/量价3/斐波2）。
- 总分 ≥70 才允许 Maker 开仓，否则观望。
- **盘面分析只有两层：日线级别 + 小时级别**（Notion 固定格式，6 样本核实）。15m 只属于第⑤源「TradingView 盘面执行 Check」，不要写成「盘面·15m级别」。
- 出稿：python-docx（`py` 运行，字体 Microsoft YaHei）。正文按用户 Notion 手写格式（主账户段 + Maker 段在文首可直接复制），后附评分明细/五源支撑。
  - docx 被占用报 PermissionError → 换新文件名。
  - 生成后用一条命令确认文件存在即可，不要反复 Read/Glob 验证。

---

## 4. 省 token 纪律（本次踩坑总结）
1. **不并行重复调用**：一个动作发 1 次，看结果再决定下一步。禁止"先多发几个保险"。
2. **不发探针**：不要 `echo probe` / 重复 `list_connected_browsers` 试连接。
3. **已知会失败的不试**：MCP-notion、python3、对非 BlockBeats 域 navigate、瞎编 deviceId/tabId。
4. **不重复 Read** 同一文件；Edit/Write 成功即生效，不回读验证。
5. **读 Notion 抽字段，不 dump 全量 JSON**。
6. 临时中转文件（`sessions/_*.txt`）用完即删。

---

## 5. 收尾
- 写 `context_log.md`（倒序，新日期块在顶）。
- 更新 memory（若有新坑/决策）。
- ❌ 不 commit（用户不用 git）。
- 清临时文件。
