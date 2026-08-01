# Exocharts Collector SOP

> 🟥 **源角色（宪法级）**：Exocharts 不是盘口四维主源。价格 / CVD / OI / 资金费率的主判来自 Coinglass；Exocharts 只提供日线足迹与主动成交的细颗粒印证。两源冲突时必须复核，Exocharts 不得单方覆盖主判、翻转方向或制造极端评分。

## 当前自动化目标

- 页面：`https://exocharts.com/web/`
- 产物：`data_sources/inbox/<YYYY-MM-DD>/exocharts.png`
- 唯一合格配置：`Bybit BTCUSD / D / Tick 120 / Bid-Ask Profile / Imbalance / Candle None / FPBS / vWap`
- 配置顺序先确认 `Bybit BTCUSD`，再设置其余控件；禁止继承旧 symbol、选择页面中的“第一个 BTCUSD”或用其它交易所的同名合约代替。
- `D` 是 Exocharts 的固定日线足迹基线；它只与 Coinglass 的同一 BTC 盘口主判做跨源强弱印证，不冒充 Coinglass 的 1H 同 pivot 四维主判。

## 通道约束

- 主通道：**A**（已登录的独立 Chrome profile + Playwright）。Exocharts 是 SPA，WebFetch 不可用。
- 兜底：**C**（用户提供当前截图／结构化转录）。
- 禁止：**B**。
- 不自动登录、不读取或导出 cookie、localStorage、sessionStorage、token、密码或账户信息。

## 通道 A 状态机

1. 导航到官方页面，等待以下任一真实条件出现，而不是固定睡眠：
   - 唯一可见的图表配置控件就绪；或
   - 唯一可见的 `plan does not allow more LIVE connections` 阻断提示。
2. 若出现 LIVE 阻断，只允许点击阻断区域内唯一、可见、精确匹配的接管动作；禁止固定坐标、隐藏重复节点或 `.first()` 猜选。接管后必须等到阻断消失且配置控件真实就绪。
3. 每个控件均按“读取当前状态 → 必要时执行一次动作 → 回读确认”处理。第一次未确认时只允许 **1 次同控件局部纠正**；仍未确认即失败。不得刷新整页、重启整轮或无限点击。
4. 逐项机械确认：
   - symbol：`Bybit: BTCUSD`；
   - timeframe：`D`（菜单项 `Daily`）；
   - tick multiplier：`120`；
   - cluster：`Bid-Ask Profile`；
   - text：`Imbalance`；
   - candle：`None`；
   - toggle：`FPBS` 与 `vWap` 均为 active。
5. toggle 先读取 `aria-*` / `data-*` / active class 等显式状态，再读取可见样式。不能再用“RGB 三通道均大于等于 200”作为唯一依据，因为高亮的黄色 `vWap` 也属于 active。
6. 等主图 canvas 就绪，把光标移到最新 K 线区域；再次回读全部配置、LIVE 阻断和 24h delayed 状态。全部成立后才写 `exocharts.png`。

## 去敏失败诊断

vNext 由 controller 将诊断目录绑定到当前 `evidence/attempt-NNN/exocharts/`；collector 不接受任意仓外目录。失败时尽最大努力生成：

- `exocharts_diagnostic.png`：当前页面截图，输入框和常见 account/profile/user 元素遮罩；
- `exocharts_diagnostic.json`：只含安全故障枚举、控件状态分类（`expected / unexpected / missing_or_ambiguous / active / inactive / unknown`）、动作次数、局部纠正次数和隐私布尔声明；
- `exocharts_result.json`：只含 `passed / failed`、安全 `capture.exocharts.*` leaf code 和诊断是否存在。

诊断 JSON 与 result 禁止包含自由文本异常、DOM 正文、价格、方向、评分、仓位、cookie、浏览器存储、token 或绝对敏感数据。vNext controller 只接受当前 capture manifest 中经过 run/date/slot/capture-id 绑定且匹配 `capture.exocharts.*` allowlist 的 leaf code；其它内容统一降为 `capture.failed`，不得进入 `sample_outcome.json`。

## 失败与预算

- 登录态／页面未就绪：该源无效，等待人工处理；不得伪造截图。
- LIVE 接管动作缺失或接管后仍阻断：该源无效。
- 任一固定配置两次动作后仍无法机械确认：该源无效，并使用对应安全 leaf code（如 `symbol_unconfirmed`、`vwap_unconfirmed`）。
- 24h delayed：该源无效。
- 单个控件的局部纠正不增加 Evidence 阶段总预算。Evidence 仍只有 **2 次完整采集 attempt**；第二次失败进入人工复核，不得扩门、加第三次或重跑其它业务阶段。

## 足迹转录边界

- 仅在截图中逐价位足迹真实可读时转录吸收、失衡、POC、OHLC、Delta、CVD、Volume。
- 足迹档位不可见／不确定时，`footprint_signals` 整块为 `null`，禁止猜测。
- `absorption`、`imbalance` 与 POC 只作强弱印证；缺失时降低该维度置信度，不允许由 Exocharts 单独翻向。
- 与 Coinglass 结果冲突时保留冲突并进入反证链，不允许为了报告一致而抹平差异。
