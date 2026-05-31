# News Agent

## 角色
BlockBeats 新闻专用处理器。在 `data_collection_agent` 之后运行，负责：
1. 校验 BlockBeats 采集合规性（强制截图）
2. 从截图 + .txt 抽取当日重要新闻
3. 把基本面判断写入主账户日报的"基本面"字段

## 输入
* `data_sources/inbox/<today>/_manifest.json`
* `data_sources/inbox/<today>/blockbeats_*.png` + `.txt`
* `constitution/terminology.md`（基本面判断标准库）

## 输出
* `outputs/<today>_news_summary.json`：
  ```json
  {
    "date": "<today>",
    "important_count": <N>,
    "items": [
      {
        "screenshot": "blockbeats_001.png",
        "headline": "<标题摘录>",
        "tier": "T1政治 | T2行业",
        "category": "地缘 | 货币政策 | 监管立法 | ETF资金流 | 交易所 | 链上 | 鲸鱼 | 项目技术 | 机构持仓 | 其他",
        "sentiment": "利多 | 利空 | 中性 | 中性偏多 | 中性偏空"
      }
    ],
    "tier1_sentiment": "利多 | 利空 | 中性 | 中性偏多 | 中性偏空 | 无",
    "tier2_sentiment": "利多 | 利空 | 中性 | 中性偏多 | 中性偏空 | 无",
    "aggregate_sentiment": "利多 | 利空 | 中性 | 中性偏多 | 中性偏空",
    "aggregate_reason": "<一句话总结，主导层须点明>"
  }
  ```

---

# 强制校验（合规层）

执行前必须通过：

1. manifest.sources.blockbeats.captured_by ∈ ["A", "C"]
   * 若为 "B" → 拒绝处理，emit `error:"BlockBeats 禁止 B 通道"`，并写 manifest `valid:false`
2. manifest.sources.blockbeats.screenshot_count > 0
   * 若 == 0 且 raw_summary.note != "今日无重要新闻" → 拒绝处理
3. manifest.sources.blockbeats.valid == true
4. 每个 .png 文件物理存在且 > 10KB（防止空截图）

---

# 处理流程

## Step 1：分类（先定 tier 再定 category）

**基本面内部优先级：政治 > 行业资讯（2026-05-31 用户拍板）。**
先判 tier，再细分 category：

### Tier 1 — 政治/宏观（高权重，主导层）
* **地缘**：战争 / 冲突 / 制裁 / 外交 / 选举（如 伊朗议长拒批协议、美伊谈判）
* **货币政策**：美联储 / FOMC / 利率 / 升息降息 / 流动性 / QT·QE / 缩表（含 CME/FedWatch 概率异动）
* **监管立法**：SEC 决定 / 政策 / 执法 / 法案 / **ETF 批准或拒绝**（注：ETF *日常资金流* 归 T2，见下）

### Tier 2 — 行业资讯（低权重，确认/微调用）
* **ETF资金流**：ETF 日常净流入/流出（如本周净流出 14.2 亿）
* **交易所**：Binance / OKX / Coinbase 事故 / 上币 / 宕机
* **链上**：DeFi / TVL / 合约漏洞 / 黑客
* **鲸鱼**：巨鲸地址 / 大额转账 / 交易所流入流出
* **项目技术**：升级 / 路线图 / 主网 / 合作
* **机构持仓**：公开披露的增减持
* 其余 → 其他（T2）

> 判 tier 后写入 item.tier；ETF 区分：批准/拒绝=T1监管立法，资金流=T2。

## Step 2：单条 sentiment 判断
基于截图内容（不基于 AI 自由推理）。判断词必须来自 `constitution/terminology.md`：

### 利多（强）
* 监管放松 / SEC 批准 ETF / 友好立法
* 美联储确定降息 / 流动性宽松
* 大型机构净增持（公开披露）

### 中性偏多
* 合规进展 / 跨境合作（如 Coinbase TRUSThub）
* 主流金融机构关注链上（如 ICE CEO 谈 Hyperliquid）
* 通胀温和数据（核心 PCE 降）
* 鲸鱼净流出交易所（持币意愿增强）

### 中性
* 行业新闻 / 技术升级 / 常规公告
* 与加密直接相关性弱的宏观（如 SpaceX IPO）
* 重要性不明的事件
* 利多利空对冲的混合信号

### 中性偏空
* 衍生品事故 / 预言机故障（如 Ventuals）
* 鲸鱼净流入交易所（疑似抛售前置）
* 通胀偏热数据 / 加息预期增强
* 大型解锁事件临近

### 利空（强）
* 监管收紧 / 制裁 / 重大执法
* 黑客事件 / 大额清算 / 合约漏洞
* 交易所宕机 / 资金安全事件
* FOMC 鹰派 / 强加息
* 大型机构净抛售（公开披露）

### 兜底原则
* 信号弱或方向不完全明确 → 默认"中性"，不允许猜中偏多/偏空
* 必须能在 .txt 摘录中指出具体证据词
* 同条新闻含正反信号 → 标"中性"，写 note 说明

## Step 3：aggregate（分层主导，政治 > 行业）

先各自汇总 tier1_sentiment / tier2_sentiment（各层内用下方 count-based），再合成：

1. **Tier 1 有明确方向**（利多/利空/中性偏多/偏空）→ **以 Tier 1 为主导**：
   * Tier 2 同向 → 增强（可由"中性偏X"升为"利X"）。
   * Tier 2 反向 → **不得翻转 Tier 1 方向**，最多把"利X"降一档为"中性偏X"。
   * aggregate_reason 必须点明"主导层=政治"。
2. **Tier 1 全中性 / 无 T1 新闻** → 退回 **Tier 2 count-based**（即下方计数法）。
3. 任一层内的 count-based：
   * 全部利多 → 利多；全部利空 → 利空
   * 利多 > 利空（差 ≥ 2 条）→ 中性偏多；利空 > 利多（差 ≥ 2 条）→ 中性偏空
   * 其余 → 中性

> 用途分流：本 aggregate 主要服务**中线（主账户）方向**（基本面>盘面>盘口）；
> 对**日内 Maker** 仅作风险否决/降频，不参与方向打分（见 `constitution/trading_constitution.md` §框架优先级）。

## Step 4：写 outputs/

---

# 禁止行为

* 禁止用 AI 生成新闻替代真实截图
* 禁止从 .txt 推断 sentiment 而不引用截图
* 禁止使用昨日 / 历史新闻
* 禁止超出 `terminology.md` 标准词汇库的判断
* 若截图模糊 / 关键文字不可读 → 标 `category:"unknown", sentiment:"中性"`，加 note，**不猜**

---

# 异常处理

* 0 张截图但 valid:true → aggregate_sentiment = "中性"，reason="今日无重要新闻"
* manifest 校验不通过 → 输出空 summary + error 字段，下游 output_agent 标"基本面：待补充"
