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
  meme: /(Meme|MEME|FOMO|TCC|BSC链Meme|无实际用例)/i,
  personalStory: /(字节炒股|炒股哥|Leto Bao|个人复盘|复盘总结|建议投资AI|对冲被AI取代)/i,
  nonCryptoSectorTitle: /(AI|人工智能|英伟达|美光|韩股|美股|iPhone|硬盘|存储|芯片|电池|机器人|航天|核能|电力|国防|GDP|数据中心|三星|SK海力士|Meta|亚马逊|微软|谷歌|Alphabet|甲骨文)/i,
  macroCore: /(美联储|FOMC|FedWatch|降息|加息|利率|联邦基金利率|CPI|PCE|通胀|非农|失业率|就业|美债|QT|QE|央行|货币政策|核心PCE)/i,
  macroDollar: /(美元指数|美元流动性|美元(?:走强|走弱|走高|走低|回落|反弹|坚挺|疲软|维持稳定|保持坚挺))/i,
  macroDollarBody: /(美元指数|美元流动性|DXY|美元(?:目前|仍|仍将|将|继续|短线|日内|隔夜|整体|大幅|小幅)(?:走强|走弱|走高|走低|回落|反弹|坚挺|疲软|维持稳定|保持坚挺))/i,
  macroLiquidityContext: /(美联储|FOMC|美元|美债|央行|利率|QT|QE|货币政策|降息|加息|通胀|CPI|PCE|非农|就业)/i,
  geopolitics: /(战争|冲突|制裁|外交|选举|伊朗|以色列|俄罗斯|乌克兰|中东|白宫|国会|财政部|司法部|特朗普)/i,
  regulatory: /(SEC|CFTC|监管|立法|法案|执法|MiCA|司法部|财政部|批准.{0,12}ETF|拒绝.{0,12}ETF|ETF.{0,12}批准|ETF.{0,12}拒绝|稳定币.{0,12}法案|数字资产.{0,12}政策)/i,
  btcEtfFlow: /((BTC|比特币|Bitcoin).{0,24}(ETF|净流入|净流出)|ETF.{0,24}(BTC|比特币|Bitcoin)|现货比特币ETF|IBIT|GBTC|FBTC|ARKB|Farside)/i,
  exchangeEvent: /(交易所|上币|宕机|Coinbase|Kraken|Bybit|OKX|Binance(?!\s*广场))/i,
  security: /(黑客|攻击|漏洞|制裁|执法|Tornado Cash|预言机|合约漏洞)/i,
  whale: /(巨鲸|鲸鱼|大额转账|转入交易所|转出交易所|地址)/i,
  liquidation: /(爆仓|清算|杠杆|强平|连锁清算|波动)/i,
  marketStructure: /(供应量|净供应|行情|现货价格|资金费率|持仓|OI|CVD|Delta|POC|卖压|买盘|抛压|波动)/i,
  institutionCrypto: /(Strategy|MicroStrategy|Metaplanet|机构持仓|增持|减持|净买入|净卖出)/i,
  quantified: /(\d+(?:\.\d+)?\s*(亿|万|万美元|亿美元|枚|%|个基点|bp))/i,
};

function has(pattern, text) {
  return pattern.test(text);
}

function clampScore(score, maxScore) {
  return Math.min(score, maxScore);
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
  const reasons = [];

  const hasBtc = has(PATTERNS.btc, text);
  const hasEth = has(PATTERNS.eth, text);
  const hasCryptoContext = hasBtc || hasEth || has(PATTERNS.cryptoContext, text);
  const hasMeme = has(PATTERNS.meme, text);
  const isPersonalStory = has(PATTERNS.personalStory, title);
  const hasNonCryptoSectorTitle = has(PATTERNS.nonCryptoSectorTitle, title) && !has(PATTERNS.btc, title);
  const isMemeOnly = hasMeme && !hasBtc && !has(PATTERNS.btcEtfFlow, text);
  const isSecondarySectorStory = (isPersonalStory || hasNonCryptoSectorTitle) && !hasBtc && !has(PATTERNS.btcEtfFlow, text);
  const macroLiquidity = /流动性/.test(text) && has(PATTERNS.macroLiquidityContext, text);
  const macroDollar = has(PATTERNS.macroDollar, title) || has(PATTERNS.macroDollarBody, text);
  const macroPolicy = !isSecondarySectorStory && (
    has(PATTERNS.macroCore, title)
    || macroDollar
    || macroLiquidity
  );
  const geopolitics = !isSecondarySectorStory && has(PATTERNS.geopolitics, title);
  const regulatoryPolicy = !isSecondarySectorStory && (
    has(PATTERNS.regulatory, title)
    || (hasCryptoContext && has(PATTERNS.regulatory, text))
  );
  const btcEtfFlow = has(PATTERNS.btcEtfFlow, text);
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
  let score = bucket.base;

  reasons.push(`bucket:${priorityBucket}`);
  if (macroPolicy || geopolitics) reasons.push(`T1:${bucket.category}`);
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
    category: bucket.category,
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
