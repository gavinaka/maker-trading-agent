const DEFAULT_WINDOW_HOURS = 12;

const BUCKETS = {
  macro_policy: {
    rank: 100,
    base: 1000,
    tier: 'T1政治/宏观',
    category: '货币政策',
  },
  regulatory_policy: {
    rank: 95,
    base: 960,
    tier: 'T1政治/宏观',
    category: '监管立法',
  },
  btc_etf_flow: {
    rank: 90,
    base: 900,
    tier: 'T2行业',
    category: 'ETF资金流',
  },
  crypto_market_structure: {
    rank: 70,
    base: 700,
    tier: 'T2行业',
    category: '链上/市场结构',
  },
  exchange_security_whale: {
    rank: 60,
    base: 620,
    tier: 'T2行业',
    category: '交易所/链上安全/鲸鱼',
  },
  eth_sector: {
    rank: 50,
    base: 540,
    tier: 'T2行业',
    category: 'ETH/项目技术',
  },
  secondary_sector: {
    rank: 30,
    base: 360,
    tier: 'T2行业',
    category: '二级行业/宏观旁枝',
  },
  other: {
    rank: 20,
    base: 300,
    tier: 'T2行业',
    category: '其他',
  },
  meme_other: {
    rank: 10,
    base: 240,
    tier: 'T2行业',
    category: 'Meme/其他',
  },
};

const PATTERNS = {
  btc: /(BTC|比特币|Bitcoin)/i,
  eth: /(ETH|以太坊|Ethereum|stETH)/i,
  cryptoContext: /(加密|数字资产|稳定币|代币|链上|DeFi|Solana|Ethereum|以太坊|BNB|BSC|交易所|巨鲸|鲸鱼|Tornado Cash)/i,
  // Regulatory relevance needs a stricter crypto context than general news
  // classification. Bare “交易所/巨鲸” may describe traditional markets.
  regulatoryCryptoContext: /(BTC|比特币|Bitcoin|ETH|以太坊|Ethereum|加密(?:货币|资产)?|数字资产|虚拟资产|稳定币|代币|区块链|链上|DeFi|Web3|NFT|MiCA|Coinbase|Kraken|Bybit|OKX|Binance(?!\s*广场)|币安|欧易|火币|Tornado Cash|Tether|USDT|USDC)/i,
  meme: /(Meme|MEME|FOMO|TCC|BSC链Meme|无实际用例)/i,
  personalStory: /(字节炒股|炒股哥|Leto Bao|个人复盘|复盘总结|建议投资AI|对冲被AI取代)/i,
  speculativePositionTitle: /(巨鲸|鲸鱼|交易员|聪明钱|某地址|多单|空单|头寸|爆仓|清算价|浮盈|浮亏)/i,
  nonCryptoSectorTitle: /(AI|人工智能|英伟达|美光|韩股|美股|证券交易所|iPhone|硬盘|存储|芯片|电池|机器人|航天|核能|电力|国防|数据中心|三星|SK海力士|Meta|亚马逊|微软|谷歌|Alphabet|甲骨文)/i,
  // “利率”不能裸匹配：它会把“毛利率”“净利率”等企业指标误升为宏观。
  macroCore: /(美联储|FOMC|FedWatch|国内生产总值|CPI|PCE|通胀|非农|失业率|就业|美债|QT|QE|央行|货币政策|核心PCE)/i,
  // 独立维护政策利率语义，并排除常见企业利润率复合词的子串命中。
  policyRate: /(降息|加息|联邦基金利率|政策利率|基准利率|目标利率|贷款市场报价利率|LPR|维持利率|保持利率|调整利率|利率不变|(?<!毛)(?<!净)(?<!年化)利率(?:决定|决议|工具|路径|预期|政策|目标|走廊))/i,
  macroDollar: /(美元指数|美元流动性|(?:^|[^\d十百千万亿])美元(?:走强|走弱|走高|走低|回落|反弹|坚挺|疲软|维持稳定|保持坚挺))/i,
  macroDollarBody: /(美元指数|美元流动性|DXY|(?:^|[^\d十百千万亿])美元(?:目前|仍|仍将|将|继续|短线|日内|隔夜|整体|大幅|小幅)(?:走强|走弱|走高|走低|回落|反弹|坚挺|疲软|维持稳定|保持坚挺))/i,
  // A bare currency unit such as “亿美元” is not macro context. Dollar
  // context must describe DXY/USD direction or liquidity explicitly.
  macroLiquidityContext: /(美联储|FOMC|美元指数|美元流动性|DXY|美债|央行|QT|QE|货币政策|通胀|CPI|PCE|非农|就业)/i,
  // A geopolitical event needs both an event trigger in the title and a
  // compatible state/political/military context. This prevents generic words
  // such as “冲突/选举/打击” from promoting private or corporate events.
  geopoliticalAuthorityContext: /(政府|总统|总理|首相|军方|军队|武装|美军|俄军|以军|伊军|乌军|国防部|外交部|白宫|克里姆林宫|国会|议会|政权|北约|联合国|军事基地|核设施|领空|边境|特朗普|普京|泽连斯基|内塔尼亚胡|哈梅内伊)/i,
  geopoliticalPoliticalContext: /(政府|总统|总理|首相|外交部|白宫|克里姆林宫|国会|议会|政党|候选人|政权|北约|联合国|特朗普|普京|泽连斯基|内塔尼亚胡|哈梅内伊)/i,
  geopoliticalMilitaryContext: /(军事|军方|军队|武装|美军|俄军|以军|伊军|乌军|导弹|火箭|无人机|空袭|炮击|轰炸|入侵|试射|扣押|扣留|劫持|击落|攻占|击沉|越境|突袭|击毙|战区|战场|攻势|核设施|军事基地|领空|边境|海峡|航运|油轮|军舰|停火|交火|战争|消耗战|霍尔木兹|哈马斯|真主党|胡塞)/i,
  geopoliticalTheater: /(中东|台海|南海|红海|黑海|霍尔木兹海峡|加沙|边境|领空)/i,
  geopoliticalBilateral: /(美伊|俄乌|以伊|美俄|中美|朝韩|印巴|以巴)/i,
  geopoliticalSovereign: /(美国|中国|俄罗斯|乌克兰|伊朗|以色列|巴勒斯坦|加沙|黎巴嫩|叙利亚|伊拉克|也门|朝鲜|韩国|日本|欧盟|英国|法国|德国|印度|巴基斯坦|台湾)/i,
  corporateGovernanceContext: /(公司|企业|董事会|股东|供应商|员工|平台|用户|个人|主播|观众|YouTuber|银行|大学|学校|学院|学生会|球队|俱乐部|协会|商会|出版社|博彩公司|预测市场)/i,
  regulatory: /(SEC|CFTC|监管|立法|法案|执法|MiCA|司法部|财政部|批准.{0,12}ETF|拒绝.{0,12}ETF|ETF.{0,12}批准|ETF.{0,12}拒绝|稳定币.{0,12}法案|数字资产.{0,12}政策)/i,
  btcEtfFlow: /((BTC|比特币|Bitcoin).{0,24}(ETF|净流入|净流出)|ETF.{0,24}(BTC|比特币|Bitcoin)|现货比特币ETF|IBIT|GBTC|FBTC|ARKB|Farside)/i,
  exchangeEvent: /(交易所|上币|宕机|Coinbase|Kraken|Bybit|OKX|Binance(?!\s*广场))/i,
  security: /(黑客|攻击|漏洞|制裁|执法|Tornado Cash|预言机|合约漏洞)/i,
  whale: /(巨鲸|鲸鱼|大额转账|转入交易所|转出交易所|地址)/i,
  liquidation: /(爆仓|清算|杠杆|强平|连锁清算|波动)/i,
  marketStructure: /(供应量|净供应|行情|现货价格|资金费率|持仓|OI|CVD|Delta|POC|卖压|买盘|抛压|波动)/i,
  institutionCrypto: /(Strategy|MicroStrategy|Metaplanet|机构持仓|增持|减持|净买入|净卖出)/i,
  quantified: /(\d+(?:\.\d+)?\s*(亿|万|万美元|亿美元|枚|%|个基点|bp))/i,
  btcComparison: /(?:超过|超越|高于|低于|不及|仅次于|接近|相当于|对比|相比(?:于)?|超)[\s、，,:：-]*(?:BTC|比特币|Bitcoin)/gi,
};

const PPI_RELEASE_PATTERN = /(\bPPI\b|工业生产者出厂价格指数|生产者(?:价格|物价)指数)/i;
const PPI_FALSE_ENTITY_PATTERN = /(?:\bPPI\b\s*[（(【\["'“‘]*\s*(?:代币|币|Token|Coin|Labs?\b|实验室|项目|协议|生态|平台|网络|融资|公司)|(?:代币|Token|Coin|Labs?\b|实验室|项目|协议|生态|平台|网络|融资|公司)[^。！？!?；;，,\n]{0,16}\bPPI\b|\bPPI\b[^。！？!?；;，,\n]{0,40}(?:代币|Token|Coin|项目|协议|平台|公司)(?:上线|发布|推出|融资|启动|开放交易)|\bPPI\b[^。！？!?；;，,\n]{0,20}(?:其实|实际)?\s*(?:是|为|系|属于|指代?)\s*(?:同名|某)?\s*(?:代币|Token|Coin|项目|协议|平台|公司)|\bPPI\b[^。！？!?；;，,\n]{0,24}%?\s*的\s*(?:代币|链上|项目)?(?:理财|收益)?(?:产品|项目|协议|收益率))/i;
const PPI_CURRENT_FALSE_IDENTITY_PATTERN = /(?:(?:文中|本文|这里|该文|上述|本次)[^。！？!?；;，,\n]{0,16}\bPPI\b|\bPPI\b[^。！？!?；;，,\n]{0,12}(?:其实|实际)?\s*(?:是|为|系|属于|指代?))[^。！？!?；;，,\n]{0,20}(?:同名|某)?\s*(?:代币|Token|Coin|项目|协议|平台|公司)(?:[^。！？!?；;，,\n]{0,20}(?:并非|不是)\s*(?:宏观|生产者|价格指数))?/i;
const PPI_POST_VALUE_FALSE_IDENTITY_PATTERN = /(?:^|[。！？!?；;，,\n])\s*(?:该(?:值|数据|读数|年率|月率)?\s*)?(?:其实|实际|事实上|本质上)\s*(?:是|为|系|属于)?\s*(?:同名|某)?\s*(?:代币|Token|Coin|项目|协议|平台)(?:[^。！？!?；;，,\n]{0,12}(?:收益率|回报率|理财产品|收益产品))?/i;
const PPI_ACTUAL_VALUE_PATTERN = /(?:(?:年率|月率|同比|环比)\s*(?:由|从)\s*[+-]?\d+(?:\.\d+)?\s*%\s*(?:升至|降至|上升至|下降至|修正为)\s*[+-]?\d+(?:\.\d+)?\s*%|(?:(?:年率|月率|同比|环比)\s*(?:录得|为|报|升至|降至|增长|下降|上升|上涨|下跌|回落|达|达到|涨幅为|降幅为|增幅为|涨|降|增|减|增加|减少|持平)?\s*(?:了\s*)?(?:约|大约)?|(?:实际值?|公布值|发布值)\s*(?:录得|为|报)?\s*(?:约|大约)?|(?:较|与)\s*(?:去年|前年|上年)同期(?:相比)?\s*(?:上涨|下降|增长|上升|下跌|回落)\s*(?:了\s*)?(?:约|大约)?)\s*[+-]?\d+(?:\.\d+)?\s*%)/i;
const PPI_INVERTED_ACTUAL_RELEASE_PATTERN = new RegExp(
  `(?:${PPI_ACTUAL_VALUE_PATTERN.source})\\s*的\\s*(?:核心\\s*)?(?:${PPI_RELEASE_PATTERN.source})(?:\\s*(?:指数|数据|结果|报告))?\\s*(?:已|正式)?\\s*(?:公布|发布|披露|出炉)`,
  'i',
);
const PPI_NON_ACTUAL_MODALITY_PATTERN = /((?:预计|预测|估计|预估|预料|认为)|(?:下一期|下期|下一次|下月|次月|下季度|未来一期)|(?:将|将会|大概率|或许|恐|恐将|有可能)(?=\s*(?:录得|为|报|达|达到|增长|下降|上升|上涨|下跌|回落|年率|月率|同比|环比))|(?:料|有望|或)(?=\s*(?:将|会|可|可能|录得|为|报|达|达到|增长|下降|上升|上涨|下跌|回落|年率|月率|同比|环比))|(?:市场|机构|分析师|经济学家|模型|路透|彭博)[^。！？!?；;，,\n]{0,10}(?:料(?:将|为|得|录得)?|认为|预计|预测|估计|预估|预料)|(?:市场|交易员|投资者)[^。！？!?；;，,\n]{0,12}(?:押注|定价)|(?:掉期|期货|衍生品)?市场[^。！？!?；;，,\n]{0,12}(?:隐含|暗示)|接受调查|调查(?:显示|预估|中值|中位数|所得共识值?)|市场共识|一致预期|或将|可能|前值|预期)/i;
const PPI_HISTORICAL_MODALITY_PATTERN = /(历史(?!新高|新低|最高|最低|纪录)|过往|往期|早前|此前|先前|更早前|当时|曾经|曾|一度|去年|上年|前年|旧|上期|前期|前次|上次|上月|前月|上季度|前季)/i;
const PPI_STRONG_ACTUAL_MODALITY_PATTERN = /((?:官方)?数据显示|(?:官方|政府部门|统计机构|劳工部)\s*(?:已|正式)?\s*(?:公布|发布|披露)(?:的)?(?:数据|结果|数值)?|(?:实际|最终)(?:值|数据|结果)?|(?:初值|终值|修正(?:后|值))|(?:最终|本次)?\s*(?:已|正式)?\s*公布|已公布|公布值|发布值)/i;
const PPI_UNPUBLISHED_STATE_SOURCE = '(?:(?:(?:截至(?:目前|发稿)|目前)\\s*)?(?:官方\\s*)?(?:(?:尚|仍|还|暂)?\\s*未|没有|尚无|仍无|暂无)\\s*(?:正式|官方|对外)?\\s*(?:公布|发布|披露|出炉)(?:值|结果|数据)?|(?:尚待|仍待|有待|等待|待)\\s*(?:正式|官方|对外)?\\s*(?:公布|发布|披露|出炉)|(?:即将|将于[^。！？!?；;，,\\n]{0,12})\\s*(?:正式)?\\s*(?:公布|发布|披露|出炉)|(?:公布|发布|披露|出炉)前|前瞻)';
const PPI_UNPUBLISHED_STATE_PATTERN = new RegExp(PPI_UNPUBLISHED_STATE_SOURCE, 'i');
const PPI_UNRELATED_SUBJECT_PATTERN = /(美联储|FOMC|央行|利率(?:决议|决定|路径|数据)|CPI|PCE|GDP|PMI|ISM|采购经理人指数|非农|失业率|就业|美元|DXY|财政部|美债|公司|企业|财报|工资|薪资|薪酬|利润|零售销售|工业产出|房价|租金|油价|能源价格|食品价格|出口|进口|消费支出|个人收入|库存|影院票价|服务价格|核心通胀)/i;
const PPI_COMPARISON_PREFIX_PATTERN = /(?:与|较)\s*(?:去年|前年|上年)(?:同期)?(?:相比|比较)?[，,\s]*|相比(?:于)?\s*(?:去年|前年|上年)(?:同期)?[，,\s]*/gi;
const OTHER_MACRO_INDICATOR_PATTERN = /(\bCPI\b|\bPCE\b|\bGDP\b|\bPMI\b|\bISM\b|采购经理人指数|非农|失业率|就业|工资|薪资|企业利润|利润|零售销售|工业产出|房价|租金|油价|能源价格|食品价格|出口|进口|消费支出|个人收入|库存)/i;
const PPI_JURISDICTION_SOURCE = '(?:美国|欧元区|欧盟|中国|英国|日本|加拿大|澳大利亚|德国|法国|韩国|瑞士|印度)';
const MONTH_TOKEN_PATTERN_SOURCE = '(?:(?<!\\d)(?:1[0-2]|0?[1-9])(?!\\d)|(?<![一二三四五六七八九十])(?:十[一二]?|[一二三四五六七八九])(?![一二三四五六七八九十]))';
const CHINESE_MONTHS = new Map([
  ['一', 1],
  ['二', 2],
  ['三', 3],
  ['四', 4],
  ['五', 5],
  ['六', 6],
  ['七', 7],
  ['八', 8],
  ['九', 9],
  ['十', 10],
  ['十一', 11],
  ['十二', 12],
]);
const GDP_TOKEN_PATTERN = /\bGDP\b/i;
const GDP_ENTITY_PATTERN_SOURCE = '(?:代币|Token|Coin|Labs?\\b|实验室|项目|协议|生态|平台|网络|融资|公司)';
const GDP_FALSE_ENTITY_PATTERN = new RegExp(
  `(?:\\bGDP\\b.{0,16}${GDP_ENTITY_PATTERN_SOURCE}|${GDP_ENTITY_PATTERN_SOURCE}.{0,16}\\bGDP\\b)`,
  'i',
);
const GDP_MACRO_CONTEXT_PATTERN = /(美国|中国|欧元区|欧盟|英国|日本|加拿大|澳大利亚|德国|法国|韩国|瑞士|印度|季度|年化|季率|同比|环比|增长|下降|增速|萎缩|经济|预期|初值|终值|修正)/i;
const GDP_ACTUAL_VALUE_PATTERN = /\bGDP\b\s*(?:录得|报|为)?\s*[+-]?\d+(?:\.\d+)?\s*%/i;
const JURISDICTION_PATTERNS = [
  ['美国', /美国/i],
  ['欧元区', /欧元区/i],
  ['欧盟', /欧盟/i],
  ['中国', /中国/i],
  ['英国', /英国/i],
  ['日本', /日本/i],
  ['加拿大', /加拿大/i],
  ['澳大利亚', /澳大利亚/i],
  ['德国', /德国/i],
  ['法国', /法国/i],
  ['韩国', /韩国/i],
  ['瑞士', /瑞士/i],
  ['印度', /印度/i],
];

function has(pattern, text) {
  return pattern.test(text);
}

function hasNearby(first, second, text, maxChars = 32) {
  const flags = 'is';
  const forward = new RegExp(`(?:${first.source}).{0,${maxChars}}(?:${second.source})`, flags);
  const reverse = new RegExp(`(?:${second.source}).{0,${maxChars}}(?:${first.source})`, flags);
  return forward.test(text) || reverse.test(text);
}

function clampScore(score, maxScore) {
  return Math.min(score, maxScore);
}

const NON_EVENT_PRODUCT_OR_USAGE_PATTERN = /(?:(?:发布|推出|开发|销售|供应|采购|展示|上线|上映|出版).{0,20}(?:软件|产品|工具|平台|系统|模型|设备|合同|订单|网站|电影|小说)|(?:软件|产品|工具|平台|系统|模型|设备|网站|电影|小说).{0,20}(?:用途|用于|供[^。！？!?；;，,\n]{0,12}使用|预测|模拟|上线|上映|出版)|博彩|赔率|题材电影|预测(?:软件|网站))/i;
const GEO_TRIGGER_DEFINITIONS = [
  { kind: 'AIRSTRIKE', pattern: /空袭/i, armed: true },
  { kind: 'MISSILE', pattern: /(?:试射|发射|部署|拦截).{0,8}(?:导弹|火箭)|(?:导弹|火箭).{0,8}(?:袭击|打击|试射|发射|拦截)/i, armed: true },
  { kind: 'ATTACK', pattern: /袭击|遭袭|打击|炮击|轰炸|入侵|扣押|扣留|劫持|击落|攻占|击沉|越境|突袭|击毙/i, armed: true },
  { kind: 'CONFLICT', pattern: /武装冲突|边境冲突|国际冲突|军事冲突|交火|开战|消耗战|战争|军事行动|停火|局势升级/i, armed: true },
  { kind: 'BLOCKADE', pattern: /封锁/i, armed: true },
  { kind: 'SANCTION', pattern: /制裁/i, armed: false },
  { kind: 'ELECTION', pattern: /选举|大选/i, armed: false },
  { kind: 'DIPLOMACY', pattern: /(?:签署|展开|举行|恢复|中断|启动|结束|升级).{0,8}外交|外交.{0,8}(?:会谈|谈判|行动|危机|冲突|关系)/i, armed: false },
];
const GEO_NON_STATE_COMPOUND_PATTERN = /(?:美国|中国|俄罗斯|乌克兰|伊朗|以色列|韩国|日本|英国|法国|德国|印度|欧盟)(?:银行|大学|学校|学院|公司|企业|球队|俱乐部|协会|商会|出版社|平台)/gi;
const GEO_ACTOR_PATTERNS = [
  ['美国', /美国|美军|白宫|美国国防部|特朗普/i],
  ['中国', /中国|中方|中国政府|解放军/i],
  ['俄罗斯', /俄罗斯|俄方|俄军|克里姆林宫|普京/i],
  ['乌克兰', /乌克兰|乌方|乌军|泽连斯基/i],
  ['伊朗', /伊朗|伊方|伊军|哈梅内伊/i],
  ['以色列', /以色列|以方|以军|内塔尼亚胡/i],
  ['叙利亚', /叙利亚|叙方|叙军/i],
  ['朝鲜', /朝鲜|朝方/i],
  ['韩国', /韩国|韩方|韩军/i],
  ['法国', /法国|法方/i],
  ['英国', /英国|英方|英军/i],
  ['德国', /德国|德方/i],
  ['日本', /日本|日方|自卫队/i],
];

function splitGeoPropositions(text) {
  return String(text)
    .split(/(?:[。！？!?；;，,\n]+|但|然而|不过|(?:并|同时|随后)(?=(?:公司|企业|平台|出版社)?\s*(?:发布|推出|上线|开发|销售|展示)))/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function geoActors(text) {
  const actorText = String(text).replace(GEO_NON_STATE_COMPOUND_PATTERN, '');
  return new Set(
    GEO_ACTOR_PATTERNS
      .filter(([, pattern]) => pattern.test(actorText))
      .map(([name]) => name),
  );
}

function geoPredicateParticipants(proposition, trigger) {
  const match = String(proposition).match(trigger.pattern);
  if (!match) return { actors: new Set(), targets: new Set() };
  const prefix = String(proposition).slice(0, match.index);
  const suffix = String(proposition).slice(match.index + match[0].length);
  const targets = geoActors(suffix);
  const prepositionalTarget = prefix.match(/(?:对|向|针对)([^。！？!?；;，,\n]{0,24})$/i);
  if (prepositionalTarget) {
    for (const target of geoActors(prepositionalTarget[1])) targets.add(target);
  }
  const actors = geoActors(prefix);
  for (const target of targets) actors.delete(target);
  return { actors, targets };
}

function classifyGeoPredicateState(proposition, trigger) {
  const text = String(proposition);
  const triggerSource = trigger.pattern.source;
  const triggerMatch = text.match(trigger.pattern);
  if (!triggerMatch) return 'NONE';
  const triggerStart = triggerMatch.index;
  const triggerEnd = triggerStart + triggerMatch[0].length;
  const prefix = text.slice(0, triggerStart);
  const effectOrAttributeDenial = new RegExp(
    `(?:否认|驳斥)[^。！？!?；;，,\\n]{0,18}(?:${triggerSource})[^。！？!?；;，,\\n]{0,18}(?:造成|导致|针对|涉及|违反|使用|采用|报道中(?:的)?)[^。！？!?；;，,\\n]{0,20}(?:伤亡|死亡|受伤|损失|平民|人员|数字|程度|目标|国际法|武器|装备|方式)`,
    'i',
  );
  if (effectOrAttributeDenial.test(text) && !/(?:未发生|没有发生|不实|不属实|虚假)/i.test(text)) {
    return 'EFFECT';
  }
  const productVerb = text.match(/(?:发布|推出|开发|销售|供应|采购|展示|上线|上映|出版)/i);
  const productAfterIndependentEvent = Boolean(
    productVerb
    && productVerb.index > triggerEnd
    && /(?:后|随后|并|同时)/i.test(text.slice(triggerEnd, productVerb.index))
  );
  if (
    (NON_EVENT_PRODUCT_OR_USAGE_PATTERN.test(text) && !productAfterIndependentEvent)
    || /(?:预测市场|博彩|赔率)[^。！？!?；;，,\n]{0,20}(?:押注|预测|预期)?/i.test(text)
  ) return 'PRODUCT';
  const continuedEvent = new RegExp(
    `(?:没有|并未|未曾|从未|尚未|还未)\\s*(?:停止|暂停|中止|中断|结束)[^。！？!?；;，,\\n]{0,20}(?:${triggerSource})|(?:仍在|继续|持续)[^。！？!?；;，,\\n]{0,12}(?:${triggerSource})`,
    'i',
  );
  if (continuedEvent.test(text)) return 'ASSERTED';
  const negatedEvent = new RegExp(
    `(?:否认|驳斥|澄清|未证实|尚未证实)[^。！？!?；;，,\\n]{0,20}(?:${triggerSource})(?:[^。！？!?；;，,\\n]{0,12}(?:发生|存在|报道|消息|传闻|说法|真实性|不实|不属实|虚假))?|(?:并未|并无|没有|未曾|从未|尚未|还未|未)\\s*[^。！？!?；;，,\\n]{0,16}(?:${triggerSource})|(?:所谓\\s*)?(?:${triggerSource})[^。！？!?；;，,\\n]{0,16}(?:从未|并未|没有|未曾|尚未|还未|未)(?:发生|存在|实施|发动|进行)?|(?:${triggerSource})[^。！？!?；;，,\\n]{0,16}(?:报道|消息|传闻|说法)[^。！？!?；;，,\\n]{0,16}(?:不实|不属实|虚假|错误|未经证实|被否认)`,
    'i',
  );
  if (negatedEvent.test(text)) return 'NEGATED';
  const escalationDiscussion = /(?:扩大|升级|继续|持续)[^。！？!?；;，,\n]{0,20}(?:范围|行动|攻势)|(?:打击|空袭)[^。！？!?；;，,\n]{0,12}范围/i.test(text);
  const conditionalPrefix = /(?:计划|拟|正?考虑|讨论|不排除|可能|或将|将|预计|预测|押注|是否|能否|有意|准备|威胁)[^。！？!?；;，,\n]{0,32}$/i.test(prefix);
  if (
    (conditionalPrefix && !escalationDiscussion)
    || /(?:如果|若|假如|一旦|预测市场|押注|预计|预测|可能|或将)[^。！？!?；;，,\n]{0,28}$/i.test(prefix)
    || new RegExp(
      `(?:批准|通过)[^。！？!?；;，,\\n]{0,20}(?:${triggerSource})[^。！？!?；;，,\\n]{0,16}(?:计划|方案)`,
      'i',
    ).test(text)
    || /(?:吗|是否|能否|会不会)[？?]?$/i.test(text)
  ) return 'CONDITIONAL';
  return 'ASSERTED';
}

function extractGeoPredicates(text, source) {
  const predicates = [];
  let priorActors = new Set();
  let priorTargets = new Set();
  let priorPredicate = null;
  for (const proposition of splitGeoPropositions(text)) {
    let matchedTrigger = false;
    for (const trigger of GEO_TRIGGER_DEFINITIONS) {
      if (!trigger.pattern.test(proposition)) continue;
      matchedTrigger = true;
      const participants = geoPredicateParticipants(proposition, trigger);
      const mayInherit = /^(?:并)?(?:确认|证实|表示|称|同时|仍|继续)/i.test(proposition);
      const actors = participants.actors.size === 0 && mayInherit
        ? new Set(priorActors)
        : participants.actors;
      const targets = participants.targets.size === 0 && mayInherit
        ? new Set(priorTargets)
        : participants.targets;
      const predicate = {
        kind: trigger.kind,
        armed: trigger.armed,
        state: classifyGeoPredicateState(proposition, trigger),
        actors: new Set(actors),
        targets: new Set(targets),
        anaphoric: /(?:相关|有关|上述|此次|该|此事|所谓)/i.test(proposition),
        text: proposition,
        source,
      };
      predicates.push(predicate);
      priorPredicate = predicate;
      if (participants.actors.size > 0) priorActors = new Set(participants.actors);
      if (participants.targets.size > 0) priorTargets = new Set(participants.targets);
    }
    if (
      !matchedTrigger
      && priorPredicate
      && /^(?:并)?(?:确认|证实)[^。！？!?；;，,\n]{0,12}(?:行动|事件)(?:已|已经)?(?:发生|执行|实施)/i.test(proposition)
    ) {
      const confirmation = {
        ...priorPredicate,
        state: 'ASSERTED',
        actors: new Set(priorActors),
        targets: new Set(priorTargets),
        anaphoric: true,
        text: proposition,
        source,
      };
      predicates.push(confirmation);
      priorPredicate = confirmation;
    }
  }
  return predicates;
}

function sameGeoEvent(asserted, denied) {
  const kineticKinds = new Set(['AIRSTRIKE', 'ATTACK']);
  const genericArmedDenial = denied.kind === 'CONFLICT'
    && denied.anaphoric
    && /军事行动/i.test(denied.text);
  if (
    asserted.kind !== denied.kind
    && !(kineticKinds.has(asserted.kind) && kineticKinds.has(denied.kind))
    && !(asserted.armed && genericArmedDenial)
  ) return false;
  const actorOverlap = [...asserted.actors].some((actor) => denied.actors.has(actor));
  const targetOverlap = [...asserted.targets].some((target) => denied.targets.has(target));
  if (
    asserted.actors.size > 0
    && denied.actors.size > 0
    && !actorOverlap
  ) return false;
  if (
    asserted.targets.size > 0
    && denied.targets.size > 0
    && !targetOverlap
  ) return false;
  if (denied.anaphoric) return actorOverlap || targetOverlap || (
    denied.actors.size === 0 && denied.targets.size === 0
  );
  return actorOverlap || targetOverlap || (
    denied.actors.size === 0 && denied.targets.size === 0
  );
}

function genericBodyDeniesTitleEvent(body, asserted) {
  const denial = /(?:(?:相关|有关|上述|这一|该|此)(?:消息|报道|传闻|说法|事|事件)[^。！？!?；;，,\n]{0,16}(?:系|是|为)?\s*(?:不实|不属实|虚假|错误|未经证实|误传)|(?:此事|该事件|这一事件)[^。！？!?；;，,\n]{0,12}(?:并未|没有|未曾)发生)/i;
  if (!denial.test(body)) return false;
  const actors = geoActors(body);
  return actors.size === 0
    || [...asserted.actors].some((actor) => actors.has(actor))
    || [...asserted.targets].some((target) => actors.has(target));
}

function geoPredicateHasLocalContext(predicate, body) {
  const local = predicate.text;
  const actorText = local.replace(GEO_NON_STATE_COMPOUND_PATTERN, '');
  const sovereignCount = distinctPatternMatches(PATTERNS.geopoliticalSovereign, actorText);
  const bilateral = has(PATTERNS.geopoliticalBilateral, actorText);
  const localAuthority = has(PATTERNS.geopoliticalAuthorityContext, local);
  const corporateOrPrivate = has(PATTERNS.corporateGovernanceContext, local);
  const context = `${local}\n${String(body)}`;
  if (predicate.armed) {
    if (corporateOrPrivate && !localAuthority) return false;
    const militaryContext = has(PATTERNS.geopoliticalMilitaryContext, context);
    const theater = has(PATTERNS.geopoliticalTheater, context);
    return militaryContext && (
      predicate.actors.size > 0 || sovereignCount >= 1 || bilateral || localAuthority || theater
    );
  }
  const localPoliticalAuthority = has(PATTERNS.geopoliticalPoliticalContext, local);
  if (corporateOrPrivate && !localPoliticalAuthority) return false;
  return localPoliticalAuthority || predicate.actors.size > 0 || sovereignCount >= 1 || bilateral;
}

function distinctPatternMatches(pattern, text) {
  const matches = text.match(new RegExp(pattern.source, 'gi')) || [];
  return new Set(matches.map((item) => item.toLowerCase())).size;
}

function isDirectGeopoliticalEvent(row) {
  const title = String(row?.title || '');
  const body = String(row?.body || '');
  const titlePredicates = extractGeoPredicates(title, 'title');
  const allPredicates = [
    ...titlePredicates,
    ...extractGeoPredicates(body, 'body'),
  ];
  const denials = allPredicates.filter((predicate) => predicate.state === 'NEGATED');
  return titlePredicates
    .filter((predicate) => predicate.state === 'ASSERTED')
    .filter((predicate) => geoPredicateHasLocalContext(predicate, body))
    .some((predicate) => (
      !denials.some((denial) => sameGeoEvent(predicate, denial))
      && !genericBodyDeniesTitleEvent(body, predicate)
    ));
}

function referenceYearMonth(row) {
  const match = String(row?.date || row?.datetime || '').match(/^(20\d{2})-(0[1-9]|1[0-2])/);
  return match ? { year: Number(match[1]), month: Number(match[2]) } : null;
}

function normalizeReportedPeriod(yearText, monthText, row) {
  const month = /^\d+$/.test(String(monthText))
    ? Number(monthText)
    : CHINESE_MONTHS.get(String(monthText));
  if (!Number.isInteger(month) || month < 1 || month > 12) return null;
  let year = yearText ? Number(yearText) : null;
  if (!year) {
    const reference = referenceYearMonth(row);
    if (!reference) return null;
    year = month > reference.month ? reference.year - 1 : reference.year;
  }
  return `${year}-${String(month).padStart(2, '0')}`;
}

function ppiPeriodMentions(text, row) {
  const raw = String(text);
  const indicator = '(?:\\bPPI\\b|工业生产者出厂价格指数|生产者(?:价格|物价)指数)';
  const before = new RegExp(
    `(?:(20\\d{2})\\s*年\\s*)?(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?\\s*(?:${PPI_JURISDICTION_SOURCE}\\s*)?(?:核心\\s*)?${indicator}`,
    'gi',
  );
  const after = new RegExp(
    `${indicator}\\s*(?:(20\\d{2})\\s*年\\s*)?(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?`,
    'gi',
  );
  const inverted = new RegExp(
    `(?:(20\\d{2})\\s*年\\s*)?(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?[^。！？!?；;，,\\n]{0,24}(?:年率|月率|同比|环比)[^。！？!?；;，,\\n]{0,16}[+-]?\\d+(?:\\.\\d+)?\\s*%\\s*的\\s*(?:核心\\s*)?${indicator}`,
    'gi',
  );
  const mentions = [];
  for (const pattern of [before, after, inverted]) {
    for (const match of raw.matchAll(pattern)) {
      const period = normalizeReportedPeriod(match[1], match[2], row);
      const ppiWithin = match[0].search(new RegExp(indicator, 'i'));
      if (!period || ppiWithin < 0) continue;
      const ppiMatch = match[0].slice(ppiWithin).match(new RegExp(indicator, 'i'));
      if (!ppiMatch) continue;
      mentions.push({
        period,
        ppiStart: match.index + ppiWithin,
        ppiEnd: match.index + ppiWithin + ppiMatch[0].length,
        coreStart: match.index,
        coreEnd: match.index + match[0].length,
      });
    }
  }
  const unique = new Map();
  for (const mention of mentions) {
    unique.set(`${mention.ppiStart}:${mention.period}`, mention);
  }
  return [...unique.values()];
}

function ppiReportedPeriods(text, row) {
  return [...new Set(ppiPeriodMentions(text, row).map((mention) => mention.period))];
}

function hasUnresolvedRelativePpiPeriod(text) {
  const periodScopeText = String(text).replace(PPI_COMPARISON_PREFIX_PATTERN, '');
  const relativePeriod = new RegExp(`(?:去年|前年|上年)\\s*${MONTH_TOKEN_PATTERN_SOURCE}\\s*月`, 'i');
  const indicator = '(?:\\bPPI\\b|工业生产者出厂价格指数|生产者(?:价格|物价)指数)';
  const relativeBeforeIdentity = new RegExp(
    `(?:去年|前年|上年)[^。！？!?；;\\n]{0,32}(?:${MONTH_TOKEN_PATTERN_SOURCE}\\s*月(?:份)?\\s*(?:核心\\s*)?${indicator}|${indicator}[^。！？!?；;\\n]{0,12}${MONTH_TOKEN_PATTERN_SOURCE}\\s*月(?:份)?)`,
    'i',
  );
  return relativePeriod.test(periodScopeText) || relativeBeforeIdentity.test(periodScopeText);
}

function explicitPpiReportedPeriod(row) {
  const title = String(row?.title || '');
  if (hasUnresolvedRelativePpiPeriod(title)) return null;
  const titlePeriods = ppiReportedPeriods(title, row);
  return titlePeriods.length === 1 ? titlePeriods[0] : null;
}

function jurisdictionsIn(text) {
  return JURISDICTION_PATTERNS
    .filter(([, pattern]) => pattern.test(text))
    .map(([name]) => name);
}

function jurisdictionOccurrences(text, offset = 0) {
  const occurrences = [];
  for (const [name, pattern] of JURISDICTION_PATTERNS) {
    for (const match of String(text).matchAll(new RegExp(pattern.source, 'gi'))) {
      occurrences.push({
        name,
        start: offset + match.index,
        end: offset + match.index + match[0].length,
      });
    }
  }
  return occurrences.sort((left, right) => left.start - right.start);
}

function ppiIdentityBridgeIsCompatible(gap) {
  const residue = String(gap)
    .replace(/\s+/g, '')
    .replace(/(?:将于|定于)?(?:1[0-2]|0?[1-9])月(?:3[01]|[12]?\d)日/g, '')
    .replace(/(?:(?:20\d{2})年)?(?:1[0-2]|0?[1-9]|十[一二]?|[一二三四五六七八九])月(?:份)?/g, '')
    .replace(/(?:核心|本次|官方|数据|报告|结果|劳工部|统计局|统计机构|政府部门|政府)/g, '')
    .replace(/(?:已|正式)?(?:公布|发布|披露|出炉)|数据显示/g, '')
    .replace(/[：:（）()【】\[\]“”"'‘’\-—]/g, '');
  return residue === '';
}

function ppiTitleJurisdictions(row) {
  const raw = String(row?.title || '');
  const mentions = ppiPeriodMentions(raw, row);
  if (mentions.length === 0) return [];
  const allJurisdictions = jurisdictionOccurrences(raw);
  const owners = [];
  for (const mention of mentions) {
    const before = raw.slice(0, mention.coreStart);
    const leftBoundary = Math.max(
      before.lastIndexOf('。'), before.lastIndexOf('！'), before.lastIndexOf('？'),
      before.lastIndexOf('!'), before.lastIndexOf('?'), before.lastIndexOf('；'),
      before.lastIndexOf(';'), before.lastIndexOf('，'), before.lastIndexOf(','),
      before.lastIndexOf('\n'),
    );
    const inlineJurisdictions = allJurisdictions.filter(
      (item) => item.start >= mention.coreStart && item.end <= mention.coreEnd,
    );
    if (inlineJurisdictions.length > 1) return [];
    if (inlineJurisdictions.length === 1) {
      owners.push(inlineJurisdictions[0].name);
      continue;
    }
    const attachedLeft = allJurisdictions
      .filter((item) => item.end <= mention.coreStart && item.start > leftBoundary)
      .filter((item) => ppiIdentityBridgeIsCompatible(raw.slice(item.end, mention.coreStart)))
      .sort((left, right) => right.end - left.end);
    if (attachedLeft.length > 1) return [];
    if (attachedLeft.length === 1) {
      const coordinatedPredecessor = allJurisdictions
        .filter((item) => item.end <= attachedLeft[0].start && item.start > leftBoundary)
        .sort((left, right) => right.end - left.end)[0];
      if (
        coordinatedPredecessor
        && /^\s*(?:与|和|及|、)\s*$/i.test(
          raw.slice(coordinatedPredecessor.end, attachedLeft[0].start),
        )
      ) return [];
      owners.push(attachedLeft[0].name);
      continue;
    }
    // A country in the immediately preceding publisher clause may carry into
    // a bare PPI clause only when that cue has no CPI/GDP/employment/etc.
    // object already consuming it. Countries to the right are never owners.
    if (leftBoundary < 0 || !/[，,]/.test(raw[leftBoundary])) return [];
    const priorText = raw.slice(0, leftBoundary);
    const priorBoundary = Math.max(
      priorText.lastIndexOf('。'), priorText.lastIndexOf('！'), priorText.lastIndexOf('？'),
      priorText.lastIndexOf('!'), priorText.lastIndexOf('?'), priorText.lastIndexOf('；'),
      priorText.lastIndexOf(';'), priorText.lastIndexOf('，'), priorText.lastIndexOf(','),
      priorText.lastIndexOf('\n'),
    );
    const publisherClause = priorText.slice(priorBoundary + 1).trim();
    const publisherJurisdictions = jurisdictionsIn(publisherClause);
    const publisherCue = /(?:劳工部|统计局|统计机构|政府部门|官方|政府)[^。！？!?；;，,\n]{0,20}(?:已|正式)?(?:公布|发布|披露|宣布|出炉)\s*$/i;
    if (
      publisherJurisdictions.length !== 1
      || !publisherCue.test(publisherClause)
      || OTHER_MACRO_INDICATOR_PATTERN.test(publisherClause)
      || PPI_UNRELATED_SUBJECT_PATTERN.test(publisherClause)
    ) return [];
    owners.push(publisherJurisdictions[0]);
  }
  return [...new Set(owners)];
}

function lastPatternEnd(pattern, text) {
  const matches = [...text.matchAll(new RegExp(pattern.source, 'gi'))];
  if (matches.length === 0) return -1;
  const last = matches[matches.length - 1];
  return last.index + last[0].length;
}

function lastNonActualModalityEnd(text) {
  return Math.max(
    lastPatternEnd(PPI_NON_ACTUAL_MODALITY_PATTERN, text),
    lastPatternEnd(PPI_HISTORICAL_MODALITY_PATTERN, text),
    lastPatternEnd(PPI_UNPUBLISHED_STATE_PATTERN, text),
  );
}

function isHistoricalTemporalAdjunct(text) {
  const raw = String(text).trim();
  if (!/(?:历史|过往|往期|早前|此前|先前|更早前|当时|曾经|曾|一度|去年|上年|前年|上期|前期|前次|上次|上月|前月)/i.test(raw)) {
    return false;
  }
  const residue = raw
    .replace(/(?:截至|在|据|根据|更|当时|有关|相关|的|消息|资料|报道|记录|时期|期间|时候|时)/g, '')
    .replace(/(?:历史|过往|往期|早前|此前|先前|曾经|曾|一度|去年|上年|前年|上期|前期|前次|上次|上月|前月)/g, '')
    .replace(/[\s：:、·（）()【】\[\]“”"'‘’\-—]/g, '');
  return residue === '';
}

function lastOwnedStrongActualEnd(text) {
  let lastEnd = -1;
  const ppiMatches = [...text.matchAll(new RegExp(PPI_RELEASE_PATTERN.source, 'gi'))]
    .filter((match) => !PPI_FALSE_ENTITY_PATTERN.test(text.slice(match.index, match.index + match[0].length + 16)));
  if (ppiMatches.length === 0) return lastEnd;
  const owner = ppiMatches[ppiMatches.length - 1];
  const ownerEnd = owner.index + owner[0].length;
  const matches = [...text.matchAll(new RegExp(PPI_STRONG_ACTUAL_MODALITY_PATTERN.source, 'gi'))];
  for (const match of matches) {
    const prefix = text.slice(0, match.index);
    const delimiters = [...prefix.matchAll(/[，,；;]|(?:但|然而|不过|随后|之后|此后)/g)];
    const lastDelimiter = delimiters.length > 0 ? delimiters[delimiters.length - 1] : null;
    const localPrefix = lastDelimiter
      ? prefix.slice(lastDelimiter.index + lastDelimiter[0].length)
      : prefix;
    if (lastNonActualModalityEnd(localPrefix) >= 0) continue;
    if (
      OTHER_MACRO_INDICATOR_PATTERN.test(localPrefix)
      && !PPI_RELEASE_PATTERN.test(localPrefix)
    ) continue;
    if (lastDelimiter && localPrefix.trim() === '') {
      const beforeDelimiter = prefix.slice(0, lastDelimiter.index);
      const priorDelimiters = [...beforeDelimiter.matchAll(/[，,；;]|(?:但|然而|不过|随后|之后|此后)/g)];
      const previousClause = priorDelimiters.length > 0
        ? beforeDelimiter.slice(
          priorDelimiters[priorDelimiters.length - 1].index
          + priorDelimiters[priorDelimiters.length - 1][0].length,
        )
        : beforeDelimiter;
      if (isHistoricalTemporalAdjunct(previousClause)) continue;
    }
    const matchEnd = match.index + match[0].length;
    const ownershipGap = matchEnd <= owner.index
      ? text.slice(matchEnd, owner.index)
      : text.slice(ownerEnd, match.index);
    if (
      OTHER_MACRO_INDICATOR_PATTERN.test(ownershipGap)
      || PPI_RELEASE_PATTERN.test(ownershipGap)
    ) continue;
    lastEnd = matchEnd;
  }
  return lastEnd;
}

function ppiValueOwnerGapIsCompatible(gap) {
  const residue = String(gap)
    .replace(/(?:(?:市场|机构|分析师|经济学家|路透|彭博)\s*)?(?:前值|预期值?|预测值?|预估值?|估计值?)[^。！？!?；;，,\n]{0,18}[+-]?\d+(?:\.\d+)?\s*%/gi, '')
    .replace(/(?:(?:20\d{2})\s*年\s*)?(?:1[0-2]|0?[1-9]|十[一二]?|[一二三四五六七八九])\s*月(?:份)?/g, '')
    .replace(/(?:经(?:季节(?:性(?:因素)?)?调整|季调)(?:后|后的)?|季调后|(?:不含|不包括|剔除|扣除)[^。！？!?；;，,\n]{0,24}(?:后|后的|的)?(?:核心)?(?:指数)?|数据显示其|报告所列|官方(?:发布|公布)结果中(?:的)?|(?:最新|本次)?读数)/g, '')
    .replace(/[\s：:、·（）()【】\[\]“”"'‘’\-—]/g, '')
    .replace(/(?:创|刷新|达到)?历史(?:新高|新低|最高|最低|纪录)/g, '')
    .replace(/(?:官方|本次|最终|实际|初值|终值|修正后|修正值|核心|总体|整体|季调后|未季调|的)/g, '')
    .replace(/(?:报告显示|数据显示|结果显示|指数|数据|报告|结果|数值)/g, '')
    .replace(/(?:低于|高于|不及|超出|符合|接近|逊于|好于|强于|弱于|超)\s*(?:市场)?(?:预期|前值)/g, '')
    .replace(/(?:市场|机构|分析师|经济学家|模型|路透|彭博)?(?:预计|预测|估计|预估|预料|认为|料|有望|或许|大概率|有可能|恐将|恐|将会|将|或)/g, '')
    .replace(/(?:历史|过往|往期|早前|此前|先前|更早前|当时|曾经|曾|一度|去年|上年|前年|旧|上期|前期|前次|上次|上月|前月|上季度|前季|下一期|下期|下一次|下月|次月|下季度|未来一期|前值|预期)/g, '')
    .replace(/(?:已|正式)?(?:公布|发布|披露)|录得|报|为/g, '')
    .replace(/(?:但|然而|不过)/g, '')
    .replace(/[，,]/g, '');
  return residue === '';
}

function ppiModalityText(text) {
  return String(text)
    .replace(
      /(?:低于|高于|符合|不及|超出|接近|相比(?:于)?|较)\s*(?:市场)?(?:预期|前值)/gi,
      '',
    )
    .replace(
      /(?:较|比|相比(?:于)?|与)\s*(?:历史|过往|往期|早前|此前|去年|上年|前年|上期|前期|前次|上次|上月|前月|上季度|前季)(?:同期)?(?:相比)?(?:上涨|下降|增长|上升|下跌|回落|持平)?/gi,
      '',
    );
}

function ppiCandidateModalityContext(text, sentenceStart, ppiStart, valueStart) {
  const rawContext = text.slice(sentenceStart, valueStart);
  const ppiOffset = Math.max(0, ppiStart - sentenceStart);
  const beforePpi = rawContext.slice(0, ppiOffset);
  const transitions = [...beforePpi.matchAll(/(?:但|然而|不过|与此同时|随后|之后|此后)/g)];
  const transitionScopeStart = transitions.length > 0
    ? transitions[transitions.length - 1].index + transitions[transitions.length - 1][0].length
    : 0;
  let unrelatedSubjectScopeStart = 0;
  let clauseStart = 0;
  for (const delimiter of beforePpi.matchAll(/[，,]/g)) {
    const clause = beforePpi.slice(clauseStart, delimiter.index);
    if (
      lastNonActualModalityEnd(ppiModalityText(clause)) >= 0
      && !PPI_RELEASE_PATTERN.test(clause)
      && (PPI_UNRELATED_SUBJECT_PATTERN.test(clause) || /[+-]?\d+(?:\.\d+)?\s*%/.test(clause))
    ) unrelatedSubjectScopeStart = delimiter.index + delimiter[0].length;
    clauseStart = delimiter.index + delimiter[0].length;
  }
  const scopeStart = Math.max(transitionScopeStart, unrelatedSubjectScopeStart);
  return ppiModalityText(rawContext.slice(scopeStart));
}

function suffixLabelsCurrentValue(suffix) {
  const boundedSuffix = String(suffix).slice(0, 64).split(/[。！？!?；;\n]/, 1)[0];
  const suffixContent = boundedSuffix.replace(/^[\s（(【\[,，:：\-—]+/, '');
  if (/^(?:(?:略|稍|小幅|大幅|明显|显著|远|更)?\s*(?:低于|高于|逊于|好于|超(?:出)?|强于|弱于|不及|符合|接近|较|相比(?:于)?|超))\s*(?:市场)?(?:预期|前值)/i.test(suffixContent)) {
    return false;
  }
  if (/^(?:仅|只)?(?:作|用于)?(?:历史|过往)(?:对照|比较|参考|回顾)/i.test(suffixContent)) {
    return true;
  }
  const unpublishedMatch = suffixContent.match(PPI_UNPUBLISHED_STATE_PATTERN);
  if (unpublishedMatch) {
    const unpublishedPrefix = suffixContent.slice(0, unpublishedMatch.index).trim();
    const unpublishedTail = suffixContent.slice(unpublishedMatch.index + unpublishedMatch[0].length);
    const directPrefix = /^(?:(?:该|本次|上述|前述|这一)?(?:数据|数字|数值|结果|实际值)?|官方(?:数据)?)$/i;
    return directPrefix.test(unpublishedPrefix)
      && !PPI_UNRELATED_SUBJECT_PATTERN.test(unpublishedTail);
  }
  const directRole = suffixContent.match(
    /^(?:[（(]\s*)?(?:(仅为|只是|仅是|仍为|仍属|为|是|系|属|属于|标注为)\s*)?(?:(市场|机构|分析师|经济学家|路透|彭博)(?:调查)?\s*)?(预测值?|预期值?|预估值?|估计值?|一致预期|一致预估|前值|预料|估算|测算结果|市场共识|调查预估|调查中值|调查中位数|调查所得共识值?|共识值|中位数)/i,
  );
  if (!directRole) return false;
  const relation = directRole[1] || '';
  const remainder = suffixContent
    .slice(directRole[0].length)
    .replace(/^[\s）)】\],，:：\-—]*(?:则\s*)?(?:为\s*)?/, '');
  if (/[+-]?\d+(?:\.\d+)?\s*%/.test(remainder)) return false;
  if (/^(?:(?:已|被)\s*)?(?:修正(?:为|至)?|同步(?:上修|下修)|上修|下修)/.test(remainder)) {
    return false;
  }
  if (/(?:落空|之外|以外|偏离)[^。！？!?；;，,\n]{0,16}(?:实际|意外|结果|数据)/i.test(remainder)) {
    return false;
  }
  if (relation) return true;
  return /^(?:区间)?\s*[）)】\]]?\s*$/i.test(remainder);
}

function ppiScopeMatchesExpectedIdentity(text, row, expectedIdentity) {
  if (!expectedIdentity) return true;
  const raw = String(text);
  if (/(?:下一期|下期|下一次|下月|次月|下季度|未来一期)/i.test(raw)) return false;
  const anaphoricPeriod = raw.match(new RegExp(
    `(?:(20\\d{2})\\s*年\\s*)?(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?[^。！？!?；;，,\\n]{0,12}(?:该|这一|上述|前述|本次)?(?:项?数据|数字|数值|结果|值|指标)`,
    'i',
  ));
  if (anaphoricPeriod) {
    const period = normalizeReportedPeriod(anaphoricPeriod[1], anaphoricPeriod[2], row);
    if (period && period !== expectedIdentity.reported_period) return false;
  }
  const comparisonFree = raw
    .replace(PPI_COMPARISON_PREFIX_PATTERN, '')
    .replace(/(?:与|较)\s*20\d{2}\s*年(?:同期)?(?:相比|比较)?/gi, '')
    .replace(/相比(?:于)?\s*20\d{2}\s*年(?:同期)?/gi, '');
  const periods = ppiReportedPeriods(comparisonFree, row);
  if (periods.length > 0 && !periods.includes(expectedIdentity.reported_period)) return false;
  const expectedYear = Number(String(expectedIdentity.reported_period).slice(0, 4));
  const explicitYears = [...comparisonFree.matchAll(/(20\d{2})\s*年/g)]
    .map((match) => Number(match[1]));
  if (explicitYears.length > 0 && !explicitYears.includes(expectedYear)) return false;
  if (PPI_RELEASE_PATTERN.test(comparisonFree)) {
    const jurisdictions = jurisdictionsIn(comparisonFree);
    if (jurisdictions.length > 0 && !jurisdictions.includes(expectedIdentity.jurisdiction)) return false;
  }
  return true;
}

function hasPpiEventContradiction(text, row, expectedIdentity) {
  const ppiSubject = `(?:${PPI_RELEASE_PATTERN.source})`;
  const anaphoricSubject = '(?:(?:该|此|这一|这个|上述|前述|所述|本次)(?:项)?(?:数据|数字|数值|数|结果|值|读数|百分比|比例|指标|年率|月率|同比|环比)|所述\s*[+-]?\d+(?:\.\d+)?\s*%|其|本报告中(?:的)?(?:数据|数字|数值|结果|值|读数|百分比|年率|月率|同比|环比)?|这(?!家|些|类|款|套|名|位|个(?:公司|企业|平台|产品)))';
  const genericDataSubject = '(?:实际数据|官方数据|数据|数字|数值|结果)';
  const predictionState = '(?:预测值?|预期值?|预估值?|估计值?|预料|估算|测算结果|市场共识|调查预估|一致预期|一致预估|前值|调查中值|调查中位数|调查所得共识值?|共识值|中位数)';
  const relation = '(?:仅为|只是|仅是|仍为|仍属|为|是|系|属|属于|标注为|来自)';
  const broadUnpublished = new RegExp(
    `(?:${PPI_UNPUBLISHED_STATE_SOURCE}|(?:(?:尚|仍|还|暂)?\\s*(?:未|无)|没有)[^。！？!?；;，,\\n]{0,18}(?:公布|发布|披露|出炉)|(?:尚待|仍待|有待|等待|待|即将|将于)[^。！？!?；;，,\\n]{0,18}(?:公布|发布|披露|出炉)|(?:官方)?(?:数据|结果|数值|公布值|发布值)?\\s*(?:尚无|仍无|暂无|没有)\\s*(?:数据|结果|数值|公布值|发布值))`,
    'i',
  );
  const referencedPrediction = new RegExp(
    `(?:${ppiSubject}|${anaphoricSubject}|${genericDataSubject})[^。！？!?；;，,\\n]{0,36}${relation}\\s*(?:一个|一项|初步)?\\s*(?:(?:市场|机构|分析师|经济学家|模型|路透|彭博)\\s*)?${predictionState}`,
    'i',
  );
  const predictionSource = new RegExp(
    `(?:${ppiSubject}|${anaphoricSubject}|${genericDataSubject})[^。！？!?；;，,\\n]{0,36}(?:来自|源自)\\s*(?:(?:市场|机构|分析师|经济学家|模型|调查)[^。！？!?；;，,\\n]{0,12}(?:预测|预估|估算|共识)|(?:分析师|经济学家|模型|调查)[^。！？!?；;，,\\n]{0,18}(?:而非|并非|不是)\\s*(?:官方)?(?:公布|发布|披露))`,
    'i',
  );
  const notActual = new RegExp(
    `(?:${ppiSubject}|${anaphoricSubject}|${genericDataSubject})[^。！？!?；;，,\\n]{0,24}(?:并非|不是)\\s*实际(?:数据|值|结果)?`,
    'i',
  );
  const numericPrediction = new RegExp(
    `^(?:(?:其中|上述|前述|该|这一|本报告中(?:的)?)\\s*)?([+-]?\\d+(?:\\.\\d+)?)\\s*%[^。！？!?；;，,\\n]{0,12}${relation}\\s*(?:一个|一项|初步)?\\s*(?:(?:市场|机构|分析师|经济学家|模型|路透|彭博)(?:调查)?\\s*)?${predictionState}`,
    'i',
  );
  const standaloneUnpublished = new RegExp(
    `^(?:(?:截至(?:目前|发稿)|目前)\\s*)?(?:官方\\s*)?(?:(?:尚|仍|还|暂)?\\s*(?:未|无)|没有|尚待|仍待|有待|等待|待)[^。！？!?；;，,\\n]{0,12}(?:公布|发布|披露|出炉)\\s*$`,
    'i',
  );
  const standaloneForecastDisclaimer = /^(?:(?:该|上述|前述|本次)?(?:数据|数字|数值|数|结果|值)?\s*)?(?:仅供|只供|用于|只是|仅为)?\s*(?:预测|预估|估算|测算)(?:参考|用途|结果|值)?(?:\s*(?:并非|不是)\s*实际(?:数据|值|结果)?)?$/i;
  const standaloneNotActual = /^(?:(?:该|上述|前述|本次)?(?:数据|数字|数值|数|结果|值)?\s*)?(?:并非|不是)\s*实际(?:数据|值|结果)?$/i;
  const periodTransition = new RegExp(
    `(?:[。！？!?；;，,\\n]+|但|然而|不过|(?:而|同时|且|并且|以及)(?=(?:(?:下一期|下期|下一次|下月|次月|下季度|未来一期)|(?:${PPI_JURISDICTION_SOURCE}\\s*)?(?:(?:20\\d{2})\\s*年\\s*)?(?:1[0-2]|0?[1-9]|十[一二]?|[一二三四五六七八九])\\s*月)))`,
  );
  const clauses = String(text)
    .split(periodTransition)
    .map((clause) => clause.trim())
    .filter(Boolean);
  let lastPpiCandidateValue = null;
  let referenceState = null;
  for (const clause of clauses) {
    const hasPpi = PPI_RELEASE_PATTERN.test(clause) && !PPI_FALSE_ENTITY_PATTERN.test(clause);
    const scopeMatches = ppiScopeMatchesExpectedIdentity(clause, row, expectedIdentity);
    const hasAnaphor = new RegExp(anaphoricSubject, 'i').test(clause);
    const genericSubjectAtStart = new RegExp(`^${genericDataSubject}`, 'i').test(clause);
    const isUnrelated = PPI_UNRELATED_SUBJECT_PATTERN.test(clause) && !hasPpi && !hasAnaphor;
    const numericMatch = clause.match(numericPrediction);
    const rebindTargetsNextPeriod = /(?:下一期|下期|下一次|下月|次月|下季度|未来一期)[^。！？!?；;，,\n]{0,20}(?:该|这一|上述|前述)?(?:项)?(?:数据|数字|数值|结果|值|指标)|(?:对应|属于|指向|是|为)[^。！？!?；;，,\n]{0,20}(?:下一期|下期|下一次|下月|次月|下季度|未来一期)/i.test(clause);
    const hasExplicitPeriodReference = (hasAnaphor || genericSubjectAtStart) && (
      /(?:20\d{2})\s*年/i.test(clause)
      || new RegExp(`(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?`, 'i').test(clause)
    );
    let clauseReferenceState = referenceState;
    if (hasPpi) clauseReferenceState = scopeMatches ? 'current' : 'other_period';
    else if (rebindTargetsNextPeriod || /(?:下一期|下期|下一次|下月|次月|下季度|未来一期)/i.test(clause)) {
      clauseReferenceState = 'next_period';
    } else if (hasExplicitPeriodReference) {
      clauseReferenceState = scopeMatches ? 'current' : 'other_period';
    } else if (isUnrelated) clauseReferenceState = 'unrelated';
    const clauseTargetsCurrent = clauseReferenceState === 'current';
    const numericRefutesLast = Boolean(
      clauseTargetsCurrent
      && numericMatch
      && lastPpiCandidateValue !== null
      && Number(numericMatch[1]) === lastPpiCandidateValue
    );
    const anaphorRefersToCurrent = hasAnaphor && clauseTargetsCurrent;
    const referenced = (hasPpi && scopeMatches)
      || anaphorRefersToCurrent
      || (genericSubjectAtStart && clauseTargetsCurrent);
    const unavailable = broadUnpublished.test(clause);
    const explicitIdentityRebind = referenceState === 'current'
      && !rebindTargetsNextPeriod
      && /^(?:实际|本次|该值|该结果|这)?\s*(?:对应|属于|指向|是|为)/i.test(clause);
    const sourceIdentityCandidate = referenceState === 'current'
      ? clause.match(new RegExp(
        `^(?:(?:${anaphoricSubject}|${genericDataSubject})\\s*)?(?:实际\\s*)?(?:来自|源自)\\s*(${PPI_JURISDICTION_SOURCE})`,
        'i',
      ))
      : null;
    const sourceIdentityRebind = sourceIdentityCandidate
      && !/(?:媒体|转载|报道|消息|网站|通讯社)/i.test(
        clause.slice(sourceIdentityCandidate.index + sourceIdentityCandidate[0].length),
      )
      ? sourceIdentityCandidate
      : null;
    if (
      sourceIdentityRebind
      && expectedIdentity
      && sourceIdentityRebind[1] !== expectedIdentity.jurisdiction
    ) return true;
    const postIdentityReference = referenceState === 'current' && (
      anaphorRefersToCurrent
      || genericSubjectAtStart
      || explicitIdentityRebind
      || Boolean(sourceIdentityRebind)
    );
    // A post-value identity correction belongs to the preceding candidate.
    // If it changes that candidate's period, year, or jurisdiction, it is a
    // contradiction. A separately scoped next-period anaphor is not.
    if (explicitIdentityRebind && !scopeMatches) return true;
    if (clauseTargetsCurrent && postIdentityReference && expectedIdentity) {
      const expectedYear = Number(String(expectedIdentity.reported_period).slice(0, 4));
      const years = [...clause.matchAll(/(20\d{2})\s*年/g)].map((match) => Number(match[1]));
      if (years.length > 0 && !years.includes(expectedYear)) return true;
      const monthMatch = clause.match(new RegExp(`(${MONTH_TOKEN_PATTERN_SOURCE})\\s*月(?:份)?`, 'i'));
      if (monthMatch) {
        const period = normalizeReportedPeriod(null, monthMatch[1], row);
        if (period && period !== expectedIdentity.reported_period) return true;
      }
      const jurisdictions = jurisdictionsIn(clause);
      const disseminationSource = /(?:来自|源自)[^。！？!?；;，,\n]{0,16}(?:媒体|转载|报道|消息|网站|通讯社)/i.test(clause);
      if (
        jurisdictions.length > 0
        && !jurisdictions.includes(expectedIdentity.jurisdiction)
        && !disseminationSource
      ) return true;
      if (OTHER_MACRO_INDICATOR_PATTERN.test(clause) && !/^\s*(?:实际|官方|本次)\s*数据/i.test(clause)) {
        return true;
      }
      const actualResultConfirmation = /^(?:该(?:值|数据|结果)?\s*)?(?:是|为|系)\s*(?:(?:市场)?(?:预期|预测)[^。！？!?；;，,\n]{0,24}(?:落空|之外|以外|偏离)[^。！？!?；;，,\n]{0,16})?(?:实际(?:数据|值|结果)|意外结果)$/i.test(clause);
      const metricOwner = clause.match(new RegExp(
        `^(?:(?:实际|本次)\\s*)?(?:(?:${anaphoricSubject})\\s*)?(?:对应|属于|指向|是|为)\\s*([^。！？!?；;，,\\n]{1,20}?)(?:数据|指标|指数|价格|费用|收益率|回报率)`,
        'i',
      ));
      if (metricOwner && !actualResultConfirmation) {
        const ownerJurisdictions = jurisdictionsIn(metricOwner[1]);
        const publisherResidue = metricOwner[1]
          .replace(expectedIdentity.jurisdiction, '')
          .replace(/(?:国家)?(?:劳工部|统计局|统计机构|政府部门|官方)/gi, '')
          .replace(/\s/g, '');
        if (
          (ownerJurisdictions.length === 0 || (
            ownerJurisdictions.length === 1
            && ownerJurisdictions[0] === expectedIdentity.jurisdiction
          ))
          && publisherResidue === ''
        ) {
          // A matching official publisher describes provenance, not a metric
          // identity change.
        } else {
        const ownerResidue = metricOwner[1]
          .replace(/(?:实际|官方|本次|该|这一|上述|前述|PPI|生产者|物价|价格)/gi, '')
          .replace(/\s/g, '');
        if (ownerResidue !== '') return true;
        }
      }
    }
    if (clauseTargetsCurrent && (
      ((referenced || (
        referenceState === 'current'
        && standaloneUnpublished.test(clause)
      )) && unavailable)
      || referencedPrediction.test(clause)
      || predictionSource.test(clause)
      || notActual.test(clause)
      || numericRefutesLast
      || (
        referenceState === 'current'
        && standaloneForecastDisclaimer.test(clause)
      )
      || (
        referenceState === 'current'
        && standaloneNotActual.test(clause)
      )
    )) return true;

    const ppiValues = hasPpi
      ? [...clause.matchAll(new RegExp(PPI_ACTUAL_VALUE_PATTERN.source, 'gi'))]
      : [];
    if (clauseTargetsCurrent && ppiValues.length > 0) {
      const percentages = [...ppiValues[ppiValues.length - 1][0].matchAll(/([+-]?\d+(?:\.\d+)?)\s*%/g)];
      if (percentages.length > 0) lastPpiCandidateValue = Number(percentages[percentages.length - 1][1]);
    }
    if (
      hasPpi
      || hasAnaphor
      || genericSubjectAtStart
      || isUnrelated
      || numericMatch
      || rebindTargetsNextPeriod
      || standaloneUnpublished.test(clause)
      || standaloneForecastDisclaimer.test(clause)
      || standaloneNotActual.test(clause)
    ) referenceState = clauseReferenceState;
  }
  return false;
}

function ppiCandidateIdentityMatches(candidate, row, expectedIdentity) {
  if (!expectedIdentity) return true;
  const scope = String(candidate.localScope || '');
  if (hasUnresolvedRelativePpiPeriod(scope)) return false;
  const periods = ppiReportedPeriods(scope, row);
  if (periods.length > 0 && (
    periods.length !== 1
    || periods[0] !== expectedIdentity.reported_period
  )) return false;
  const candidateOwners = jurisdictionOccurrences(String(candidate.prePpiScope || ''))
    .filter((item) => ppiIdentityBridgeIsCompatible(
      String(candidate.prePpiScope || '').slice(item.end),
    ));
  if (candidateOwners.length > 1) return false;
  if (
    candidateOwners.length === 1
    && candidateOwners[0].name !== expectedIdentity.jurisdiction
  ) return false;
  const comparisonFree = scope
    .replace(PPI_COMPARISON_PREFIX_PATTERN, '')
    .replace(/(?:与|较)\s*20\d{2}\s*年(?:同期)?(?:相比|比较)?/gi, '')
    .replace(/相比(?:于)?\s*20\d{2}\s*年(?:同期)?/gi, '');
  const expectedYear = Number(String(expectedIdentity.reported_period).slice(0, 4));
  const explicitYears = [...comparisonFree.matchAll(/(20\d{2})\s*年/g)]
    .map((match) => Number(match[1]));
  if (explicitYears.length > 0 && !explicitYears.includes(expectedYear)) return false;
  const reportContextYears = [...String(candidate.prePpiScope || '').matchAll(
    /(20\d{2})\s*年(?:的)?[^。！？!?；;，,\n]{0,12}(?:报告|数据|记录|资料|发布)/gi,
  )].map((match) => Number(match[1]));
  return reportContextYears.length === 0 || reportContextYears.includes(expectedYear);
}

function ppiCandidateIsHistoricalReference(candidate, text, row, expectedIdentity) {
  if (!expectedIdentity) return false;
  const scope = String(candidate.localScope || '');
  const periods = ppiReportedPeriods(scope, row);
  const expectedYear = Number(String(expectedIdentity.reported_period).slice(0, 4));
  const explicitYears = [...scope.matchAll(/(20\d{2})\s*年/g)].map((match) => Number(match[1]));
  const explicitTimeMismatch = (
    (periods.length > 0 && !periods.includes(expectedIdentity.reported_period))
    || (explicitYears.length > 0 && !explicitYears.includes(expectedYear))
  );
  if (!explicitTimeMismatch) return false;
  const tail = String(text).slice(candidate.valueEnd, candidate.sentenceEnd);
  return /(?:历史|往期|旧值|对照|对比|比较|参考|回顾|基数|基期)/i.test(tail);
}

function ppiActualCandidates(text, maxChars = 32, { requireEvidence = false } = {}) {
  const ppiIndicators = [...text.matchAll(new RegExp(PPI_RELEASE_PATTERN.source, 'gi'))]
    .filter((match) => !PPI_FALSE_ENTITY_PATTERN.test(
      text.slice(match.index, match.index + match[0].length + 16),
    ))
    .map((match) => ({ kind: 'ppi', start: match.index, end: match.index + match[0].length }));
  const otherIndicators = [...text.matchAll(new RegExp(OTHER_MACRO_INDICATOR_PATTERN.source, 'gi'))]
    .map((match) => ({ kind: 'other', start: match.index, end: match.index + match[0].length }));
  const indicators = [...ppiIndicators, ...otherIndicators];
  const values = [...text.matchAll(new RegExp(PPI_ACTUAL_VALUE_PATTERN.source, 'gi'))];
  const candidates = [];
  for (const value of values) {
    const valueStart = value.index;
    const valueEnd = valueStart + value[0].length;
    if (suffixLabelsCurrentValue(text.slice(valueEnd, valueEnd + 48))) continue;
    const nearby = indicators
      .filter((indicator) => indicator.end <= valueStart)
      .map((indicator) => ({
        ...indicator,
        distance: valueStart - indicator.end,
      }))
      .filter((indicator) => indicator.distance <= maxChars)
      .sort((left, right) => left.distance - right.distance);
    if (nearby.length === 0) continue;
    const nearestDistance = nearby[0].distance;
    const nearestKinds = new Set(
      nearby.filter((indicator) => indicator.distance === nearestDistance).map((indicator) => indicator.kind),
    );
    if (nearestKinds.size !== 1 || !nearestKinds.has('ppi')) continue;
    const nearestPpi = nearby.find(
      (indicator) => indicator.kind === 'ppi' && indicator.distance === nearestDistance,
    );
    if (!nearestPpi) continue;
    const ownerGap = text.slice(nearestPpi.end, valueStart);
    if (!ppiValueOwnerGapIsCompatible(ownerGap)) continue;

    // Resolve fact modality across the complete sentence, not a fixed character
    // window. A later strong publication cue resets an earlier forecast/prior
    // cue; otherwise the candidate value remains non-actual.
    const sentencePrefix = text.slice(0, valueStart);
    const sentenceBoundaries = [...sentencePrefix.matchAll(/[。！？!?；;\n]/g)];
    const sentenceStart = sentenceBoundaries.length > 0
      ? sentenceBoundaries[sentenceBoundaries.length - 1].index + 1
      : 0;
    const modalityContext = ppiCandidateModalityContext(
      text,
      sentenceStart,
      nearestPpi.start,
      valueStart,
    );
    const lastNonActual = lastNonActualModalityEnd(modalityContext);
    const lastStrongActual = lastOwnedStrongActualEnd(modalityContext);
    const explicitActualRole = /^(?:实际值?|公布值|发布值)/i.test(value[0].trim());
    if (!explicitActualRole && lastNonActual > lastStrongActual) continue;
    const assertiveValue = /(?:实际|录得|为|报|升至|降至|上升至|下降至|增长|下降|上升|上涨|下跌|回落|达|达到|涨幅为|降幅为|增幅为|涨|降|增|减|增加|减少|持平|修正为)/i.test(value[0]);
    const sentenceTail = text.slice(valueEnd).split(/[。！？!?；;\n]/, 1)[0];
    const normalizedTail = sentenceTail.replace(/^[\s，,：:（）()【】\[\]\-—]+/, '');
    const postPublicationCue = (
      /^(?:(?:该|本次|官方)?(?:数据|结果|数值)?\s*)?(?:已|已经)?\s*(?:正式)?\s*(?:公布|发布|披露)/i.test(normalizedTail)
      || /^(?:已\s*)?由\s*(?:美国)?(?:劳工部|政府部门|统计机构|官方)\s*(?:正式)?\s*(?:公布|发布|披露)/i.test(normalizedTail)
    );
    const postActualConfirmation = /^(?:是|为)\s*(?:市场)?(?:预期|预测)[^。！？!?；;，,\n]{0,20}(?:落空|之外|以外|偏离)[^。！？!?；;，,\n]{0,16}(?:实际数据|实际结果|意外结果)/i.test(normalizedTail);
    const benchmarkEvidence = /^(?:(?:(?:市场|机构|路透|彭博)\s*)?(?:预期(?:值|中值|中位数)?|预测值?|预估值?|调查中值|调查中位数|前值)(?:则)?\s*(?:为|约为|录得|报)?\s*[+-]?\d+(?:\.\d+)?\s*%|(?:(?:略|稍|小幅|大幅|明显|显著|远|更)?\s*(?:低于|高于|逊于|好于|超(?:出)?|强于|弱于|不及|符合|接近|较|相比(?:于)?|超))\s*(?:市场)?(?:预期|前值)|[+-]?\d+(?:\.\d+)?\s*%\s*(?:为|是|系)\s*(?:市场)?(?:预期值?|预测值?|前值))$/i.test(normalizedTail);
    if (
      requireEvidence
      && !assertiveValue
      && lastStrongActual < 0
      && !postPublicationCue
      && !postActualConfirmation
      && !benchmarkEvidence
    ) continue;

    const sentenceTailIndex = text.slice(valueEnd).search(/[。！？!?；;\n]/);
    const sentenceEnd = sentenceTailIndex >= 0 ? valueEnd + sentenceTailIndex : text.length;
    const beforePpi = text.slice(sentenceStart, nearestPpi.start);
    const commaMatches = [...beforePpi.matchAll(/[，,]/g)];
    const localStart = commaMatches.length > 0
      ? sentenceStart + commaMatches[commaMatches.length - 1].index + 1
      : sentenceStart;
    const afterValue = text.slice(valueEnd, sentenceEnd);
    const nextComma = afterValue.search(/[，,]/);
    const localEnd = nextComma >= 0 ? valueEnd + nextComma : sentenceEnd;
    candidates.push({
      value,
      valueStart,
      valueEnd,
      ppi: nearestPpi,
      sentenceStart,
      sentenceEnd,
      prePpiScope: text.slice(sentenceStart, nearestPpi.start),
      localScope: text.slice(localStart, localEnd),
    });
  }
  return candidates;
}

function compatiblePpiActualSegment(segment, row, expectedIdentity) {
  if (!PPI_RELEASE_PATTERN.test(segment)) return false;
  return ppiActualCandidates(segment, 32, { requireEvidence: true })
    .some((candidate) => ppiCandidateIdentityMatches(candidate, row, expectedIdentity));
}

function isPpiBodyIdentityCompatible(body, row, expectedIdentity) {
  if (!expectedIdentity) return true;
  const bodyText = String(body);
  const actualCandidates = ppiActualCandidates(bodyText, 32, { requireEvidence: true });
  return actualCandidates.every(
    (candidate) => (
      ppiCandidateIdentityMatches(candidate, row, expectedIdentity)
      || ppiCandidateIsHistoricalReference(candidate, bodyText, row, expectedIdentity)
    ),
  );
}

function ppiTitleIdentity(row) {
  const title = String(row?.title || '');
  if (
    !PPI_RELEASE_PATTERN.test(title)
    || PPI_FALSE_ENTITY_PATTERN.test(title)
    || PPI_POST_VALUE_FALSE_IDENTITY_PATTERN.test(title)
  ) return null;
  const jurisdictions = ppiTitleJurisdictions(row);
  const reportedPeriod = explicitPpiReportedPeriod(row);
  if (jurisdictions.length !== 1 || !reportedPeriod) return null;
  return { jurisdiction: jurisdictions[0], reported_period: reportedPeriod };
}

function hasInvertedPpiActualRelease(title, row, expectedIdentity) {
  const match = String(title).match(PPI_INVERTED_ACTUAL_RELEASE_PATTERN);
  if (!match) return false;
  const prefix = String(title).slice(0, match.index);
  if (lastNonActualModalityEnd(ppiModalityText(prefix)) >= 0) return false;
  return ppiScopeMatchesExpectedIdentity(title, row, expectedIdentity);
}

function isExplicitPpiDataRelease(row, expectedIdentity = null) {
  const title = String(row?.title || '');
  const body = String(row?.body || '');
  // The event itself must be PPI-led. The body may prove an actual release,
  // but it cannot provide or replace the event identity.
  if (!PPI_RELEASE_PATTERN.test(title)) return false;
  if (
    PPI_CURRENT_FALSE_IDENTITY_PATTERN.test(body)
    || PPI_POST_VALUE_FALSE_IDENTITY_PATTERN.test(`${title}\n${body}`)
  ) return false;
  if (
    /(?:更正|纠正|报道有误|误报)/i.test(body)
    && OTHER_MACRO_INDICATOR_PATTERN.test(body)
    && /(?:而非|并非|不是)\s*(?:本次)?\s*(?:PPI|生产者(?:价格|物价)指数)/i.test(body)
  ) return false;
  if (expectedIdentity) {
    const officialSource = body.match(new RegExp(
      `(?:^|[。！？!?；;，,\\n])\\s*(?:数据)?来源\\s*[:：]?\\s*(${PPI_JURISDICTION_SOURCE})(?:国家)?(?:统计局|劳工部|政府部门|官方)`,
      'i',
    ));
    if (officialSource && officialSource[1] !== expectedIdentity.jurisdiction) return false;
  }
  if (!isPpiBodyIdentityCompatible(body, row, expectedIdentity)) return false;
  if (hasPpiEventContradiction(`${title}\n${body}`, row, expectedIdentity)) return false;
  if (hasInvertedPpiActualRelease(title, row, expectedIdentity)) return true;
  if (ppiActualCandidates(title).some(
    (candidate) => ppiCandidateIdentityMatches(candidate, row, expectedIdentity),
  )) return true;
  return body
    .split(/[。！？!?；;\n]+/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .some((segment) => compatiblePpiActualSegment(segment, row, expectedIdentity));
}

function isExplicitGdpMacro(title) {
  if (/国内生产总值/i.test(title)) return true;
  return (
    GDP_TOKEN_PATTERN.test(title)
    && !GDP_FALSE_ENTITY_PATTERN.test(title)
    && (GDP_MACRO_CONTEXT_PATTERN.test(title) || GDP_ACTUAL_VALUE_PATTERN.test(title))
  );
}

/**
 * Return a conservative event-family identity only when the row is clearly a
 * PPI data release and both jurisdiction and reported period are explicit.
 * Ambiguous PPI commentary stays ungrouped rather than risking a false merge.
 */
export function identifyEventFamily(row) {
  const identity = ppiTitleIdentity(row);
  if (!identity || !isExplicitPpiDataRelease(row, identity)) return null;
  const { jurisdiction, reported_period: reportedPeriod } = identity;

  return {
    key: `macro_release:ppi:${jurisdiction}:${reportedPeriod}`,
    kind: 'macro_release',
    indicator: 'PPI',
    jurisdiction,
    reported_period: reportedPeriod,
  };
}

function recencyScore(row, nowMs, windowHours) {
  const ageHours = Math.max(0, (nowMs - row.epoch_ms) / 3600000);
  return Math.max(0, Math.round((windowHours - ageHours) * 5));
}

function chooseBucket(signals, reasons) {
  if (signals.isMemeOnly) {
    reasons.push('cap:Meme/非BTC直接相关');
    return 'meme_other';
  }
  if (signals.isSecondarySectorStory) {
    reasons.push('cap:非BTC行业叙事');
    return 'secondary_sector';
  }
  if (signals.geopolitics || signals.macroPolicy) {
    return 'macro_policy';
  }
  if (signals.regulatoryPolicy) {
    return 'regulatory_policy';
  }
  if (signals.btcEtfFlow) {
    return 'btc_etf_flow';
  }
  if (signals.cryptoMarketStructure) {
    return 'crypto_market_structure';
  }
  if (signals.exchangeSecurityWhale) {
    return 'exchange_security_whale';
  }
  if (signals.hasEth || signals.institutionCrypto) {
    return 'eth_sector';
  }
  return 'other';
}

function directnessLabel(directness) {
  if (directness >= 3) return 'direct_btc_or_btc_etf';
  if (directness === 2) return 'direct_macro_or_regulatory';
  if (directness === 1) return 'crypto_adjacent';
  return 'low_btc_relevance';
}

export function classifyImpact(row, nowMs, windowHours = DEFAULT_WINDOW_HOURS) {
  const title = row.title || '';
  const body = row.body || '';
  const text = `${title}\n${body}`;
  const directBtcText = text.replace(PATTERNS.btcComparison, '');
  const reasons = [];

  const hasBtc = has(PATTERNS.btc, directBtcText);
  const hasEth = has(PATTERNS.eth, text);
  const hasCryptoContext = hasBtc || hasEth || has(PATTERNS.cryptoContext, text);
  const hasMeme = has(PATTERNS.meme, text);
  const isPersonalStory = has(PATTERNS.personalStory, title);
  const isSpeculativePositionStory = has(PATTERNS.speculativePositionTitle, title);
  const hasNonCryptoSectorTitle = has(PATTERNS.nonCryptoSectorTitle, title) && !has(PATTERNS.btc, title);
  const btcEtfFlow = has(PATTERNS.btcEtfFlow, text);
  const macroLiquidity = (
    hasNearby(/流动性/i, PATTERNS.macroLiquidityContext, text)
    || hasNearby(/流动性/i, PATTERNS.policyRate, text)
  );
  const macroDollar = has(PATTERNS.macroDollar, title) || has(PATTERNS.macroDollarBody, text);
  const ppiIdentity = ppiTitleIdentity(row);
  const ppiDataRelease = Boolean(ppiIdentity && isExplicitPpiDataRelease(row, ppiIdentity));
  const gdpMacro = isExplicitGdpMacro(title);
  const directMacroPolicy = (
    has(PATTERNS.macroCore, title)
    || has(PATTERNS.policyRate, title)
    || ppiDataRelease
    || gdpMacro
    || macroDollar
    || macroLiquidity
  );
  const directGeopolitics = isDirectGeopoliticalEvent(row);
  const directRegulatoryPolicy = (
    has(PATTERNS.regulatory, title)
    || (hasCryptoContext && has(PATTERNS.regulatory, text))
  );
  const regulatoryCryptoContext = has(PATTERNS.regulatoryCryptoContext, text);
  const directCryptoRegulatoryPolicy = directRegulatoryPolicy && (regulatoryCryptoContext || btcEtfFlow);
  const hasDirectTierOneSignal = directMacroPolicy || directGeopolitics || directCryptoRegulatoryPolicy;
  const isMemeOnly = hasMeme && !hasBtc && !btcEtfFlow;
  // Explicit Tier1 facts outrank incidental non-crypto sector words. Personal
  // retrospectives and speculative-position headlines remain capped.
  const isSecondarySectorStory = (
    isPersonalStory
    || (hasNonCryptoSectorTitle && !hasDirectTierOneSignal)
  ) && !hasBtc && !btcEtfFlow;
  const tierOnePolicyEligible = !isPersonalStory && !isSpeculativePositionStory;
  const macroPolicy = tierOnePolicyEligible && directMacroPolicy;
  const geopolitics = tierOnePolicyEligible && directGeopolitics;
  const regulatoryPolicy = tierOnePolicyEligible && directCryptoRegulatoryPolicy;
  if (
    hasNonCryptoSectorTitle
    && hasDirectTierOneSignal
    && !isPersonalStory
    && !isSpeculativePositionStory
  ) {
    reasons.push('override:明确Tier1信号优先于行业词');
  }
  const cryptoMarketStructure = !isMemeOnly && hasCryptoContext && (
    has(PATTERNS.marketStructure, text)
    || has(PATTERNS.liquidation, text)
  );
  const exchangeSecurityWhale = !isMemeOnly && hasCryptoContext && (
    has(PATTERNS.exchangeEvent, text)
    || has(PATTERNS.security, text)
    || has(PATTERNS.whale, text)
  );
  const institutionCrypto = hasCryptoContext && has(PATTERNS.institutionCrypto, text);

  const signals = {
    hasBtc,
    hasEth,
    hasCryptoContext,
    isMemeOnly,
    isSecondarySectorStory,
    macroPolicy,
    geopolitics,
    regulatoryPolicy,
    btcEtfFlow,
    cryptoMarketStructure,
    exchangeSecurityWhale,
    institutionCrypto,
  };

  const priorityBucket = chooseBucket(signals, reasons);
  const bucket = BUCKETS[priorityBucket];
  const category = geopolitics && !macroPolicy ? '地缘政治' : bucket.category;
  let score = bucket.base;

  reasons.push(`bucket:${priorityBucket}`);
  if (macroPolicy) reasons.push('T1:货币政策');
  if (geopolitics) reasons.push('T1:地缘政治');
  if (regulatoryPolicy) reasons.push('T1:监管立法');
  if (btcEtfFlow) reasons.push('BTC ETF/资金流直接相关');
  if (cryptoMarketStructure) reasons.push('市场结构/链上直接相关');
  if (exchangeSecurityWhale) reasons.push('交易所/安全/鲸鱼事件');
  if (hasBtc) {
    score += 220;
    reasons.push('BTC相关');
  }
  if (hasEth) {
    score += 90;
    reasons.push('ETH相关');
  }
  if (macroPolicy || geopolitics) score += 160;
  if (regulatoryPolicy) score += 150;
  if (btcEtfFlow) score += 180;
  if (has(PATTERNS.liquidation, text) && (hasBtc || hasCryptoContext) && !isMemeOnly) {
    score += 120;
    reasons.push('杠杆/清算风险');
  }
  if (has(PATTERNS.security, text) && hasCryptoContext) {
    score += 100;
    reasons.push('安全/监管冲击');
  }
  if (has(PATTERNS.quantified, text)) {
    const numericScore = priorityBucket === 'secondary_sector' || priorityBucket === 'meme_other' ? 10 : 60;
    score += numericScore;
    reasons.push(`量化规模+${numericScore}`);
  }

  const recent = recencyScore(row, nowMs, windowHours);
  score += recent;
  reasons.push(`recency+${recent}`);

  let directness = 0;
  if (hasBtc || btcEtfFlow) directness = 3;
  else if (macroPolicy || regulatoryPolicy || geopolitics) directness = 2;
  else if (hasEth || cryptoMarketStructure || exchangeSecurityWhale || institutionCrypto) directness = 1;
  if (priorityBucket === 'secondary_sector' || priorityBucket === 'meme_other') {
    directness = 0;
    score = clampScore(score, bucket.base + 140 + recent);
  }

  return {
    tier: bucket.tier,
    category,
    score,
    reasons,
    priority_bucket: priorityBucket,
    bucket_rank: bucket.rank,
    directness,
    directness_label: directnessLabel(directness),
  };
}

export function compareRowsByPriority(a, b) {
  const aPriority = a.analysis_priority || {};
  const bPriority = b.analysis_priority || {};
  return (
    (bPriority.bucket_rank || 0) - (aPriority.bucket_rank || 0)
    || (bPriority.score || 0) - (aPriority.score || 0)
    || b.epoch_ms - a.epoch_ms
  );
}

/**
 * Select distinct fundamental events after priority sorting. Candidate rows
 * remain immutable. When one PPI release has multiple published dimensions
 * (for example YoY and MoM), the highest-priority row represents one Top-N
 * slot and all original sibling rows remain bound under event_family.members.
 */
export function selectTopRowsByPriority(rows, limit) {
  if (!Array.isArray(rows)) throw new TypeError('rows must be an array');
  if (!Number.isInteger(limit) || limit < 0) throw new RangeError('limit must be a non-negative integer');

  const groups = [];
  const familyGroups = new Map();
  for (const candidate of [...rows].sort(compareRowsByPriority)) {
    const family = identifyEventFamily(candidate);
    if (!family) {
      groups.push({ representative: candidate, family: null, members: [candidate] });
      continue;
    }
    const existing = familyGroups.get(family.key);
    if (existing) {
      existing.members.push(candidate);
      continue;
    }
    const group = { representative: candidate, family, members: [candidate] };
    familyGroups.set(family.key, group);
    groups.push(group);
  }

  return groups.slice(0, limit).map(({ representative, family, members }) => {
    if (!family) return representative;
    return {
      ...representative,
      event_family: {
        ...family,
        member_count: members.length,
        members: members.map((member) => ({ ...member })),
      },
    };
  });
}
