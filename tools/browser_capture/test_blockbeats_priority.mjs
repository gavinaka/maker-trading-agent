import assert from 'node:assert/strict';
import {
  classifyImpact,
  compareRowsByPriority,
  identifyEventFamily,
  selectTopRowsByPriority,
} from './blockbeats_priority.js';

const nowMs = Date.parse('2026-07-10T14:10:00+08:00');

function row(title, body, datetime) {
  return {
    title,
    body,
    datetime,
    epoch_ms: Date.parse(datetime),
  };
}

const currentIncidentRows = [
  row(
    'Bitwise Q2总结：加密市场量价齐跌，预测市场交投火爆',
    '现货比特币 ETF 录得季度流出，预测市场交易量达432亿美元；稳定币持有美债超大多数国家。多个协议收入增长，链上活动与交易量仍然分化，价格反映熊市估值，但行业规模扩大，流动性更深。',
    '2026-07-10T10:52:00+08:00',
  ),
  row(
    '俄罗斯拟全面监控加密交易，6万卢布以上交易需报送详细信息',
    '俄罗斯政府拟通过配套法案授权金融监测局监管全部加密交易。',
    '2026-07-10T12:22:00+08:00',
  ),
  row(
    '特朗普重启对伊朗打击，共和党担忧拖累中期选举',
    '美军打击军事目标，伊朗反击，停火结束。',
    '2026-07-10T08:24:00+08:00',
  ),
  row(
    '美联储组建五个外部工作组，全面审查货币政策运行机制',
    '工作组将审查FOMC沟通与利率工具。',
    '2026-07-10T08:48:00+08:00',
  ),
];

const incidentRows = currentIncidentRows.map((candidate) => ({
  ...candidate,
  analysis_priority: classifyImpact(candidate, nowMs),
}));
const incidentTitles = [...incidentRows]
  .sort(compareRowsByPriority)
  .slice(0, 3)
  .map((candidate) => candidate.title);

assert.ok(incidentTitles.some((title) => title.includes('美联储组建五个外部工作组')));
assert.ok(incidentTitles.some((title) => title.includes('俄罗斯拟全面监控加密交易')));
assert.ok(incidentTitles.some((title) => title.includes('特朗普重启对伊朗打击')));
assert.ok(!incidentTitles.some((title) => title.includes('Bitwise Q2总结')));

const bitwiseQuarterly = incidentRows.find((candidate) => candidate.title.includes('Bitwise Q2总结'));
assert.equal(bitwiseQuarterly.analysis_priority.priority_bucket, 'btc_etf_flow');

const russianRegulation = incidentRows.find((candidate) => candidate.title.includes('俄罗斯拟全面监控'));
assert.equal(russianRegulation.analysis_priority.priority_bucket, 'regulatory_policy');

const regressionRows = [
  row('TCC Meme项目无实际用例', 'BSC链Meme出现FOMO。', '2026-07-10T13:30:00+08:00'),
  row('AWS加码AI存储赛道', 'AI资本开支继续扩大。', '2026-07-10T13:20:00+08:00'),
  row('纽约梅隆银行：美联储降息预期升温', 'FOMC与利率路径变化。', '2026-07-10T13:10:00+08:00'),
  row('比特币衍生品风险升温', 'Murphy称BTC持仓、资金费率与波动同步上升。', '2026-07-10T13:00:00+08:00'),
  row('EthLabs发布协议升级', '以太坊项目技术更新。', '2026-07-10T12:50:00+08:00'),
];

const scoredRows = regressionRows.map((candidate) => ({
  ...candidate,
  analysis_priority: classifyImpact(candidate, nowMs),
}));

const tcc = scoredRows.find((candidate) => candidate.title.includes('TCC'));
assert.equal(tcc.analysis_priority.priority_bucket, 'meme_other');
assert.equal(tcc.analysis_priority.directness_label, 'low_btc_relevance');

const awsSector = scoredRows.find((candidate) => candidate.title.includes('AWS'));
assert.equal(awsSector.analysis_priority.priority_bucket, 'secondary_sector');
assert.equal(awsSector.analysis_priority.directness_label, 'low_btc_relevance');

const nyMellonMacro = scoredRows.find((candidate) => candidate.title.includes('纽约梅隆银行'));
assert.equal(nyMellonMacro.analysis_priority.priority_bucket, 'macro_policy');
assert.equal(nyMellonMacro.analysis_priority.directness_label, 'direct_macro_or_regulatory');

const btcDerivativesRisk = scoredRows.find((candidate) => candidate.body.includes('Murphy'));
assert.equal(btcDerivativesRisk.analysis_priority.priority_bucket, 'crypto_market_structure');

const ethLabs = scoredRows.find((candidate) => candidate.title.includes('EthLabs'));
assert.notEqual(ethLabs.analysis_priority.priority_bucket, 'macro_policy');

const skHynixFunding = row(
  'Hyperliquid上SK海力士相关合约资金费率一小时暴涨逾130%',
  '该合约24小时交易量达18.36亿美元，超过 BTC，随后交易量小幅回落；资金费率与OI仍处高位。',
  '2026-07-10T13:40:00+08:00',
);
const skHynixPriority = classifyImpact(skHynixFunding, nowMs);
assert.equal(skHynixPriority.priority_bucket, 'secondary_sector');
assert.equal(skHynixPriority.directness_label, 'low_btc_relevance');

const btcFunding = row(
  'BTC资金费率持续上升，OI同步增加',
  '比特币永续合约资金费率和持仓量同步走高。',
  '2026-07-10T13:35:00+08:00',
);
assert.equal(classifyImpact(btcFunding, nowMs).priority_bucket, 'crypto_market_structure');

const actualDollarMove = row(
  '美元小幅回落，美联储利率预期重新定价',
  'DXY走低，市场关注FOMC与联邦基金利率路径。',
  '2026-07-10T13:30:00+08:00',
);
assert.equal(classifyImpact(actualDollarMove, nowMs).priority_bucket, 'macro_policy');

const amountDenominatedMove = row(
  'Hyperliquid某合约交易量回落',
  '该合约交易量从18.36亿美元小幅回落，资金费率与OI仍处高位。',
  '2026-07-10T13:25:00+08:00',
);
assert.notEqual(classifyImpact(amountDenominatedMove, nowMs).priority_bucket, 'macro_policy');

const cpiWhalePosition = row(
  'CPI前夕1名巨鲸持7400万纳指重仓，多单规模独占该合约21%持仓量',
  '该巨鲸在Hyperliquid持有纳斯达克100指数多单；美国CPI将于今晚公布。',
  '2026-07-10T13:22:00+08:00',
);
assert.equal(classifyImpact(cpiWhalePosition, nowMs).priority_bucket, 'crypto_market_structure');

const topThreeRegression = [
  skHynixFunding,
  cpiWhalePosition,
  row('美国CPI数据即将公布', '通胀数据将影响美联储利率路径。', '2026-07-10T13:20:00+08:00'),
  row('美联储官员讨论下一次利率决定', 'FOMC继续评估通胀与就业。', '2026-07-10T13:15:00+08:00'),
  row('昨日比特币ETF录得净流入', '现货比特币ETF净流入2亿美元。', '2026-07-10T13:10:00+08:00'),
].map((candidate) => ({
  ...candidate,
  analysis_priority: classifyImpact(candidate, nowMs),
}));
const topThreeTitles = topThreeRegression
  .sort(compareRowsByPriority)
  .slice(0, 3)
  .map((candidate) => candidate.title);
assert.ok(!topThreeTitles.includes(skHynixFunding.title));
assert.ok(!topThreeTitles.includes(cpiWhalePosition.title));

const ppiAnnual = row(
  '美国6月PPI年率5.5%，预期6.2%',
  '美国6月PPI年率低于预期，前值同步修正。',
  '2026-07-10T14:01:00+08:00',
);
const ppiMonthly = row(
  '美国6月PPI月率-0.3%，预期0%',
  '美国6月PPI月率低于预期，前值同步修正。',
  '2026-07-10T14:00:00+08:00',
);
const ppiChineseMonthNarrative = row(
  '美国六月PPI通胀关键指标低于预期，或为美联储提供更多推迟加息空间',
  '数据显示，核心 PPI 指数同比上涨4.7%，环比上升0.2%；总体 PPI 年率为5.5%。',
  '2026-07-10T14:02:00+08:00',
);
assert.equal(classifyImpact(ppiAnnual, nowMs).priority_bucket, 'macro_policy');
assert.equal(classifyImpact(ppiMonthly, nowMs).priority_bucket, 'macro_policy');
assert.equal(identifyEventFamily(ppiAnnual)?.key, identifyEventFamily(ppiMonthly)?.key);
assert.equal(identifyEventFamily(ppiChineseMonthNarrative)?.key, identifyEventFamily(ppiAnnual)?.key);

const ppiBodyFallback = row(
  '美国PPI数据低于预期',
  '数据显示，美国6月PPI年率5.5%，低于市场预期。',
  '2026-07-10T14:03:00+08:00',
);
assert.equal(identifyEventFamily(ppiBodyFallback), null);

for (const candidate of [
  row(
    '美国PPI数据低于预期',
    '数据显示，中国6月PPI年率为5.5%。',
    '2026-07-10T14:03:30+08:00',
  ),
  row(
    '美国6月PPI数据解读',
    '数据显示，美国5月PPI年率为5.5%。',
    '2026-07-10T14:03:29+08:00',
  ),
  row(
    '美国六月PPI追踪',
    'CPI年率3.0%。',
    '2026-07-10T14:03:28+08:00',
  ),
  row(
    '美国六月PPI追踪',
    'CPI年率3.0%，PPI仍待公布。',
    '2026-07-10T14:03:28+08:00',
  ),
  row(
    '美国六月PPI数据更新',
    '市场预计 PPI 年率为5.5%。',
    '2026-07-10T14:03:27+08:00',
  ),
  row(
    '美国六月PPI数据更新',
    '前值 PPI 年率5.5%。',
    '2026-07-10T14:03:26+08:00',
  ),
]) {
  assert.equal(identifyEventFamily(candidate), null);
}

const ppiChineseMonthPreview = row(
  '美国六月PPI前瞻：市场等待数据公布',
  '数据尚未公布，前值PPI年率5.5%。',
  '2026-07-10T14:04:00+08:00',
);
assert.equal(identifyEventFamily(ppiChineseMonthPreview), null);

const ppiActualWithPreviousValue = row(
  '美国六月PPI数据解读',
  '数据显示，美国PPI年率5.5%，前值6.5%。',
  '2026-07-10T14:04:10+08:00',
);
assert.equal(identifyEventFamily(ppiActualWithPreviousValue)?.key, identifyEventFamily(ppiAnnual)?.key);
assert.equal(identifyEventFamily(row(
  '美国6月PPI年率5.5%，预计美联储保持利率',
  '数据已经公布。',
  '2026-07-10T14:04:11+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);
assert.equal(identifyEventFamily(row(
  '美国六月PPI创历史新高，年率5.5%',
  '数据已经公布。',
  '2026-07-10T14:04:12+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const title of [
  '美国6月PPI年率5.5%预测值',
  '美国6月PPI年率5.5%预期值',
  '美国6月PPI年率5.5%（预测值）',
  '美国6月PPI年率5.5%（预期值）',
  '美国6月PPI年率5.5%，为市场预测值',
  '美国6月PPI年率5.5%预估值',
  '美国6月PPI年率5.5%（市场一致预期）',
  '美国6月PPI年率5.5%（路透预估）',
  '美国6月PPI年率5.5%（路透调查预估）',
  '美国6月PPI年率5.5%（前值）',
  '美国6月PPI年率5.5%，为前值',
  '美国6月PPI年率5.5%，尚未公布',
  '美国6月PPI年率5.5%（待公布）',
  '美国6月PPI年率5.5%（预期区间）',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '市场仍在等待实际数据。',
    '2026-07-10T14:04:13+08:00',
  )), null, title);
}

for (const body of [
  '分析师预计，考虑到能源与食品价格持续上涨等因素，美国PPI同比上涨4.7%。',
  '前值方面，考虑到能源与食品价格持续上涨等因素，美国PPI同比上涨4.7%。',
  '市场预计美国PPI年率录得4.7%。',
  '分析师估计美国PPI同比上涨4.7%。',
  '市场预估美国PPI同比上涨4.7%。',
  '市场料美国PPI同比上涨4.7%。',
  '市场预料美国PPI同比上涨4.7%。',
  '此前数据显示，美国PPI年率5.5%。',
  '根据此前官方数据显示，美国PPI年率5.5%。',
  '分析师预计美国PPI低于预期，年率5.5%。',
  '市场预估美国PPI低于预期，年率5.5%。',
  '历史数据显示，美国PPI年率5.5%。',
  '过往数据显示，美国PPI年率5.5%。',
  '往期官方数据显示，美国PPI年率5.5%。',
  '去年数据显示，美国PPI年率5.5%。',
  '上次公布数据显示，美国PPI年率5.5%。',
  '模型预测数据显示，美国PPI年率5.5%。',
  '分析师预测数据显示，美国PPI年率5.5%。',
  '市场预估数据显示，美国PPI年率5.5%。',
  '机构预计后续数据显示，美国PPI年率5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:14+08:00',
  )), null);
}

assert.equal(identifyEventFamily(row(
  '美国6月PPI年率5.5%，预期6.2%',
  '数据已经公布。',
  '2026-07-10T14:04:15+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const title of [
  '美国6月PPI年率5.5%（预期值6.2%）',
  '美国6月PPI年率5.5%（市场预期值为6.2%）',
  '美国6月PPI年率5.5%（前值6.5%）',
  '美国6月PPI年率5.5%，前值修正为6.0%',
  '美国6月PPI年率5.5%，前值同步下修',
  '美国6月PPI年率5.5%（前值修正为6.0%）',
  '美国6月PPI年率5.5%，前值由6.5%修正为6.0%',
  '美国6月PPI年率5.5%（预期值约6.2%）',
  '美国6月PPI年率5.5%，预期年率6.2%',
  '美国6月PPI年率5.5%，市场预期PPI年率6.2%',
  '美国6月PPI年率5.5%，前值PPI年率6.5%',
  '美国6月PPI年率5.5%，预期区间6.0%-6.2%',
  '美国6月PPI年率5.5%（市场预期区间6.0%-6.2%）',
  '美国6月PPI年率5.5%，前值区间6.0%-6.5%',
  '美国6月PPI年率5.5%，预期约为6.2%',
  '美国6月PPI年率5.5%，市场预期此前为6.2%',
  '美国6月PPI年率5.5%，路透预估美联储将维持利率',
  '市场预期6.2%，美国6月PPI年率录得5.5%',
  '预期6.2%，美国6月PPI年率为5.5%',
  '美国6月PPI年率5.5%，美联储将于明日公布利率决议',
  '美联储利率数据尚未公布但美国6月PPI年率5.5%',
  '美联储利率数据尚未公布，美国6月PPI年率5.5%',
  '市场预计美联储降息，美国6月PPI年率5.5%',
  '与去年同期相比，美国六月PPI年率5.5%',
  '美国六月PPI较去年同期上涨5.5%',
  '美国六月PPI与去年同期相比上涨5.5%',
  '美国6月PPI年率达5.5%',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '当前数据已经公布。',
    '2026-07-10T14:04:15+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, title);
}

assert.equal(identifyEventFamily(row(
  '美国六月PPI低于预期，市场预计美联储保持利率',
  '数据显示，美国PPI年率5.5%。',
  '2026-07-10T14:04:16+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const body of [
  '数据显示，美国PPI年率5.5%。',
  '数据显示，本次数据低于前值，美国PPI年率5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI低于前值',
    body,
    '2026-07-10T14:04:16+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key);
}

assert.equal(identifyEventFamily(row(
  '美国六月PPI数据观察',
  '数据显示，美国PPI年率5.5%。美联储利率数据尚未公布。',
  '2026-07-10T14:04:18+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

assert.equal(identifyEventFamily(row(
  '美国六月PPI数据观察',
  '市场预计美联储降息，但数据显示美国PPI同比上涨4.7%。',
  '2026-07-10T14:04:17+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

assert.equal(identifyEventFamily(row(
  '美国六月PPI数据观察',
  '数据显示，美国PPI同比涨幅为5.5%。',
  '2026-07-10T14:04:17+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const title of [
  '去年美国六月PPI年率5.5%',
  '前年公布的美国六月PPI年率5.5%',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '数据已经公布。',
    '2026-07-10T14:04:18+08:00',
  )), null);
}

for (const body of [
  '美国PPI年率5.5%？数据尚未公布。',
  '美国PPI年率5.5%。但该数字为预测值，数据尚未公布。',
  '美国PPI年率5.5%。但PPI仍待公布。',
  '美国PPI年率5.5%。但该数据仍待公布。',
  '美国PPI年率5.5%。但该数字为市场预测。',
  '美国PPI年率5.5%。该数字只是分析师预估。',
  '美国PPI年率5.5%。这只是预期，并非实际数据。',
  '美国PPI年率5.5%。实际数据尚未发布。',
  '美国PPI年率5.5%。官方尚未发布该数据。',
  '美国PPI年率5.5%。这一数字只是市场估算。',
  '美国PPI年率5.5%。该值为预测值。',
  '美国PPI年率5.5%。上述数据尚未公布。',
  '美国PPI年率5.5%。前述数据尚未公布。',
  '美国PPI年率5.5%。上述数值系预测值。',
  '美国PPI年率5.5%。但官方尚未公布。',
  '美国PPI年率5.5%。截至目前仍未公布。',
  '美国PPI年率5.5%。该结果为预测值。',
  '美国PPI年率5.5%。数据仍为预期值。',
  '美国PPI年率5.5%。PPI实际数据将于明日公布。',
  '美国PPI年率5.5%。官方数据尚未公布。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:19+08:00',
  )), null);
}

for (const body of [
  '去年美国6月PPI年率5.5%。',
  '美国去年6月PPI年率5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:19+08:00',
  )), null);
}

assert.equal(identifyEventFamily(row(
  '美国六月PPI数据观察',
  '与去年同期相比，美国PPI同比上涨5.5%。',
  '2026-07-10T14:04:19+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const body of [
  '数据显示，欧元区5月PPI年率3.0%。',
  '数据显示，美国5月PPI年率3.0%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国6月PPI年率5.5%',
    body,
    '2026-07-10T14:04:20+08:00',
  )), null);
}

for (const body of [
  '数据显示，美国6月PPI月率-0.3%。',
  '数据显示，欧元区5月CPI年率3.0%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国6月PPI年率5.5%',
    body,
    '2026-07-10T14:04:21+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key);
}

// Candidate-local PPI semantics: subject ownership, modality, time scope,
// release state, and post-value labels are independent dimensions. A valid
// current release must survive comparisons, while forecasts, historical
// observations, unrelated subjects, and unpublished values must not borrow it.
for (const title of [
  '美国6月PPI此前预期6.2%，官方数据显示PPI年率5.5%',
  '市场预计通胀放缓，官方数据显示美国6月PPI年率5.5%',
  '美国6月PPI年率5.5%，低于预期',
  '美国6月PPI年率5.5%，符合市场预期',
  '美国6月PPI年率5.5%，较前值回落',
  '美国6月PPI年率5.5%，不及市场预期',
  '美国6月PPI年率5.5%，较预期低0.7个百分点',
  '美国6月PPI年率5.5%，6.2%为预期值',
  '美国6月PPI同比增5.5%',
  '美国6月PPI环比持平0.0%',
  '美国6月PPI年率由4.7%升至5.5%',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '本次数据已经公布。',
    '2026-07-10T14:04:21+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, title);
}

for (const body of [
  '此前预测PPI年率6.2%，官方数据显示美国PPI年率5.5%。',
  '市场预计通胀放缓，官方数据显示美国PPI年率5.5%。',
  '官方数据显示，美国PPI年率5.5%；2025年6月PPI前值为6.5%。',
  '官方数据显示，美国PPI年率5.5%；下一期PPI尚未公布。',
  '官方数据显示，美国PPI年率5.5%；美国7月PPI尚未公布。',
  '官方数据显示，美国PPI年率5.5%；官方尚未公布就业数据。',
  '美国PPI同比增5.5%。',
  '美国PPI环比持平0.0%。',
  '美国PPI年率由4.7%升至5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:22+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, body);
}

for (const title of [
  '美国6月PPI代币年率5.5%',
  '美国6月PPI料录得年率5.5%',
  '美国6月PPI有望录得年率5.5%',
  '美国6月PPI或录得年率5.5%',
]) {
  const candidate = row(title, '市场仍在等待官方发布。', '2026-07-10T14:04:23+08:00');
  assert.equal(identifyEventFamily(candidate), null, title);
  assert.notEqual(classifyImpact(candidate, nowMs).priority_bucket, 'macro_policy', title);
}

for (const body of [
  '美国PPI年率5.5%。5.5%只是预测值。',
  '美国PPI年率5.5%。其中5.5%为预测值。',
  '美国PPI年率5.5%。该数字来自分析师模型而非官方发布。',
  '美国PPI官方结果仍没有对外发布，市场给出年率5.5%。',
  '美国PPI的实际值尚未公布，市场预计年率5.5%。',
  '美国PPI实际值尚未公布，市场预计年率5.5%。',
  '美国PPI数据目前仍未公布，市场预计年率5.5%。',
  '该数据截至目前尚未公布，美国PPI预期年率5.5%。',
  '美国PPI最终结果尚未公布，市场预计年率5.5%。',
  '美国PPI官方数据尚未公布，市场预计年率5.5%。',
  '美国PPI尚待官方公布，市场预计年率5.5%。',
  '美国PPI暂未公布，市场预计年率5.5%。',
  '美国PPI尚未正式公布，市场预计年率5.5%。',
  '美国PPI未对外公布，市场预计年率5.5%。',
  '美国PPI截至发稿仍未公布，市场预计年率5.5%。',
  '美国PPI目前官方尚未公布，市场预计年率5.5%。',
  '该结果仍属预测值，美国PPI年率5.5%。',
  '这只是一个市场预测，美国PPI年率5.5%。',
  '该结果只是初步估算，美国PPI年率5.5%。',
  '该值来自分析师预测，美国PPI年率5.5%。',
  '早前数据显示，美国PPI年率5.5%。',
  '旧数据显示，美国PPI年率5.5%。',
  '接受调查的经济学家认为，美国PPI年率5.5%。',
  '市场共识显示，美国PPI年率5.5%。',
  '路透调查显示，美国PPI年率5.5%。',
  '历史实际值显示，美国PPI年率5.5%。',
  '过往公布值显示，美国PPI年率5.5%。',
  '往期发布值显示，美国PPI年率5.5%。',
  '去年实际值显示，美国PPI年率5.5%。',
  '上期数据显示，美国PPI年率5.5%。',
  '前次数据显示，美国PPI年率5.5%。',
  '上月数据显示，美国PPI年率5.5%。',
  '美国PPI上月年率5.5%。',
  '美国PPI上期年率5.5%。',
  '美国PPI前次年率5.5%。',
  '官方数据显示CPI回落，美国PPI年率5.5%。',
  '官方数据显示GDP增长，美国PPI年率5.5%。',
  '美国PPI报告称工资同比上涨5.5%。',
  '美国PPI报告：企业利润同比上涨5.5%。',
  '去年同期美国PPI同比上涨5.5%。',
  '上年同期美国PPI同比上涨5.5%。',
  '2025年同期美国PPI同比上涨5.5%。',
  '2025年美国PPI同比上涨5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:24+08:00',
  )), null, body);
}

assert.equal(identifyEventFamily(row(
  '美国六月PPI数据观察',
  '数据显示，核心PPI同比上涨4.7%。',
  '2026-07-10T14:04:25+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const title of [
  '美国6月PPI前值年率6.2%，实际值为5.5%',
  '美国6月PPI同比上涨5.5%，逊于市场预期',
  '美国6月PPI同比上涨5.5%，好于预期',
  '美国6月PPI同比上涨5.5%，超预期',
  '美国6月PPI同比上涨5.5%，强于预期',
  '美国6月PPI同比上涨5.5%，弱于预期',
  '美国6月PPI同比上涨5.5%，略低于预期',
  '美国6月PPI同比上涨5.5%，大幅高于预期',
  '美国6月PPI同比上涨5.5%，市场预期下半年企业成本回落',
  '美国6月PPI同比上涨5.5%，前值已经在上月公布',
  '美国6月PPI年率从4.7%升至5.5%',
  '美国6月PPI同比增长了5.5%',
  '美国6月PPI同比上涨约5.5%',
  '6月美国PPI同比上涨5.5%',
  '美国6月同比上涨5.5%的PPI数据正式公布',
  '美国6月PPI初值年率5.5%',
  '美国6月PPI修正后年率5.5%',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '本次数据已经正式公布。',
    '2026-07-10T14:04:26+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, title);
}

for (const body of [
  '美国PPI前值年率6.2%，但实际值为5.5%。',
  '美国PPI年率5.5%，市场预期则为6.2%。',
  '美国PPI年率5.5%，预期中值为6.2%。',
  '美国PPI年率5.5%，前值则为6.5%。',
  '美国PPI年率5.5%，数据已正式公布。',
  '美国劳工部正式公布：PPI年率5.5%。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。下一期数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。下月该指标尚未发布。',
  '官方数据显示，美国PPI年率5.5%；2025年6月PPI实际值为6.5%，仅作历史对照。',
  '官方数据显示，美国PPI年率5.5%。该数据来自机构官方发布。',
  '官方数据显示，美国PPI年率5.5%。7月该数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。2026年7月该指标待发布。',
  '官方数据显示，美国PPI年率5.5%。次月该数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%；2025年6月PPI实际值为6.5%，用于和本次数据作对照。',
  '官方数据显示，美国PPI年率5.5%；2025年6月PPI实际值为6.5%，作为往期对比。',
  '官方数据显示，美国PPI年率5.5%；2025年6月PPI实际值为6.5%，这是历史参考值。',
  '官方数据显示，美国PPI经季节调整后的年率为5.5%。',
  '官方数据显示，美国PPI数据显示其年率为5.5%。',
  '官方数据显示，美国PPI报告所列年率为5.5%。',
  '官方数据显示，美国PPI官方发布结果中的年率为5.5%。',
  '官方数据显示，美国PPI（经季节调整）环比-0.3%。',
  '官方数据显示，美国PPI经季调后环比-0.3%。',
  '官方数据显示，美国PPI不含食品和能源的核心指数同比4.7%。',
  '美国PPI前值年率6.2%，最终公布为年率5.5%。',
  '美国PPI前值年率6.2%，实际年率为5.5%。',
  '美国PPI前值年率6.2%，最终年率为5.5%。',
  '美国PPI年率5.5%，由劳工部正式公布。',
  '美国PPI年率5.5%，已由劳工部公布。',
  '美国PPI年率5.5%，是市场预期落空后的实际数据。',
  '美国PPI年率5.5%，为预期之外的意外结果。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:27+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, body);
}

for (const body of [
  '本次PPI尚未公布而下一期PPI也待发布。',
  '美国PPI年率5.5%。5.5%系路透预估。',
  '美国PPI年率5.5%。上述5.5%来自路透预估。',
  '美国PPI报告称员工薪酬同比上涨5.5%。',
  '美国PPI报告称服务价格同比上涨5.5%。',
  '美国PPI报告发布，影院票价同比上涨5.5%。',
  '美国PPI报告发布，某公司订单同比上涨5.5%。',
  '美国PPI年率5.5%，这是5月数据。',
  '美国PPI年率5.5%，这是中国数据。',
  '美国PPI年率5.5%，实际对应2025年。',
  '数据显示，美国PPI年率5.5%，实际对应2025年。',
  '此前，官方数据显示，美国PPI年率5.5%。',
  '早前，官方数据显示，美国PPI年率5.5%。',
  '过往，官方数据显示，美国PPI年率5.5%。',
  '官方数据尚无结果，其中5.5%只是路透调查中值。',
  '官方数据尚无结果，其中5.5%系经济学家调查中位数。',
  '官方数据尚无结果，其中5.5%为彭博调查所得共识值。',
  '市场预计美国PPI，CPI数据显示，美国PPI年率5.5%。',
  '市场预计美国PPI，工资数据显示，美国PPI年率5.5%。',
  '本次PPI尚未公布同时下一期PPI也待发布。',
  '本次PPI尚未公布且下一期PPI也待发布。',
  '美国PPI年率5.5%。5.5%为路透一致预估。',
  '美国PPI年率5.5%。5.5%为市场测算结果。',
  '美国PPI年率5.5%，实际对应CPI。',
  '美国PPI年率5.5%，这是GDP数据。',
  '美国PPI年率5.5%，该值属于海运费数据。',
  '美国PPI年率5.5%，该数据并非PPI而是CPI。',
  '美国PPI年率5.5%，该数为预测值。',
  '美国PPI年率5.5%，其并非实际数据。',
  '美国PPI年率5.5%，本报告中的5.5%为预测值。',
  '美国PPI年率5.5%，此值为预测值。',
  '美国PPI年率5.5%，该读数并非实际值。',
  '美国PPI年率5.5%，上述百分比为市场预测值。',
  '美国PPI年率5.5%，所述5.5%为预期值。',
  '美国PPI年率5.5%，仅供预测参考，并非实际值。',
  '截至此前，官方数据显示，美国PPI年率5.5%。',
  '在此前，官方数据显示，美国PPI年率5.5%。',
  '更早前，官方数据显示，美国PPI年率5.5%。',
  '当时，官方数据显示，美国PPI年率5.5%。',
  '据早前消息，官方数据显示，美国PPI年率5.5%。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国六月PPI数据观察',
    body,
    '2026-07-10T14:04:28+08:00',
  )), null, body);
}

for (const title of [
  '美国代币6月PPI年率5.5%',
  '美国6月PPI币年率5.5%',
  '美国6月PPI（代币）年率上涨5.5%',
  '美国6月代币PPI年率上涨5.5%',
  '美国6月项目PPI年率上涨5.5%',
  '美国6月PPI将录得年率5.5%',
  '美国6月PPI大概率录得年率5.5%',
  '美国6月PPI或许录得年率5.5%',
  '美国6月PPI恐录得年率5.5%',
  '美国6月PPI曾录得年率5.5%',
  '美国6月PPI先前录得年率5.5%',
  '美国6月PPI观察：2025年PPI同比上涨5.5%',
  '美国6月PPI年率5.5%代币上线',
]) {
  const candidate = row(title, '正文不得补造当前发布。', '2026-07-10T14:04:29+08:00');
  assert.equal(identifyEventFamily(candidate), null, title);
  assert.notEqual(classifyImpact(candidate, nowMs).priority_bucket, 'macro_policy', title);
}

for (const body of [
  '与此同时，这家公司尚未公布财报。',
  '零售销售数据尚未公布。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国6月PPI同比上涨5.5%',
    body,
    '2026-07-10T14:04:30+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, body);
}

assert.equal(identifyEventFamily(row(
  '美国6月PPI同比上涨5.5%，中国出口商面临更大压力',
  '本次数据已经正式公布。',
  '2026-07-10T14:04:30+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

assert.equal(identifyEventFamily(row(
  '美国劳工部公布，6月PPI同比上涨5.5%',
  '本次数据已经正式公布。',
  '2026-07-10T14:04:30+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

assert.equal(identifyEventFamily(row(
  '6月PPI同比上涨5.5%，中国出口商面临更大压力',
  '本次数据已经正式公布。',
  '2026-07-10T14:04:30+08:00',
)), null);

assert.equal(identifyEventFamily(row(
  '美国6月PPI年率5.5%',
  '美国6月PPI已公布而美国7月PPI尚未公布。',
  '2026-07-10T14:04:30+08:00',
))?.key, identifyEventFamily(ppiAnnual)?.key);

for (const body of [
  '官方数据显示，美国PPI经季节性因素调整后环比下降0.3%。',
  '官方数据显示，美国PPI剔除食品和能源后的核心指数同比上涨4.7%。',
  '官方数据显示，美国PPI年率5.5%。2025年6月PPI实际值为6.5%，作为同比基数。',
  '官方数据显示，美国PPI年率5.5%。这是美国劳工部数据。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据对应7月。该数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。对应7月的是下一期该数据，尚未公布。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据对应7月。数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据对应7月。该结果是CPI数据。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据来自中国模型预测。',
  '官方数据显示，美国PPI年率5.5%。下一期该数据预计为5.5%。5.5%为市场预测值。',
  '官方数据显示，美国PPI年率5.5%。零售销售数据受到关注。该数据尚未公布。',
  '官方数据显示，美国PPI年率5.5%。某公司利润率为5.5%。5.5%为市场预测值。',
  '官方数据显示，美国PPI年率5.5%。该数据来自中国媒体转载。',
]) {
  assert.equal(identifyEventFamily(row(
    '美国6月PPI数据观察',
    body,
    '2026-07-10T14:04:30+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, body);
}

for (const title of [
  '美国6月PPI同比上涨5.5%拖累中国出口商',
  '中国资产因美国6月PPI年率5.5%而上涨',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '本次数据已经正式公布。',
    '2026-07-10T14:04:30+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, title);
}

assert.equal(identifyEventFamily(row(
  '美国市场关注中国6月PPI年率5.5%',
  '本次数据已经正式公布。',
  '2026-07-10T14:04:30+08:00',
))?.key, 'macro_release:ppi:中国:2026-06');

for (const [title, body] of [
  ['美国6月PPI年率5.5%', '文中的PPI是同名代币，并非宏观价格指数。'],
  ['美国6月PPI数据观察', 'PMI数据显示，美国PPI年率5.5%。'],
  ['美国6月PPI数据观察', '数据显示，美国PPI年率5.5%，数据实际来自中国。'],
  ['美国6月PPI数据回顾', '在2025年的报告中，官方数据显示，美国PPI年率5.5%。'],
  ['美国6月PPI年率5.5%其实是代币收益率', '正文说明这是项目指标。'],
  ['美国6月PPI数据观察', '官方数据显示，美国PPI年率5.5%。该值是某项目收益率。'],
  ['美国6月PPI数据观察', '美国PPI年率5.5%，该项读数并非实际值。'],
  ['美国6月PPI数据观察', '美国PPI年率5.5%，前述年率为调查中值。'],
  ['美国6月PPI年率5.5%的代币理财产品', '该产品将在链上提供收益。'],
  ['美国6月PPI年率5.5%的代币收益产品', '该项目即将开放申购。'],
  ['市场押注美国6月PPI年率5.5%', '交易员正在布局数据公布前的仓位。'],
  ['掉期市场隐含美国6月PPI年率5.5%', '这是交易定价，不是官方数据。'],
  ['美国6月PPI年率5.5%', '更正：报道有误，5.5%实际是CPI年率，而非PPI。'],
  ['美国6月PPI年率5.5%', '来源：中国国家统计局。'],
  ['美国6月PPI年率5.5%，其实是代币收益率', '该项目即将开放申购。'],
  ['美国6月PPI年率5.5%', '其实是代币收益率。'],
  ['美国6月PPI数据观察', '官方数据显示，美国PPI年率5.5%。下一期该数据对应7月。6月该数据尚未公布。'],
]) {
  const candidate = row(title, body, '2026-07-10T14:04:30+08:00');
  assert.equal(identifyEventFamily(candidate), null, `${title} | ${body}`);
  assert.notEqual(classifyImpact(candidate, nowMs).priority_bucket, 'macro_policy', title);
}

for (const [title, body] of [
  ['美国官方发布就业报告，6月PPI年率5.5%', '正文不得借用就业发布 cue。'],
  ['中国政府公布GDP数据，6月PPI年率5.5%', '正文不得借用 GDP 发布 cue。'],
  ['美国官方发布公司财报，6月PPI年率5.5%', '正文不得借用财报发布 cue。'],
  ['中国政府公布人口数据，6月PPI年率5.5%', '正文不得借用人口发布 cue。'],
]) {
  assert.equal(identifyEventFamily(row(
    title,
    body,
    '2026-07-10T14:04:30+08:00',
  )), null, title);
}

for (const title of [
  '美国6月PPI经季节性调整后的月率下降0.3%',
  '美国6月PPI最新读数年率为5.5%',
]) {
  assert.equal(identifyEventFamily(row(
    title,
    '美国劳工部公布最新数据。',
    '2026-07-10T14:04:30+08:00',
  ))?.key, identifyEventFamily(ppiAnnual)?.key, title);
}

for (const title of [
  '美国否认与伊朗发生军事冲突',
  '美国没有证据表明伊朗发动袭击',
  '美国公司发布总统选举预测软件',
  '美国公司发布供美军空袭伊朗设施使用的软件',
  '美国尚未空袭伊朗',
  '美国称空袭伊朗的报道不实',
  '美国未证实伊朗发动袭击',
  '如果美国空袭伊朗，油价或将上涨',
  '美国会空袭伊朗吗？',
  '美国博彩公司开出总统大选赔率',
  '美国公司上线总统选举预测网站',
  '法国外交题材电影上映',
  '美国出版社推出《空袭伊朗》小说',
]) {
  const candidate = row(title, '没有可认证的新地缘事件。', '2026-07-10T14:04:31+08:00');
  assert.notEqual(classifyImpact(candidate, nowMs).category, '地缘政治', title);
  assert.ok(!classifyImpact(candidate, nowMs).reasons.includes('T1:地缘政治'), title);
}

const deniedIranStrike = row(
  '美国空袭伊朗设施',
  '白宫否认相关空袭报道，称消息不实。',
  '2026-07-10T14:04:33+08:00',
);
assert.notEqual(classifyImpact(deniedIranStrike, nowMs).category, '地缘政治');
assert.ok(!classifyImpact(deniedIranStrike, nowMs).reasons.includes('T1:地缘政治'));

for (const candidate of [
  row('中国银行与美国银行发生冲突', '双方因跨境结算合同产生商业纠纷。', '2026-07-10T14:04:33+08:00'),
  row('美国大学学生会选举结束', '校内学生完成自治组织换届。', '2026-07-10T14:04:33+08:00'),
  row('美国空袭伊朗军事基地', '美国国防部表示，相关消息不属实。', '2026-07-10T14:04:33+08:00'),
  row('预测市场押注美国将空袭伊朗', '交易者评估未来军事行动概率。', '2026-07-10T14:04:33+08:00'),
  row('美军并未空袭伊朗', '双方仍保持军事戒备。', '2026-07-10T14:04:33+08:00'),
  row('所谓空袭从未发生', '军方称报道不实。', '2026-07-10T14:04:33+08:00'),
  row('美国计划空袭伊朗设施', '该计划仍在评估。', '2026-07-10T14:04:33+08:00'),
  row('美国计划对伊朗实施空袭', '仍在评估。', '2026-07-10T14:04:33+08:00'),
  row('美国拟对伊朗发动空袭', '尚未获批。', '2026-07-10T14:04:33+08:00'),
  row('美国将空袭伊朗设施', '行动尚未开始。', '2026-07-10T14:04:33+08:00'),
  row('美国正考虑空袭伊朗设施', '仍在讨论。', '2026-07-10T14:04:33+08:00'),
  row('美国讨论空袭伊朗设施', '尚未形成决定。', '2026-07-10T14:04:33+08:00'),
  row('白宫批准空袭伊朗的计划', '行动尚未执行。', '2026-07-10T14:04:33+08:00'),
  row('美国不排除空袭伊朗', '这只是政策选项。', '2026-07-10T14:04:33+08:00'),
  row('美国威胁将空袭伊朗', '未来行动仍不确定。', '2026-07-10T14:04:33+08:00'),
  row('美国并无空袭伊朗的计划', '军方否认相关安排。', '2026-07-10T14:04:33+08:00'),
  row('美国空袭伊朗的说法被否认', '官方称报道不实。', '2026-07-10T14:04:33+08:00'),
  row('美国空袭伊朗设施但否认空袭发生', '标题内含同事件反证。', '2026-07-10T14:04:33+08:00'),
  row('美军空袭伊朗基地', '伊朗军方称美军并未空袭该基地。', '2026-07-10T14:04:33+08:00'),
  row('美军空袭伊朗基地', '并未进行此次军事行动。', '2026-07-10T14:04:33+08:00'),
  row('美国空袭伊朗军事基地', '五角大楼称这一说法系误传。', '2026-07-10T14:04:33+08:00'),
  row('报道称美国空袭伊朗军事基地', '伊朗官方表示，此事并未发生。', '2026-07-10T14:04:33+08:00'),
]) {
  assert.notEqual(classifyImpact(candidate, nowMs).category, '地缘政治', candidate.title);
  assert.ok(!classifyImpact(candidate, nowMs).reasons.includes('T1:地缘政治'), candidate.title);
}

for (const candidate of [
  row('俄军炮击乌克兰边境城市', '乌克兰军方确认炮火造成设施受损。', '2026-07-10T14:04:34+08:00'),
  row('俄罗斯再次入侵乌克兰领土', '乌克兰军方称地面部队越过边境。', '2026-07-10T14:04:34+08:00'),
  row('朝鲜试射新型导弹', '韩国军方确认导弹落入海域。', '2026-07-10T14:04:34+08:00'),
  row('伊朗扣押美国油轮', '伊朗军方称船只已被带往港口。', '2026-07-10T14:04:34+08:00'),
  row('美军没有停止对伊朗军事目标的打击', '伊朗军方称空袭仍在持续。', '2026-07-10T14:04:34+08:00'),
  row('美军并未暂停对伊朗的空袭', '行动仍在持续。', '2026-07-10T14:04:34+08:00'),
  row('美军从未中断对伊朗的打击', '行动仍在持续。', '2026-07-10T14:04:34+08:00'),
  row('美国否认此次空袭行动针对平民，但确认空袭已经发生', '军方确认行动已执行。', '2026-07-10T14:04:34+08:00'),
  row('美国否认空袭报道中的伤亡数字，但确认空袭已经发生', '军方确认行动已执行。', '2026-07-10T14:04:34+08:00'),
  row('美国否认空袭违反国际法，但确认行动发生', '军方确认行动已执行。', '2026-07-10T14:04:34+08:00'),
  row('美国否认空袭使用某型武器，但确认行动发生', '军方确认行动已执行。', '2026-07-10T14:04:34+08:00'),
  row('美军空袭伊朗基地，公司随后发布航运风险软件', '空袭事实由军方确认。', '2026-07-10T14:04:34+08:00'),
  row('美军空袭伊朗基地后发布航运风险软件', '空袭事实由军方确认。', '2026-07-10T14:04:34+08:00'),
  row('美军空袭伊朗基地', '俄方否认空袭乌克兰，伊朗军方确认美军行动。', '2026-07-10T14:04:34+08:00'),
  row('美军空袭伊朗基地', '美国否认空袭叙利亚。', '2026-07-10T14:04:34+08:00'),
  row('以军击落伊朗无人机', '军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('俄军攻占乌克兰边境据点', '乌克兰军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('伊朗击沉美国军舰', '伊朗军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('朝鲜军队越境进入韩国', '韩国军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('乌克兰无人机突袭俄罗斯基地', '乌克兰军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('美国扣留伊朗油轮', '美国军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
  row('以军击毙伊朗高级军官', '军方确认事件发生。', '2026-07-10T14:04:34+08:00'),
]) {
  assert.equal(classifyImpact(candidate, nowMs).category, '地缘政治', candidate.title);
  assert.ok(classifyImpact(candidate, nowMs).reasons.includes('T1:地缘政治'), candidate.title);
}


for (const title of [
  '美国空袭伊朗设施但否认造成平民伤亡',
  '美国总统签署制裁伊朗方案',
]) {
  const candidate = row(title, '标题声明真实国家行动。', '2026-07-10T14:04:32+08:00');
  assert.equal(classifyImpact(candidate, nowMs).category, '地缘政治', title);
  assert.ok(classifyImpact(candidate, nowMs).reasons.includes('T1:地缘政治'), title);
}

for (const title of [
  '美国13月PPI年率5.5%',
  '美国16月PPI年率5.5%',
  '美国123月PPI年率5.5%',
  '美国十三月PPI年率5.5%',
]) {
  assert.equal(identifyEventFamily(row(title, '数据已经公布。', '2026-07-10T14:04:12+08:00')), null);
}

const multiTopicRoundupWithPpiBody = row(
  '美股盘前要闻一览：英伟达VERA RUBIN投产，中国版Apple智能完成备案',
  '1、美国6月PPI月率-0.3%，预期0%；美国6月PPI年率5.5%，预期6.2%。2、英伟达项目投入生产。',
  '2026-07-10T14:05:00+08:00',
);
assert.equal(identifyEventFamily(multiTopicRoundupWithPpiBody), null);
assert.notEqual(classifyImpact(multiTopicRoundupWithPpiBody, nowMs).priority_bucket, 'macro_policy');

const grossMarginStory = row(
  'DeepSeek年化收入逼近5亿美元，V4 API毛利率超50%',
  '企业收入、融资和API毛利率上升，经营流动性改善。',
  '2026-07-10T13:58:00+08:00',
);
assert.notEqual(classifyImpact(grossMarginStory, nowMs).priority_bucket, 'macro_policy');

for (const title of [
  'DeepSeek上调API毛利率预期至55%',
  '某公司毛利率目标50%',
  '企业净利率预期20%',
]) {
  assert.notEqual(
    classifyImpact(row(title, '企业经营指标更新。', '2026-07-10T13:57:30+08:00'), nowMs).priority_bucket,
    'macro_policy',
  );
}

const productYieldStory = row(
  '某产品年化收益率升至8%',
  '该收益率来自产品经营表现，并非央行政策或国债市场。',
  '2026-07-10T13:57:00+08:00',
);
assert.notEqual(classifyImpact(productYieldStory, nowMs).priority_bucket, 'macro_policy');

const actualRateDecision = row(
  '美联储讨论下一次利率决定',
  'FOMC将根据通胀与就业数据评估政策利率路径。',
  '2026-07-10T13:56:00+08:00',
);
assert.equal(classifyImpact(actualRateDecision, nowMs).priority_bucket, 'macro_policy');

const gdpRelease = row(
  '美国二季度GDP年化季率增长2.4%，高于预期',
  '美国经济增长数据正式公布。',
  '2026-07-10T13:56:50+08:00',
);
assert.equal(classifyImpact(gdpRelease, nowMs).priority_bucket, 'macro_policy');

assert.equal(classifyImpact(row(
  '美国二季度国内生产总值增长2.4%',
  '宏观经济数据正式公布。',
  '2026-07-10T13:56:45+08:00',
), nowMs).priority_bucket, 'macro_policy');
assert.notEqual(classifyImpact(row(
  'GDPR数据合规规则更新',
  '该规则名称包含相邻英文字母，但并非GDP数据。',
  '2026-07-10T13:56:44+08:00',
), nowMs).priority_bucket, 'macro_policy');
for (const title of [
  'GDP代币6月上线后上涨20%',
  'GDP Token项目完成融资',
  'GDP Labs公布AI业务毛利率50%',
  'GDP生态代币上涨20%',
  '代币GDP上涨20%',
]) {
  assert.notEqual(
    classifyImpact(row(title, '企业或项目动态。', '2026-07-10T13:56:43+08:00'), nowMs).priority_bucket,
    'macro_policy',
  );
}

const ppiWithGdpRevision = row(
  '美国6月PPI年率5.5%，GDP预期同步下修',
  'PPI实际值低于预期，经济增长预期同步调整。',
  '2026-07-10T13:56:40+08:00',
);
assert.equal(classifyImpact(ppiWithGdpRevision, nowMs).priority_bucket, 'macro_policy');

const equitiesWithDirectFedSignal = row(
  '美股因美联储降息预期升温而上涨',
  'FOMC政策预期推动风险资产重新定价。',
  '2026-07-10T13:56:30+08:00',
);
const equitiesFedPriority = classifyImpact(equitiesWithDirectFedSignal, nowMs);
assert.equal(equitiesFedPriority.priority_bucket, 'macro_policy');
assert.ok(equitiesFedPriority.reasons.includes('override:明确Tier1信号优先于行业词'));

const pureEquitiesStory = row(
  '美股芯片板块上涨',
  '企业盈利推动行业表现。',
  '2026-07-10T13:56:20+08:00',
);
assert.equal(classifyImpact(pureEquitiesStory, nowMs).priority_bucket, 'secondary_sector');

const personalKnifeAttack = row(
  '韩国一投资类YouTuber遭观众持刀袭击，疑因跟投股票巨亏引发',
  '据《朝鲜日报》报道，韩国釜山一名股票投资类 YouTuber 遭订阅者持刀连续刺伤，嫌疑人疑因跟投亏损而实施袭击。',
  '2026-07-10T13:56:19+08:00',
);
const personalKnifeAttackPriority = classifyImpact(personalKnifeAttack, nowMs);
assert.notEqual(personalKnifeAttackPriority.priority_bucket, 'macro_policy');
assert.equal(personalKnifeAttackPriority.directness_label, 'low_btc_relevance');

const iranStrike = row(
  '特朗普讨论扩大对伊朗打击范围',
  '白宫讨论针对伊朗军事目标的大规模攻势。',
  '2026-07-10T13:56:18+08:00',
);
const iranStrikePriority = classifyImpact(iranStrike, nowMs);
assert.equal(iranStrikePriority.priority_bucket, 'macro_policy');
assert.equal(iranStrikePriority.category, '地缘政治');
assert.ok(iranStrikePriority.reasons.includes('T1:地缘政治'));
assert.ok(!iranStrikePriority.reasons.includes('T1:货币政策'));

for (const candidate of [
  row('平台封锁用户账号', '普通内容审核事件。', '2026-07-10T13:56:17+08:00'),
  row('韩国政府打击网络诈骗团伙', '警方处理普通刑事案件。', '2026-07-10T13:56:16+08:00'),
  row('AI公司与供应商发生冲突', '双方就商业合同产生争议。', '2026-07-10T13:56:15+08:00'),
  row('某公司董事会选举完成', '股东完成内部治理程序。', '2026-07-10T13:56:14+08:00'),
  row('芯片价格战开战', '企业通过降价争夺市场份额。', '2026-07-10T13:56:13+08:00'),
  row('主播与观众发生冲突', '私人纠纷继续升级。', '2026-07-10T13:56:12+08:00'),
  row('平台用户遭袭传闻', '调查显示不涉及军事冲突或外交政策。', '2026-07-10T13:56:11+08:00'),
  row('美国公司与中国供应商发生冲突', '双方就商业合同产生争议。', '2026-07-10T13:56:10+08:00'),
  row('美国公司与中国公司董事会联合选举', '股东完成跨境企业治理程序。', '2026-07-10T13:56:09+08:00'),
  row('韩国平台用户遭袭传闻', '调查显示未涉及军事冲突或外交政策。', '2026-07-10T13:56:08+08:00'),
  row(
    '美国公司与中国供应商发生冲突',
    '合同仅涉及军方无人机零部件交付，属于企业纠纷。',
    '2026-07-10T13:56:07+08:00',
  ),
  row(
    '美国公司与中国公司董事会联合选举',
    '两国政府均未参与，属于企业治理。',
    '2026-07-10T13:56:06+08:00',
  ),
  row('韩国公司发布战争题材游戏', '产品面向普通消费者。', '2026-07-10T13:56:05+08:00'),
  row('美国公司展示导弹概念模型', '这是普通商业展品。', '2026-07-10T13:56:04+08:00'),
  row('韩国个人发布战争回忆录', '内容是个人历史回忆。', '2026-07-10T13:56:03+08:00'),
  row('美国公司发布新型导弹防御芯片', '企业发布普通产品。', '2026-07-10T13:56:02+08:00'),
  row('美国公司军事目标管理平台上线', '企业软件产品正式上线。', '2026-07-10T13:56:01+08:00'),
  row(
    '美国公司董事会选举，总统出席活动',
    '政府没有参与董事会治理。',
    '2026-07-10T13:56:00+08:00',
  ),
  row(
    '美国未对伊朗发动打击，美军继续提高戒备',
    '目前没有发生军事行动。',
    '2026-07-10T13:55:59+08:00',
  ),
  row(
    '美国与伊朗未发生军事冲突，美军继续提高戒备',
    '双方没有交火。',
    '2026-07-10T13:55:58+08:00',
  ),
]) {
  assert.notEqual(classifyImpact(candidate, nowMs).priority_bucket, 'macro_policy', candidate.title);
}

for (const candidate of [
  row(
    '霍尔木兹海峡附近船只遭袭',
    '伊朗军方称无人机行动针对航运封锁区域。',
    '2026-07-10T13:56:10+08:00',
  ),
  row(
    '分析：美伊正陷入霍尔木兹海峡消耗战',
    '美国与伊朗围绕航运、导弹和军事目标持续对峙。',
    '2026-07-10T13:56:09+08:00',
  ),
  row(
    '法国总统选举进入第二轮',
    '候选人继续争取议会与选民支持。',
    '2026-07-10T13:56:08+08:00',
  ),
  row(
    '美国政府宣布制裁中国军工公司',
    '外交部门公布相关国家政策。',
    '2026-07-10T13:56:07+08:00',
  ),
  row(
    '美国军方打击伊朗国有石油公司设施',
    '美军称行动针对军事目标。',
    '2026-07-10T13:56:06+08:00',
  ),
  row(
    '美军空袭伊朗石油公司设施',
    '军方确认这是针对军事目标的行动。',
    '2026-07-10T13:56:05+08:00',
  ),
  row(
    '伊朗向以色列发射导弹',
    '军方称导弹袭击已发生。',
    '2026-07-10T13:56:04+08:00',
  ),
]) {
  const priority = classifyImpact(candidate, nowMs);
  assert.equal(priority.priority_bucket, 'macro_policy');
  assert.equal(priority.category, '地缘政治');
}

const nonCryptoSecStory = row(
  'AI公司因SEC调查而下调盈利预期',
  '事件仅涉及传统企业财务披露合规。',
  '2026-07-10T13:56:15+08:00',
);
const nonCryptoSecPriority = classifyImpact(nonCryptoSecStory, nowMs);
assert.equal(nonCryptoSecPriority.priority_bucket, 'secondary_sector');
assert.ok(!nonCryptoSecPriority.reasons.includes('T1:监管立法'));

for (const title of [
  'SEC调查某上市公司财务披露',
  '司法部对波音展开反垄断执法',
]) {
  assert.notEqual(
    classifyImpact(row(title, '传统企业监管事件。', '2026-07-10T13:56:14+08:00'), nowMs).priority_bucket,
    'regulatory_policy',
  );
}
const traditionalExchangeRegulation = classifyImpact(row(
  'SEC调查纽约证券交易所',
  '传统证券市场监管事件。',
  '2026-07-10T13:56:14+08:00',
), nowMs);
assert.equal(traditionalExchangeRegulation.priority_bucket, 'secondary_sector');
assert.equal(traditionalExchangeRegulation.directness_label, 'low_btc_relevance');

const cryptoRegulatoryAiStory = row(
  'AI公司因数字资产政策调整加密业务',
  '监管规则直接涉及数字资产。',
  '2026-07-10T13:56:14+08:00',
);
assert.equal(classifyImpact(cryptoRegulatoryAiStory, nowMs).priority_bucket, 'regulatory_policy');
assert.equal(classifyImpact(row(
  'SEC调查Coinbase',
  '监管调查直接涉及加密资产交易平台。',
  '2026-07-10T13:56:13+08:00',
), nowMs).priority_bucket, 'regulatory_policy');
assert.equal(classifyImpact(row(
  '欧盟MiCA正式生效',
  '加密资产监管制度进入执行阶段。',
  '2026-07-10T13:56:12+08:00',
), nowMs).priority_bucket, 'regulatory_policy');
assert.equal(classifyImpact(row(
  'SEC批准现货比特币ETF',
  '监管决定直接涉及BTC现货ETF。',
  '2026-07-10T13:56:13+08:00',
), nowMs).priority_bucket, 'regulatory_policy');

const personalMacroRetrospective = row(
  '炒股哥复盘美联储降息预期',
  '个人投资复盘，不是新的宏观事件。',
  '2026-07-10T13:56:10+08:00',
);
assert.equal(classifyImpact(personalMacroRetrospective, nowMs).priority_bucket, 'secondary_sector');

const ppiToken = row(
  '美国PPI代币6月上线后上涨20%',
  '该项目为同名代币，不是宏观数据发布。',
  '2026-07-10T13:55:30+08:00',
);
assert.notEqual(classifyImpact(ppiToken, nowMs).priority_bucket, 'macro_policy');
assert.equal(identifyEventFamily(ppiToken), null);

const fullChinesePpiName = row(
  '美国6月工业生产者出厂价格指数同比增长5.5%',
  '实际值低于市场预期。',
  '2026-07-10T13:55:20+08:00',
);
assert.equal(classifyImpact(fullChinesePpiName, nowMs).priority_bucket, 'macro_policy');
assert.equal(identifyEventFamily(fullChinesePpiName)?.reported_period, '2026-06');

const releaseDateAndPeriod = row(
  '美国7月15日公布6月PPI年率5.5%',
  '本次公布值低于市场预期。',
  '2026-07-10T13:55:10+08:00',
);
assert.equal(identifyEventFamily(releaseDateAndPeriod)?.reported_period, '2026-06');

const ppiPeriodAfterIndicatorAnnual = row(
  '美国PPI 6月年率5.5%',
  '美国PPI实际发布。',
  '2026-07-10T13:55:09+08:00',
);
const ppiPeriodAfterIndicatorMonthly = row(
  '美国PPI 6月月率-0.3%',
  '美国PPI实际发布。',
  '2026-07-10T13:55:08+08:00',
);
assert.equal(
  identifyEventFamily(ppiPeriodAfterIndicatorAnnual)?.key,
  identifyEventFamily(ppiPeriodAfterIndicatorMonthly)?.key,
);
assert.equal(identifyEventFamily(ppiPeriodAfterIndicatorAnnual)?.key, identifyEventFamily(ppiAnnual)?.key);
assert.equal(identifyEventFamily(ppiPeriodAfterIndicatorMonthly)?.key, identifyEventFamily(ppiAnnual)?.key);

const ppi2026 = row(
  '美国2026年6月PPI年率5.5%',
  '美国PPI实际发布。',
  '2026-07-10T13:55:07+08:00',
);
const ppi2025 = row(
  '美国2025年6月PPI月率-0.3%',
  '美国PPI历史修正值发布。',
  '2026-07-10T13:55:06+08:00',
);
assert.notEqual(identifyEventFamily(ppi2026)?.key, identifyEventFamily(ppi2025)?.key);

const ppiChineseDecember = row(
  '美国十二月PPI年率5.5%',
  '美国PPI实际发布。',
  '2027-01-10T13:55:05+08:00',
);
assert.equal(identifyEventFamily(ppiChineseDecember)?.reported_period, '2026-12');
assert.equal(identifyEventFamily(row(
  '美国去年六月PPI年率5.5%',
  '历史数据回顾。',
  '2026-07-10T13:55:05+08:00',
)), null);

const ppiPreview = row(
  '美国6月PPI年率预期低于前值',
  '数据尚未公布。',
  '2026-07-10T13:55:05+08:00',
);
assert.equal(identifyEventFamily(ppiPreview), null);

const crossJurisdiction = row(
  '欧盟与欧元区6月PPI年率5.5%',
  '标题包含两个地区，禁止推断事件身份。',
  '2026-07-10T13:55:04+08:00',
);
assert.equal(identifyEventFamily(crossJurisdiction), null);

const fedOnChinaPpi = row(
  '美联储关注中国6月PPI年率5.5%',
  '显式数据地区是中国。',
  '2026-07-10T13:55:03+08:00',
);
assert.equal(identifyEventFamily(fedOnChinaPpi)?.jurisdiction, '中国');

const chinaPpi = row(
  '中国6月PPI年率5.5%',
  '中国PPI实际发布。',
  '2026-07-10T13:55:02+08:00',
);
const usMayPpi = row(
  '美国5月PPI年率5.5%',
  '美国5月PPI实际发布。',
  '2026-07-10T13:55:01+08:00',
);
assert.notEqual(identifyEventFamily(ppiAnnual)?.key, identifyEventFamily(chinaPpi)?.key);
assert.notEqual(identifyEventFamily(ppiAnnual)?.key, identifyEventFamily(usMayPpi)?.key);
assert.equal(identifyEventFamily(row(
  '美国6月CPI年率3.0%',
  '美国CPI实际发布。',
  '2026-07-10T13:55:00+08:00',
)), null);

const eventFamilyCandidates = [
  ppiChineseMonthNarrative,
  ppiAnnual,
  ppiMonthly,
  actualRateDecision,
  row(
    '昨日比特币ETF录得净流入',
    '现货比特币ETF净流入2亿美元。',
    '2026-07-10T13:55:00+08:00',
  ),
  row(
    'AI企业公布季度收入',
    '该企业收入增长，属于非BTC行业叙事。',
    '2026-07-10T13:54:00+08:00',
  ),
].map((candidate) => ({
  ...candidate,
  analysis_priority: classifyImpact(candidate, nowMs),
}));
const distinctTopThree = selectTopRowsByPriority(eventFamilyCandidates, 3);
assert.equal(distinctTopThree.length, 3);
assert.equal(distinctTopThree.filter((candidate) => candidate.title.includes('PPI')).length, 1);
const selectedPpi = distinctTopThree.find((candidate) => candidate.title.includes('PPI'));
assert.equal(selectedPpi.event_family.member_count, 3);
assert.deepEqual(
  selectedPpi.event_family.members.map((candidate) => candidate.title),
  [ppiChineseMonthNarrative.title, ppiAnnual.title, ppiMonthly.title],
);
assert.deepEqual(
  selectedPpi.event_family.members,
  eventFamilyCandidates.filter((candidate) => candidate.title.includes('PPI')),
);
assert.ok(distinctTopThree.some((candidate) => candidate.title.includes('利率决定')));
assert.ok(distinctTopThree.some((candidate) => candidate.title.includes('ETF')));
assert.ok(!eventFamilyCandidates.some((candidate) => 'event_family' in candidate));

console.log('[PASS] BlockBeats priority regression');
