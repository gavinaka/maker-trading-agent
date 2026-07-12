# BlockBeats 新闻规则

# 数据源
https://www.theblockbeats.info/newsflash

---

# 核心用途
用于：
- 加密行业重大新闻
- 宏观突发事件
- 政策消息
- 市场情绪变化

---

# 内部优先级：政治 > 行业资讯（2026-05-31 用户拍板）
- **Tier 1 政治/宏观**（主导）：地缘（战争/制裁/外交/选举）、货币政策（升降息/FOMC/美联储/流动性）、监管立法（SEC/政策/法案/ETF 批准拒绝）。
- **Tier 2 行业资讯**（确认/微调）：ETF 资金流、交易所、链上/DeFi、鲸鱼、项目技术、机构持仓。
- 合成基本面方向时 **Tier 1 主导，Tier 2 不得翻转 Tier 1 方向**；以本文件和 `scoring/scoring_contract.json` 为当前权威，历史 Agent 文档不得覆盖。
- 该基本面方向主要服务**中线（基本面>盘面>盘口）**；对**日内 Maker（盘口>盘面>基本面）**仅作风险否决/降频。

## 机械排序优先级：分桶先于关键词加分（2026-07-06 午报起）

采集器必须先判断事件与 BTC 交易系统的直接相关性，再打分。排序顺序为：

1. `macro_policy`：Fed/FOMC/利率/CPI/PCE/非农/美元指数或美元走势/美债等直接宏观政策，或宏观语境中的流动性变化。
2. `regulatory_policy`：SEC/CFTC/ETF 批准拒绝/数字资产政策/稳定币法案等加密监管事件。
3. `btc_etf_flow`：BTC 现货 ETF、IBIT/GBTC/FBTC/ARKB、Farside、BTC 资金净流入/净流出。
4. `crypto_market_structure`：BTC/ETH/链上/清算/供应/行情结构等会影响盘面解释的加密市场结构。
5. `exchange_security_whale`：交易所、安全、黑客、链上鲸鱼等事件。
6. `eth_sector`：ETH 或项目技术事件。
7. `secondary_sector`：AI、美股、芯片、存储、电池等非 BTC 二级行业叙事。
8. `meme_other`：Meme 或其他弱 BTC 相关内容。

关键约束：
- `流动性`只有和 Fed/FOMC/美元指数或美元走势/美债/央行/利率/QT/QE/通胀等宏观语境共现时，才能进入宏观政策桶；单纯“万美元/亿美元”金额单位不得触发宏观桶。
- `需求`不能单独触发 ETF/资金流加分；必须与 BTC ETF、IBIT、GBTC、Farside、净流入/净流出等共现。
- Meme、个人投资复盘、AI/存储/芯片等非 BTC 叙事可以保留在 `candidate_rows`，但没有 BTC/ETF/宏观/监管直接语境时，不能挤进 top3。
- `analysis_priority` 必须保留 `tier/category/score/reasons` 兼容字段，并新增 `priority_bucket/bucket_rank/directness/directness_label` 供审计。

---

# 硬性规则

## 必须截图
新闻必须使用截图。
禁止：
- 文字替代截图
- AI总结替代截图
- 编造新闻
- 历史新闻替代实时新闻

---

# 时间规则
仅允许抓取前 12 小时内的实时重要快讯。
禁止：
- 12 小时窗口之外的新闻
- 历史旧闻
- 非实时内容

---

# 输出规则
新闻部分必须包含：
- 时间
- 标题
- 截图
- 12 小时候选池筛选出的 top3 依据

---

# 数据异常处理
如果：
- 网站无法访问
- 页面加载失败
- 无法截图
- 权限不足

必须输出“BlockBeats数据待补充”。
禁止继续生成新闻模块。

---

# Agent限制
Agent 不得：
- 总结新闻立场
- 主观分析新闻
- 放大情绪
- 猜测市场影响

仅允许客观记录。

---

# 核心原则
新闻是辅助信息，不能高于评分系统。

---

# 风险规则
重大新闻出现时，必须重新评估：
- 盘口结构
- 波动率
- 流动性风险

必要时强制观望。
