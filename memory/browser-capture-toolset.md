---
name: browser-capture-toolset
description: "tools/browser_capture 浏览器自动化采集六源证据(一条命令跑齐),含登录/profile/对齐口径与坑"
metadata:
  node_type: memory
  type: project
  originSessionId: 6eb115b3-6948-4361-bafc-243c52400826
---

2026-06-20 建成、2026-06-28 扩为**五源自动截图工具集**，2026-07-05 扩为**六源证据采集工具集**:`tools/browser_capture/`(Node+Playwright,走系统真实 Chrome/Edge channel)。目的=替代用户手动给核心源截图/结构化证据；①BlockBeats 已改由 `capture_blockbeats.js` 统一采集，禁止再走 blockbeats-fetch/Claude-in-Chrome。

**一条命令**:`node tools/browser_capture/capture_all.js`(=`npm run all`)→ 顺序跑 BlockBeats→Coinglass→Exo→CME→Farside BTC ETF Flow→TV四档,全部落 `data_sources/inbox/<当天YYYY-MM-DD>/`;单源:`npm run blockbeats/coinglass/exo/fedwatch/farside/tv`。

**各源产物+对齐口径(对齐用户手工基准·已逐张验收)**:
- Coinglass `coinglass.png` 2560×1440:Bybit_BTCUSDT 主图、**1H**、删掉默认6面板里的3个(成交量Volume/聚合现货CVD/聚合合约订单**薄**深度差值——注意CG错别字"薄"非"簿",删除靠 blob iframe 内 `legend-source-item`+派发mouse事件)、裁掉右侧自选表→全宽4面板(价/CVD/资金费率/持仓OI)。公开免登录。
- Exo `exocharts.png` 2560×1440:Bybit BTCUSD·D·Tick×120·Bid-Ask Profile·FPBS(底部Footprint统计)·**vWap**(黄线·易漏)·关Trial弹窗。**需登录**。
- CME `fedwatch.png` 原生 **1425×1001**(用户选A保持原生·固定布局工具不强拉2560):截 cmegroup 页内 quikstrike iframe(`iframe[id^=cmeIframe-]`)=真实 FedWatch Tool 控件(会议信息+概率表+柱状图+NOW/1天/1周/1月)。公开;cookie 只拒绝不接受。
- Farside `farside_btc_etf.png` + `farside_btc_etf.json`: `https://farside.co.uk/btc/` 的 Bitcoin ETF Flow (US$m) 表格。JSON 解析最新日度 Total、方向(inflow/outflow/flat)、前一日、最近5日净流，作为 BTC 现货 ETF 流入/流出与价格方向一致性的策略辅助确认源。公开免登录；文件必须当日重新采集，表格最新行可停留在最近一个美股交易日。
- TV **每周期2张共8张**(2026-06-21 用户加·读流动性猎杀):①`tradingview_btc_{1d,4h,1h,15m}.png`=结构图(趋势/道氏/SMA20·原固定zoom 1D=17步≈2月/4H=15≈15天/1H=9≈7天/15m=15≈1天内)；②`tradingview_btc_{tf}_liq.png`=**高低点+VRVP特写**(结构图后再追加放大 zoomExtra=8/7/6/7步·把各周期摆动高/低=候选猎杀位+POC/VAH/VAL放大到精确可读)。2560×1440·登录态(带手绘线/VRVP/SMA/通道)。**规整=切周期→`Alt+R`重置→折叠右侧自选表→贴右侧(光标x≈2100)滚轮放大**。✅ **zoomExtra 8/7/6/7 已实跑核对锁定(2026-06-21晚)**:裁剪右侧VRVP直方图+价格轴区后 VRVP/POC/VAH/VAL 节点价精确可读(15m紧凑±3000点最佳/1h~1周/1d·4h宽覆盖完整价值区符合高周期看全局HVN-LVN用途);🟥勿盲目加大(15m已紧凑·再大=只剩几根K致POC失真)勿减小(高周期需看全价值区)。**需登录**。
- 🟥🟥 **`_liq` 读图纪律(2026-06-21晚加固·核验三更新执行后发现:`_liq` 抓了却没被用作 §九步②主判源·我用主图读SMA、`_liq` 只glance)**：4张 `_liq` 特写**必须像读SMA轴标那样裁剪放大读**(PIL `im.crop((int(W*0.58),0,W,H)).resize(...)` 取右侧VRVP+价格轴·+各周期最近摆动高低区)·读出 VRVP/POC/VAH/VAL 精确节点价+HVN/LVN厚薄+各周期摆动高低候选猎杀位·写③后附做主判；🟥**禁拿 Read 直读的缩略图当"读过 `_liq`"**(缩略图节点价读不准·会退化成用主图读SMA·`_liq`形同没抓)。抓取到位·缺口只在"有没有裁剪读"。配 [[liquidity-hunt-logic]] 的 report_lint「盘面五步·VRVP主判门」(WARN·管写没写主判)双管(本纪律管读没读 `_liq`)·写进 daily-report SKILL §1⑤。

**登录机制(关键·绕Google反自动化)**:TV+Exo 共用独立目录 `~/.tv_chrome_profile`。Google OAuth 在自动化浏览器里被拦,且 Chrome136+ 禁默认配置目录开调试、复制配置又被App-Bound加密破坏→正解=**用普通 Chrome(非自动化)以 `--user-data-dir=该目录` 启动让用户手动登一次**(就地登录cookie可解密),之后 Playwright 用 `channel:'chrome'` 复用。掉登录就重登一次。

**坑/前置**:①GUI 必须前台+**关闭沙箱**运行(`dangerouslyDisableSandbox`);后台或带沙箱会 `spawn UNKNOWN`。②完整 Chromium 缺 VC++ 运行库报 SxS→改用系统 chrome/edge channel 规避。③采集时这些独立 profile 的 Chrome 窗口必须关闭(独占锁),不影响用户日常 Chrome(默认配置)。④裁图测距的细长条(_calib/_verify)别留 inbox,用户会当"畸形"。⑤跨午夜会落不同日期目录。

**自动清理(2026-06-20 用户加)**:`cleanup.js`(=`npm run cleanup`)删过期动态图——`data_sources/inbox/<日期>/`(核心源截图/JSON + 辅助热力图) + `outputs/blockbeats/<日期>_*.png`(基本面快讯卡),**只删"日期<cutoff"、保留最近 `CLEANUP_KEEP_DAYS` 天(默认2=今天+昨天·防跨午夜/晚间复用)、绝不碰当天在用图**。已挂进 capture_all 开头(每次采集前先清),两处目录均 gitignore 不进库。读完/推完 Notion 即无保留价值。

**辅助源·清算热力图(2026-06-21 用户加)**:`capture_liqheatmap.js`(已挂进 capture_all 末尾)→ `liqheatmap_{3d|48h|24h}.png`。Coinglass 清算热力图(URL `.../pro/futures/LiquidationHeatMap?coin=BTC`)·Binance BTC/USDT 永续·阈值固定0.85·黄=最强磁吸(上方带=空头流动性/下方带=多头流动性)。**周期规则:周末(六/日)抓3天·周一至五抓48H+24H**(脚本按 `getDay()` 自动切)。🟥**定位=辅助印证流动性猎杀概率；Farside 才是第六个核心源；热力图失败只 WARN 不硬停六源**。用 `~/.tv_chrome_profile`(与TV/Exo同一登录目录·Coinglass Prime 已于 2026-06-21 登录)。✅**已实跑验证(2026-06-21)**:登录通过·周期自动选对(周日→3天)·截图门修复(canvas 仅绘图区→须扩边纳入右侧价格轴/时间轴/左强度色阶·否则读不到磁吸带精确价位)。读法权威=`scoring/chart_methodology.md §九`D·见 [[liquidity-hunt-logic]]。

🟩**状态(2026-07-05 用户补充·已并入日报工作流)**:出**任何报告前先跑** `node tools/browser_capture/capture_all.js` 或带 slot/lease 的 `capture_delta.js` 抓齐六源；①BlockBeats 由 `capture_blockbeats.js` 勾选「重要快讯」，并按 2026-07-04 规则覆盖抓取前 12 小时候选池后筛 top3；②Farside 由 `capture_farside_btc_etf.js` 输出截图+JSON，用于判定 BTC 现货 ETF 流与价格方向是否一致。已写进 `sessions/日报SOP.md §0.0+§1` 与 `.agents/skills/daily-report/SKILL.md`。🟥**采集后必过验证门**:Read/校验每个源确认真实有效(非登录墙/空图/陈旧/默认symbol/无效JSON),任一源失败=该源缺失=按 [[five-sources-complete-or-halt]](旧名兼容) **硬停**(重登或回退该源用户手动截图/结构化数据),绝不拿无效图或推测数据当数据读。判读口径全不变(只换"图从哪来")。见 [[daily-workflow-order]]。
