import assert from 'node:assert/strict';
import { classifyImpact, compareRowsByPriority } from './blockbeats_priority.js';

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

console.log('[PASS] BlockBeats priority regression');
