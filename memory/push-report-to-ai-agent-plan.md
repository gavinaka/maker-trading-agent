---
name: push-report-to-ai-agent-plan
description: 每天把生成的日报通过 Notion API 写入「AI agent（plan）」页面下的日期子页(2026.M.D)，按主账户 plan 格式；硬规则=只写这一个项目，其它项目只读。
metadata:
  node_type: memory
  type: project
  originSessionId: 1e944348-5206-449b-9064-15102b1469cd
---

用户 2026-06-02 新增需求：每天把系统生成的日报推送进 Notion 项目 **「AI agent（plan）」**。

- **目标页**：`AI agent（plan）` page_id = `373fda35-a098-80be-ae2f-ddfb06b3b075`（REST API 写入）。
- **结构**：在该页下新建**日期子页**，标题格式 `2026.M.D`(如 `2026.6.2`)。**日期子页下分子页(2026-06-02 拍板)**：`🌅 2026.M.D 早间日报（11:00 评分点）`、`🌙 2026.M.D 晚间日报（20:00 评分点）`、`🔍 2026.M.D 晚间独立审查（倒推）`(晚间专属，见 [[evening-review-visual-to-notion]])，各装当次完整 ①正文+②Maker(+基本面3图)。
  - 🟢 **优化(2026-06-02 收工·机制)：早间从一开始就直接建 🌅 子页写入，禁止再平铺到日期页**——这样晚间只需新增 🌙+🔍 子页，**永不发生"迁移早间+重传图"**(旧的先平铺再迁移=纯浪费，已废)。
  - 防重复：建前用 `find_child_page(date_page, "🌅"/"🌙"/"🔍")`，已存在则 ABORT。
- **内容格式**：按**主账户 plan**(`交易Plan 主账户` page `21bfda35-a098-8025-a61e-e474bafe172b`)的子页格式——H2`不能做` → H3`基本面` → H3`技术面`/盘口段落 → H3`解读` → 盘面段落 → H3`趋势确认` → H3`日内支撑/压力` → H3`策略`；之后 divider + H2`Maker 计划`。即把日报 ①正文 套主账户标题块、②Maker 计划附后。对齐见 [[report-template-alignment]]。
- **硬规则(用户强调)**：**只允许在「AI agent（plan）」内操作**，其它所有 Notion 项目**仅读取、绝不写**。写前先 GET 子页列表防重复(同名 `2026.M.D` 已存在则 ABORT)。

**⚡ 唯一推送路径(2026-06-02 深度优化·机制层)**：用**可复用库 `outputs/notion_push_lib.py`** + `py`(真 Python 3.14·自带 requests；`python3` 是 Windows stub 不可用)。每天的推送脚本只 `import notion_push_lib as n` 后**填 blocks 内容 + 调 `n.push_subpage(...)`/`n.create_page`**，plumbing 全在库里、不再每天重推导：
  - 库已封装：rich_text/各类 block 构造器(`rt/para/h2/h3/quote/callout/divider/table/trow/cell/image_block`)、`get_children/find_child_page/find_heading/ensure_date_page/create_page(自动分页>100)/upload_image(multipart 三步)/insert_images_after_heading/copy_block(迁移旧块·剥只读字段)/push_subpage(一站式建页+插图+去重)`。
  - **token 走 `$env:NOTION_TOKEN`(绝不硬编码进库/git)**；🟢 **双源(2026-06-10 加固)**：主源=User 级注册表环境变量 `[Environment]::GetEnvironmentVariable('NOTION_TOKEN','User')`(经用户授权已持久化·无人值守 cron 直读注册表不受父进程影响)，后备=`notion-positions` SKILL 火种行(🟥禁删)，两源皆失则显式 throw。图片 `image` 块用 `file_upload` id(本地 PNG 重传，S3 URL 会过期不能复用)。
  - 🟥 **写操作禁盲重试(2026-06-10 加固)**：`create_page`/`insert_images_after_heading` 失败后**先 GET 核实服务端实际落地状态**(`_find_exact_child_page` 查同名页 / 数块计数)再决定续用或重发——SSL EOF 多在响应阶段、请求可能已成功，盲重发会重复建页/重复插块(6/9 实际事故的防范对象)；插图函数幂等(页内图已齐则跳过，固化 6/9 守卫脚本)。GET 读取仍 3 次重试。
  - 🟥 **Python 字符串坑**：中文引号一律用全角「」，**禁用半角 `"`**(与定界符冲突→SyntaxError)。
  - 🟥 **控制台坑**：Windows PS 控制台 GBK 编码**打印 emoji/部分中文会报 UnicodeEncodeError**——脚本里别 `print` emoji(用 `json.dumps(...,ensure_ascii=True)` 或不打)，不影响 API 写入。
  - 参考实现：`outputs/_notion_push_0602_{morning,evening,review}.py`(date-hardcoded 示例)。

**写入技术要点(REST，token 见 [[../skills 中 notion-positions]])**：
- 创建子页：`POST /v1/pages`，`parent={page_id}`、`properties.title`、`children=[blocks]`；中文必须 `[Text.Encoding]::UTF8.GetBytes($json)` 发字节。
- **集成需具备写能力**：用户已在 Notion 集成 Capabilities 开启 Insert/Update content(原只读，2026-06-02 开通)。token 唯一值见 `notion-positions` skill；运行推送脚本时**临时** `$env:NOTION_TOKEN=<该值>`，勿写进任何入库文件。
- **PowerShell 坑**：① `$pid` 是保留变量、换名；② 调用自定义函数传多参用**空格**不要 `f("a",$true)`(后者会把 `,` 当成数组塞进第一个参数)；③ JSON 里字面 `$1000` 用反引号转义 `` `$1000 ``。

**配色/层级规则(对照用户两套模板，2026-06-02 用户要求对齐)**：
- 颜色语义：**红**=空头/压力/利空/止损/破位/禁令；**绿**=支撑/止盈/利多；**黄**=中线/中性/原因提示；**紫**=注意事项/取消价≠止损 等告警；默认=叙述。
- ①主账户段：`不能做`(H2，禁令词红粗) → `基本面`(H3，方向词红或绿粗·原因括号黄粗·价格兑现绿/红粗) → `技术面`(H3) → `盘口（合约）`(P默认)+盘口数据行(P加粗) → `解读`(H3，中性黄粗·破位卖压红粗) → `盘面`(P)+日线/小时(破位词与"利空"红粗) → `趋势确认`(H3，空头趋势红粗) → `日内支撑/压力`(H3整行加粗，支撑绿粗·压力红粗) → `策略`(H3)+中线段(黄粗整段)。
- ②Maker段：divider 后 `BTC（策略）：执行概率…胜率…`(H2默认不加粗) → 入场行(P加粗) → `止盈`(绿粗) → `止损`(红粗) → `防守计划`(H3) → 第一/二层(P加粗) → `注意事项`/`取消价≠止损`(紫粗) → 持仓校准(默认)。
- 技术坑(补)：Notion rich_text 每段可多 run 分别染色，`annotations={bold,color}`；重建页用"先 DELETE 旧子块再 PATCH children"保 URL 不变。

**基本面=图片格式(3张BlockBeats快讯卡，2026-06-02 用户要求)**：
- 来源固定：每天跑日报/晚报时由 `tools/browser_capture/capture_blockbeats.js` 打开 `https://www.theblockbeats.info/newsflash`，**必须读完抓取前 12 小时内全部「重要快讯」**(滚动+点「查看更多」跨调用异步加载，直到覆盖 12 小时窗口；用户强调「取3条不是少读、要读全再按优先级筛」)，再**按市场影响优先级严格筛 3 条**(不多不少)。政治/宏观/监管 Tier1 > ETF/资金流/机构持仓 > 交易所/链上安全/鲸鱼 > 项目技术/Meme/其他。最终只制卡和分析这 3 条，但 `blockbeats.json` 必须保留 12 小时候选池。
- 出图：Chrome MCP 的 `computer screenshot/zoom(save_to_disk)` **拿不到落盘字节**(本地搜不到、MCP 不回显路径)——放弃截原图。改为**本地渲染暗色卡片**：PowerShell `System.Drawing` + 微软雅黑，每条卡含「BLOCKBEATS 快讯」蓝标+标题(粗)+`BlockBeats · 日期时间`+正文(自动换行)，存 `outputs\blockbeats\`。正文逐条从 `/flash/{id}` 单页 `get_page_text` 取全(列表项 `a.news-flash-title` 的 href=/flash/{id})。
- 入库：Notion 文件上传 3 步 = `POST /v1/file_uploads`→`POST {upload_url}/send`(PS5.1 手搓 multipart：field name `file`、Content-Type image/png、boundary)→拿 file_upload id；再 `PATCH /blocks/{page}/children` 用 `{children:[image块], after:基本面heading_id}` **插到基本面标题之后**(image 块 = `{type:image,image:{type:file_upload,file_upload:{id}}}`；`after` 参数 2022-06-28 版可用、已验证生效)。

**Why**：用户授予了 AI agent（plan）的编辑权限做日报自动归档，但其余项目是他的真实交易台账，误写会污染。
**How to apply**：每天出完日报后，按上述格式建当天 `2026.M.D` 子页写入；只碰这一个页面。
