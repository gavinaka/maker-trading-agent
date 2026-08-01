---
name: browser-capture-toolset
description: "tools/browser_capture 浏览器自动化采集六源证据(一条命令跑齐),含登录/profile/对齐口径与坑"
metadata:
  node_type: memory
  type: project
  originSessionId: 6eb115b3-6948-4361-bafc-243c52400826
---

2026-06-20 建成、2026-06-28 扩为**五源自动截图工具集**，2026-07-05 扩为**六源证据采集工具集**:`tools/browser_capture/`(Node+Playwright,走系统真实 Chrome/Edge channel)。目的=替代用户手动给核心源截图/结构化证据；①BlockBeats 已改由 `capture_blockbeats.js` 统一采集，禁止再走 blockbeats-fetch/Claude-in-Chrome。

**一条命令**：先 `py runtime/session_runner.py begin-session --date <date> --slot <slot>` 取得 lease token；早报跑 `node tools/browser_capture/capture_all.js --slot morning --lease-token <token>`，午/晚跑 `node tools/browser_capture/capture_delta.js --slot midday|evening --lease-token <token>`。六源固定顺序为 BlockBeats → Coinglass → Exocharts → FedWatch → Farside BTC ETF Flow → TradingView 四档，全部落 `data_sources/inbox/<当天YYYY-MM-DD>/`；旧 `npm run all/delta` 无租约快捷入口只作历史别名，不用于正式日报。

**各源产物+对齐口径(对齐用户手工基准·已逐张验收)**:
- Coinglass `coinglass.png` 2560×1440:Bybit_BTCUSDT 主图、**1H**、删掉默认6面板里的3个(成交量Volume/聚合现货CVD/聚合合约订单**薄**深度差值——注意CG错别字"薄"非"簿",删除靠 blob iframe 内 `legend-source-item`+派发mouse事件)、裁掉右侧自选表→全宽4面板(价/CVD/资金费率/持仓OI)。公开免登录。
- Exocharts `exocharts.png` 2560×1440：每轮最开始必须先选择 `Bybit BTCUSD`，随后精确确认 `D`、`Tick 120`、`Bid-Ask Profile`、`Imbalance`、`Candle None`、`FPBS`、`vWap` 八项配置；任一项不确定即该源无效，禁止把默认 BitMEX 或相似控件当成正确状态。**需登录**。
- FedWatch `fedwatch.png` 原生 **1425×1001**（固定布局工具不强拉2560）：每轮重新导航 CME Group 官方页面并等待 quikstrike iframe（`iframe[id^=cmeIframe-]`）中的真实 FedWatch Tool 完整渲染，再截会议信息、概率表、柱状图及 NOW/1天/1周/1月。页面显示的 `Data as of ... CT` 只是转录元数据，禁止与主机 UTC／北京时间／文件时间比较并据此判定未来、陈旧、重采或硬停。公开；cookie 只拒绝不接受。
- Farside BTC ETF Flow `farside_btc_etf.png` + `farside_btc_etf.json`: `https://farside.co.uk/btc/` 的 Bitcoin ETF Flow (US$m) 表格。JSON 解析最新日度 Total、方向(inflow/outflow/flat)、前一日、最近5日净流，作为 BTC 现货 ETF 流入/流出与价格方向一致性的策略辅助确认源。公开免登录；文件必须当日重新采集，表格最新行可停留在最近一个美股交易日。
- TradingView **每周期 2 张共 8 张**：①`tradingview_btc_{1d,4h,1h,15m}.png` 为 1D/4H/1H/15m 结构图（道氏结构、SMA20、手绘支撑压力与通道）；②`tradingview_btc_{tf}_liq.png` 保留旧文件名，但当前语义是**候选摆动高低 + 用户手绘成交量分布区域特写**。平台内置 VRVP 必须在采集时隐藏且永不取值，禁止自动 POC/VAH/VAL/HVN/LVN 单点进入证据、评分、报告或 Maker 挂价。2560×1440，使用持久化登录态。
- 🟥 **`_liq` 读图纪律**：只读取用户手绘区域的阿拉伯数字 `lower_bound–upper_bound`、周期与明确标注的 `value_area/poc_zone/hvn_zone/lvn_zone` 角色；普通支撑/压力线不得冒充 profile。平台状态只有被可靠确认隐藏或不存在时，手绘区域才可标 `readable`；区域不可读、平台仍可见或状态未知时必须 `status=insufficient`、`zones=[]`、原因必填、`chart.liquidity_hunt=0`。此时 TradingView 四周期结构仍有效，Coinglass 清算热力图保持 `neutral`，不得替代 profile、生成概率落点或翻方向。

**登录机制(关键·绕Google反自动化)**:TradingView 与 Exocharts 共用独立目录 `~/.tv_chrome_profile`。Google OAuth 在自动化浏览器里被拦,且 Chrome136+ 禁默认配置目录开调试、复制配置又被App-Bound加密破坏→正解=**用普通 Chrome(非自动化)以 `--user-data-dir=该目录` 启动让用户手动登一次**(就地登录cookie可解密),之后 Playwright 用 `channel:'chrome'` 复用。掉登录就重登一次。

**坑/前置**:①GUI 必须前台+**关闭沙箱**运行(`dangerouslyDisableSandbox`);后台或带沙箱会 `spawn UNKNOWN`。②完整 Chromium 缺 VC++ 运行库报 SxS→改用系统 chrome/edge channel 规避。③采集时这些独立 profile 的 Chrome 窗口必须关闭(独占锁),不影响用户日常 Chrome(默认配置)。④裁图测距的细长条(_calib/_verify)别留 inbox,用户会当"畸形"。⑤跨午夜会落不同日期目录。

**自动清理(2026-06-20 用户加；2026-07-06 扩为交付后自动保留期清理)**:`cleanup.js`(=`npm run cleanup`)只负责采集前轻清理——`data_sources/inbox/<日期>/`(核心源截图/JSON + 辅助热力图) + `outputs/blockbeats/<日期>_*.png`(基本面快讯卡)，**只删"日期<cutoff"、保留最近 `CLEANUP_KEEP_DAYS` 天(默认2=今天+昨天·防跨午夜/晚间复用)、绝不碰当天在用图**。已挂进 `capture_all.js`/`capture_delta.js` 开头，两处目录均 gitignore 不进库。报告交付后重物料清理由 `session_runner.py deliver` 自动触发 `runtime/report_retention.py` 执行：`REPORT_RETENTION_KEEP_DAYS` 默认2天，写入 `runtime_state/<日期>/retention_cleanup_<slot>.json`；长期只保留本地 Word 底稿、Notion 页面、delivery/lease/automation 最小状态和 `context_log.md`，清理过期六源截图、combined 草稿、HTML 审查报告、执行中间 JSON、Word-QA 图片/PDF、publish attempts、一次性 `_*.py` 等可再生产物。`--skip-retention-cleanup` 只用于明确排障。

**辅助源·清算热力图(2026-06-21 用户加)**:`capture_liqheatmap.js`(已挂进 capture_all 末尾)→ `liqheatmap_{3d|48h|24h}.png`。Coinglass 清算热力图(URL `.../pro/futures/LiquidationHeatMap?coin=BTC`)·Binance BTC/USDT 永续·阈值固定0.85·黄=最强磁吸(上方带=空头流动性/下方带=多头流动性)。**周期规则:周末(六/日)抓3天·周一至五抓48H+24H**(脚本按 `getDay()` 自动切)。🟥**定位=只辅助印证可读的用户手绘成交量分布所给位置/概率；Farside BTC ETF Flow 是六个核心源之一，清算热力图不是新增核心源；手绘 profile 不足时热力图必须 `neutral`，不得替代、加分或翻向；热力图失败只 WARN 不硬停六源**。用 `~/.tv_chrome_profile`(与 TradingView/Exocharts 同一登录目录·Coinglass Prime 已于 2026-06-21 登录)。读法权威=`scoring/chart_methodology.md §九`D·见 [[liquidity-hunt-logic]]。

🟩**状态(2026-07-05 用户补充·已并入日报工作流)**:出**任何报告前先跑** `node tools/browser_capture/capture_all.js` 或带 slot/lease 的 `capture_delta.js` 抓齐六源；①BlockBeats 由 `capture_blockbeats.js` 勾选「重要快讯」，并按 2026-07-04 规则覆盖抓取前 12 小时候选池后筛 top3；⑤Farside BTC ETF Flow 由 `capture_farside_btc_etf.js` 输出截图+JSON，用于判定 BTC 现货 ETF 流与价格方向是否一致。已写进 `sessions/日报SOP.md §0.0+§1` 与 `.agents/skills/daily-report/SKILL.md`。🟥**采集后必过验证门**:Read/校验每个源确认真实有效(非登录墙/空图/陈旧/默认symbol/无效JSON),任一源失败=该源缺失=按 [[five-sources-complete-or-halt]](旧名兼容) **硬停**(重登或回退该源用户手动截图/结构化数据),绝不拿无效图或推测数据当数据读。判读口径全不变(只换"图从哪来")。见 [[daily-workflow-order]]。
