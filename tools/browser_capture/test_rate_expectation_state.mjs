import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  RATE_ARTIFACTS,
  buildProvenance,
  decideFullCaptureFallback,
  decideProvider,
  hashRecord,
  validateCmeResult,
  validateProviderContract,
  validateProvenance,
} from './rate_expectation_state.js';
import { selectNextEvent } from './capture_kalshi_feddecision.js';


const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const CONTRACT = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'data_sources', 'rate_expectation_provider_contract.json'),
  'utf8',
));
const RUN_ID = '11111111-1111-4111-8111-111111111111';


function cmeResult({ status = 'passed', defectCode = null } = {}) {
  const result = {
    schema_version: CONTRACT.cme_attempt_schema_version,
    capture_run_id: RUN_ID,
    provider_id: CONTRACT.selection_modes.cme_primary.provider_id,
    status,
    defect_code: defectCode,
    started_at: '2026-07-19T01:00:00.000Z',
    completed_at: '2026-07-19T01:00:01.000Z',
    output: status === 'passed' ? {
      path: RATE_ARTIFACTS.primaryImage,
      sha256: 'a'.repeat(64),
      bytes: 42,
    } : null,
    attempt_sha256: '',
  };
  result.attempt_sha256 = hashRecord(result, 'attempt_sha256');
  return result;
}


function kalshiEvent(eventTicker, {
  strikeDate = '2026-07-29T18:00:00.000Z',
  closeTime = '2026-07-29T17:59:00.000Z',
  provisional = undefined,
} = {}) {
  return {
    event_ticker: eventTicker,
    series_ticker: CONTRACT.kalshi.series_ticker,
    strike_date: strikeDate,
    mutually_exclusive: true,
    markets: CONTRACT.kalshi.outcome_mappings.map((mapping, index) => {
      const market = {
        event_ticker: eventTicker,
        ticker: `${eventTicker}-M${index}`,
        status: 'active',
        close_time: closeTime,
        custom_strike: {
          [mapping.custom_strike_key]: mapping.custom_strike_value,
        },
        subtitle: mapping.subtitle,
        yes_bid_dollars: '0.1000',
        yes_ask_dollars: '0.2000',
      };
      if (provisional !== undefined) market.is_provisional = provisional;
      return market;
    }),
  };
}


test('valid CME primary selects CME and does not authorize Plan C', () => {
  const decision = decideProvider(cmeResult(), CONTRACT);
  assert.deepEqual(decision, {
    action: 'select_primary',
    selection_mode: 'cme_primary',
    provider_id: 'cme_fedwatch_ui',
    fallback_reason_code: 'none',
  });
});


test('only a sealed eligible CME technical failure authorizes one Plan C attempt', () => {
  for (const defectCode of CONTRACT.cme.eligible_fallback_codes) {
    const decision = decideProvider(
      cmeResult({ status: 'failed', defectCode }),
      CONTRACT,
    );
    assert.equal(decision.action, 'attempt_plan_c_once');
    assert.equal(decision.fallback_reason_code, defectCode);
  }
});


test('non-fallback and unknown CME failures hard stop', () => {
  for (const defectCode of [
    ...CONTRACT.cme.non_fallback_codes,
    'cme_unknown_future_failure',
  ]) {
    const decision = decideProvider(
      cmeResult({ status: 'failed', defectCode }),
      CONTRACT,
    );
    assert.equal(decision.action, 'hard_stop');
  }
});


test('tampered CME result is rejected before provider selection', () => {
  const result = cmeResult();
  result.output.bytes += 1;
  assert.throws(
    () => validateCmeResult(result, CONTRACT),
    /identity or hash is invalid/,
  );
});


test('provider contract cannot weaken or reorder the CME attempt schema', () => {
  const mutations = [
    (contract) => contract.cme.attempt_artifact.exact_fields.pop(),
    (contract) => contract.cme.attempt_artifact.status_values.reverse(),
    (contract) => contract.cme.attempt_artifact.passed_output_exact_fields.reverse(),
  ];
  for (const mutate of mutations) {
    const changed = structuredClone(CONTRACT);
    mutate(changed);
    assert.throws(
      () => validateProviderContract(changed),
      /attempt artifact contract is incomplete/,
    );
  }
});


test('primary provenance selects only CME artifacts', () => {
  const provenance = buildProvenance({
    captureRunId: RUN_ID,
    contract: CONTRACT,
    selectionMode: 'cme_primary',
    fallbackReasonCode: 'none',
  });
  validateProvenance(provenance, RUN_ID, CONTRACT);
  assert.deepEqual(provenance.raw_artifact_paths, []);
  assert.equal(provenance.normalized_artifact_path, null);
  assert.deepEqual(provenance.selected_artifact_paths, [
    'cme_fedwatch_result.json',
    'fedwatch.png',
  ]);
});


test('Plan C provenance has exact no-PNG artifact set and eligible reason', () => {
  const provenance = buildProvenance({
    captureRunId: RUN_ID,
    contract: CONTRACT,
    selectionMode: 'kalshi_plan_c_fallback',
    fallbackReasonCode: 'cme_tool_content_load_error',
  });
  validateProvenance(provenance, RUN_ID, CONTRACT);
  assert.deepEqual(provenance.selected_artifact_paths, [
    'cme_fedwatch_result.json',
    'fedwatch.json',
    'kalshi_feddecision_raw.json',
  ]);
  assert.equal(provenance.selected_artifact_paths.some((name) => name.endsWith('.png')), false);
});


test('provenance cannot mix primary and Plan C artifacts', () => {
  const provenance = buildProvenance({
    captureRunId: RUN_ID,
    contract: CONTRACT,
    selectionMode: 'cme_primary',
    fallbackReasonCode: 'none',
  });
  provenance.raw_artifact_paths = ['kalshi_feddecision_raw.json'];
  provenance.provenance_sha256 = hashRecord(provenance, 'provenance_sha256');
  assert.throws(
    () => validateProvenance(provenance, RUN_ID, CONTRACT),
    /artifact selection is invalid/,
  );
});


test('hash-valid provenance with an unknown fallback reason is rejected', () => {
  const provenance = buildProvenance({
    captureRunId: RUN_ID,
    contract: CONTRACT,
    selectionMode: 'kalshi_plan_c_fallback',
    fallbackReasonCode: 'cme_tool_content_load_error',
  });
  provenance.fallback_reason_code = 'cme_unknown_future_failure';
  provenance.provenance_sha256 = hashRecord(provenance, 'provenance_sha256');
  assert.throws(
    () => validateProvenance(provenance, RUN_ID, CONTRACT),
    /fallback reason is invalid/,
  );
});


test('rate-expectation failure never triggers a second full capture', () => {
  assert.deepEqual(
    decideFullCaptureFallback(['capture_rate_expectation.js'], null),
    {
      run_full_fallback: false,
      suppressed_reason_code: 'rate_expectation_capture_failed',
    },
  );
});


test('consumed Plan C prevents a second provider attempt after another source fails', () => {
  assert.deepEqual(
    decideFullCaptureFallback(
      ['capture_coinglass.js'],
      { provider_fallback_used: true },
    ),
    {
      run_full_fallback: false,
      suppressed_reason_code: 'plan_c_attempt_already_consumed',
    },
  );
});


test('CME primary preserves the existing full recollection for another source failure', () => {
  assert.deepEqual(
    decideFullCaptureFallback(
      ['capture_coinglass.js'],
      { provider_fallback_used: false },
    ),
    { run_full_fallback: true, suppressed_reason_code: null },
  );
});


test('Kalshi selection rejects two complete events at the same earliest strike', () => {
  const nowMs = Date.parse('2026-07-19T00:00:00.000Z');
  assert.throws(
    () => selectNextEvent({
      events: [kalshiEvent('KXFEDDECISION-A'), kalshiEvent('KXFEDDECISION-B')],
    }, nowMs),
    /ambiguous earliest/,
  );
});


test('Kalshi selection requires a strictly future event and open market window', () => {
  const nowText = '2026-07-19T00:00:00.000Z';
  const nowMs = Date.parse(nowText);
  assert.throws(
    () => selectNextEvent({
      events: [kalshiEvent('KXFEDDECISION-EQUAL', { strikeDate: nowText })],
    }, nowMs),
    /no future/,
  );
  assert.throws(
    () => selectNextEvent({
      events: [kalshiEvent('KXFEDDECISION-CLOSED', { closeTime: nowText })],
    }, nowMs),
    /structurally incomplete/,
  );
});


test('Kalshi selection rejects provisional markets before any history request', () => {
  const nowMs = Date.parse('2026-07-19T00:00:00.000Z');
  assert.throws(
    () => selectNextEvent({
      events: [kalshiEvent('KXFEDDECISION-PROVISIONAL', { provisional: true })],
    }, nowMs),
    /structurally incomplete/,
  );
  assert.equal(
    selectNextEvent({
      events: [kalshiEvent('KXFEDDECISION-FINAL', { provisional: false })],
    }, nowMs).event.event_ticker,
    'KXFEDDECISION-FINAL',
  );
});


test('an incomplete earliest event hard-stops instead of skipping to a later event', () => {
  const nowMs = Date.parse('2026-07-19T00:00:00.000Z');
  const earliest = kalshiEvent('KXFEDDECISION-EARLIEST', {
    strikeDate: '2026-07-20T18:00:00.000Z',
  });
  earliest.markets.pop();
  const later = kalshiEvent('KXFEDDECISION-LATER', {
    strikeDate: '2026-09-01T18:00:00.000Z',
  });
  assert.throws(
    () => selectNextEvent({ events: [later, earliest] }, nowMs),
    /earliest .* structurally incomplete/,
  );
});


test('one capture-shape fixture is accepted by JS lineage and Python normalizer', () => {
  const python = String(
    process.env.VNEXT_PYTHON_EXECUTABLE
      || (process.platform === 'win32' ? 'py' : 'python3'),
  );
  const fixtureProcess = spawnSync(python, [
    '-c',
    [
      'import json',
      'from tests.test_rate_expectation import _fixture',
      'contract, cme, raw = _fixture()',
      'print(json.dumps({"contract": contract, "cme": cme, "raw": raw}, ensure_ascii=False))',
    ].join(';'),
  ], {
    cwd: ROOT,
    encoding: 'utf8',
  });
  assert.equal(fixtureProcess.status, 0, fixtureProcess.stderr);
  const fixture = JSON.parse(fixtureProcess.stdout);
  validateCmeResult(fixture.cme, fixture.contract);
  assert.equal(
    fixture.raw.cme_attempt_sha256,
    fixture.cme.attempt_sha256,
  );
  assert.equal(fixture.raw.raw_sha256, hashRecord(fixture.raw, 'raw_sha256'));

  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'rate-expectation-interop-'));
  try {
    const contractPath = path.join(temporary, 'contract.json');
    const cmePath = path.join(temporary, 'cme.json');
    const rawPath = path.join(temporary, 'raw.json');
    const outputPath = path.join(temporary, 'fedwatch.json');
    fs.writeFileSync(contractPath, JSON.stringify(fixture.contract));
    fs.writeFileSync(cmePath, JSON.stringify(fixture.cme));
    fs.writeFileSync(rawPath, JSON.stringify(fixture.raw));
    const normalized = spawnSync(python, [
      '-m',
      'runtime_vnext.rate_expectation',
      'normalize-kalshi',
      '--contract', contractPath,
      '--cme-result', cmePath,
      '--raw', rawPath,
      '--output', outputPath,
    ], {
      cwd: ROOT,
      encoding: 'utf8',
    });
    assert.equal(normalized.status, 0, normalized.stderr);
    const payload = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
    assert.equal(payload.selection_mode, 'kalshi_plan_c_fallback');
    assert.equal(payload.capture_run_id, fixture.cme.capture_run_id);
    assert.equal(payload.bindings.cme_attempt_sha256, fixture.cme.attempt_sha256);
    assert.equal(payload.bindings.kalshi_raw_sha256, fixture.raw.raw_sha256);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
