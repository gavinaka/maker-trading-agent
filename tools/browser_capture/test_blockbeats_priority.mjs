import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { classifyImpact, compareRowsByPriority } from './blockbeats_priority.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const samplePath = path.join(repoRoot, 'data_sources', 'inbox', '2026-07-06', 'blockbeats.json');
const sample = JSON.parse(fs.readFileSync(samplePath, 'utf8'));
const nowMs = Date.parse(sample.window_end);

const scoredRows = sample.candidate_rows.map((row) => ({
  ...row,
  analysis_priority: classifyImpact(row, nowMs, sample.capture_window_hours),
}));
const selectedTitles = [...scoredRows]
  .sort(compareRowsByPriority)
  .slice(0, 3)
  .map((row) => row.title);

assert.equal(
  selectedTitles[0],
  '美联储加息预期降温，比特币、以太坊及黄金延续反弹行情',
);
assert.ok(selectedTitles.some((title) => title.includes('纽约梅隆银行')));
assert.ok(!selectedTitles.some((title) => /TCC|Meme|MEME/.test(title)));
assert.ok(!selectedTitles.some((title) => /AI存储赛道|AI资本开支|字节炒股赚3000万/.test(title)));

const tcc = scoredRows.find((row) => row.title.includes('TCC'));
assert.equal(tcc.analysis_priority.priority_bucket, 'meme_other');
assert.equal(tcc.analysis_priority.directness_label, 'low_btc_relevance');

const awsSector = scoredRows.find((row) => row.title.includes('AWS'));
assert.equal(awsSector.analysis_priority.priority_bucket, 'secondary_sector');
assert.equal(awsSector.analysis_priority.directness_label, 'low_btc_relevance');

const nyMellonMacro = scoredRows.find((row) => row.title.includes('纽约梅隆银行'));
assert.equal(nyMellonMacro.analysis_priority.priority_bucket, 'macro_policy');
assert.equal(nyMellonMacro.analysis_priority.directness_label, 'direct_macro_or_regulatory');

const btcDerivativesRisk = scoredRows.find((row) => row.body.includes('Murphy'));
assert.equal(btcDerivativesRisk.analysis_priority.priority_bucket, 'crypto_market_structure');

const ethLabs = scoredRows.find((row) => row.title.includes('EthLabs'));
assert.notEqual(ethLabs.analysis_priority.priority_bucket, 'macro_policy');

console.log('[PASS] BlockBeats priority regression');
