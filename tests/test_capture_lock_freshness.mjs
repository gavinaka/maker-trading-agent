import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { snapshotEvidence } from '../tools/browser_capture/capture_lock.js';
import {
  buildProvenance,
  hashRecord,
} from '../tools/browser_capture/rate_expectation_state.js';


const CORE_FILES = [
  'blockbeats.json',
  'blockbeats.png',
  'coinglass.png',
  'exocharts.png',
  'farside_btc_etf.json',
  'farside_btc_etf.png',
  'tradingview_btc_1d.png',
  'tradingview_btc_1d_liq.png',
  'tradingview_btc_4h.png',
  'tradingview_btc_4h_liq.png',
  'tradingview_btc_1h.png',
  'tradingview_btc_1h_liq.png',
  'tradingview_btc_15m.png',
  'tradingview_btc_15m_liq.png',
  'liqheatmap_48h.png',
  'liqheatmap_24h.png',
];
const RUN_ID = '11111111-1111-4111-8111-111111111111';
const CONTRACT = JSON.parse(fs.readFileSync(
  new URL('../data_sources/rate_expectation_provider_contract.json', import.meta.url),
  'utf8',
));


function rateProvenance(mode) {
  return buildProvenance({
    captureRunId: RUN_ID,
    contract: CONTRACT,
    selectionMode: mode === 'primary' ? 'cme_primary' : 'kalshi_plan_c_fallback',
    fallbackReasonCode: mode === 'primary' ? 'none' : 'cme_tool_content_load_error',
  });
}


function seedRoot({ omit = null, stale = null, rateMode = 'primary' } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trading-capture-lock-'));
  const inbox = path.join(root, 'data_sources', 'inbox', '2026-07-13');
  fs.mkdirSync(inbox, { recursive: true });
  const provenance = rateProvenance(rateMode);
  const rateFiles = [
    ...provenance.selected_artifact_paths,
    'rate_expectation_provenance.json',
  ];
  for (const name of [...CORE_FILES, ...rateFiles]) {
    if (name === omit) continue;
    const target = path.join(inbox, name);
    fs.writeFileSync(
      target,
      name === 'rate_expectation_provenance.json'
        ? JSON.stringify(provenance)
        : 'fixture',
    );
    if (name === stale) {
      const old = new Date(Date.now() - 60 * 60 * 1000);
      fs.utimesSync(target, old, old);
    }
  }
  return root;
}


const PRIMARY_FILE_COUNT = CORE_FILES.length
  + rateProvenance('primary').selected_artifact_paths.length
  + 1;


function profileBinding(runId) {
  return {
    schema_version: 'tradingview-profile-capture-binding-v1',
    capture_run_id: runId,
    capture_nonce: '22222222-2222-4222-8222-222222222222',
    sidecar_filename: 'tradingview_profile_state.json',
    sidecar_schema_version: 'tradingview-profile-state-v2',
  };
}


test('snapshot accepts a complete current-run Monday evidence set', () => {
  const root = seedRoot();
  try {
    const snapshot = snapshotEvidence(
      root,
      '2026-07-13',
      'midday',
      RUN_ID,
      new Date(Date.now() - 1000).toISOString(),
    );
    assert.equal(snapshot.files.length, PRIMARY_FILE_COUNT);
    assert.ok(snapshot.files.every((item) => item.modified_at));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot uses the exact Plan C artifact set without a PNG', () => {
  const root = seedRoot({ rateMode: 'plan_c' });
  try {
    const snapshot = snapshotEvidence(
      root,
      '2026-07-13',
      'midday',
      RUN_ID,
      new Date(Date.now() - 1000).toISOString(),
    );
    const names = snapshot.files.map((item) => item.path);
    assert.ok(names.includes('cme_fedwatch_result.json'));
    assert.ok(names.includes('kalshi_feddecision_raw.json'));
    assert.ok(names.includes('fedwatch.json'));
    assert.ok(names.includes('rate_expectation_provenance.json'));
    assert.equal(names.includes('fedwatch.png'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot rejects a missing provider-selected rate artifact', () => {
  const root = seedRoot({ rateMode: 'plan_c', omit: 'kalshi_feddecision_raw.json' });
  try {
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        RUN_ID,
        new Date(Date.now() - 1000).toISOString(),
      ),
      /missing=kalshi_feddecision_raw\.json/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot rejects hash-valid provenance with an unknown fallback reason', () => {
  const root = seedRoot({ rateMode: 'plan_c' });
  try {
    const provenancePath = path.join(
      root,
      'data_sources',
      'inbox',
      '2026-07-13',
      'rate_expectation_provenance.json',
    );
    const provenance = JSON.parse(fs.readFileSync(provenancePath, 'utf8'));
    provenance.fallback_reason_code = 'cme_unknown_future_failure';
    provenance.provenance_sha256 = hashRecord(provenance, 'provenance_sha256');
    fs.writeFileSync(provenancePath, JSON.stringify(provenance));
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        RUN_ID,
        new Date(Date.now() - 1000).toISOString(),
      ),
      /fallback reason is invalid/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot rejects same-day files that predate the current capture', () => {
  const root = seedRoot({ stale: 'exocharts.png' });
  try {
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        RUN_ID,
        new Date(Date.now() - 5000).toISOString(),
      ),
      /stale=exocharts\.png/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot has no backward freshness tolerance', () => {
  const root = seedRoot();
  try {
    const startedAtMs = Date.now() - 5000;
    const stale = path.join(
      root,
      'data_sources',
      'inbox',
      '2026-07-13',
      'exocharts.png',
    );
    const beforeStart = new Date(startedAtMs - 1);
    fs.utimesSync(stale, beforeStart, beforeStart);
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        RUN_ID,
        new Date(startedAtMs).toISOString(),
      ),
      /stale=exocharts\.png/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot rejects a missing required liquidation window', () => {
  const root = seedRoot({ omit: 'liqheatmap_24h.png' });
  try {
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        RUN_ID,
        new Date(Date.now() - 1000).toISOString(),
      ),
      /missing=liqheatmap_24h\.png/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot rejects a profile binding from another capture run', () => {
  const root = seedRoot();
  try {
    const runId = '11111111-1111-4111-8111-111111111111';
    const otherRunBinding = profileBinding(
      '33333333-3333-4333-8333-333333333333',
    );
    assert.throws(
      () => snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        runId,
        new Date(Date.now() - 1000).toISOString(),
        { tradingviewProfileBinding: otherRunBinding },
      ),
      /profile binding does not match current evidence run/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('snapshot includes only the profile sidecar bound to this capture identity', () => {
  const root = seedRoot();
  try {
    const runId = '11111111-1111-4111-8111-111111111111';
    const binding = profileBinding(runId);
    const sidecar = path.join(
      root,
      'data_sources',
      'inbox',
      '2026-07-13',
      binding.sidecar_filename,
    );
    fs.writeFileSync(sidecar, JSON.stringify({
      schema_version: binding.sidecar_schema_version,
      capture_run_id: binding.capture_run_id,
      capture_nonce: binding.capture_nonce,
    }));
    const snapshot = snapshotEvidence(
      root,
      '2026-07-13',
      'midday',
      runId,
      new Date(Date.now() - 1000).toISOString(),
      { tradingviewProfileBinding: binding },
    );
    assert.ok(snapshot.files.some((item) => item.path === binding.sidecar_filename));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('stale or corrupt profile sidecar identity degrades locally and is not snapshotted', () => {
  for (const payload of [
    '{not-json',
    JSON.stringify({
      schema_version: 'tradingview-profile-state-v2',
      capture_run_id: '33333333-3333-4333-8333-333333333333',
      capture_nonce: '22222222-2222-4222-8222-222222222222',
    }),
    JSON.stringify({
      schema_version: 'tradingview-profile-state-v2',
      capture_run_id: '11111111-1111-4111-8111-111111111111',
      capture_nonce: '44444444-4444-4444-8444-444444444444',
    }),
  ]) {
    const root = seedRoot();
    try {
      const runId = '11111111-1111-4111-8111-111111111111';
      const binding = profileBinding(runId);
      const sidecar = path.join(
        root,
        'data_sources',
        'inbox',
        '2026-07-13',
        binding.sidecar_filename,
      );
      fs.writeFileSync(sidecar, payload);
      const snapshot = snapshotEvidence(
        root,
        '2026-07-13',
        'midday',
        runId,
        new Date(Date.now() - 1000).toISOString(),
        { tradingviewProfileBinding: binding },
      );
      assert.equal(
        snapshot.files.some((item) => item.path === binding.sidecar_filename),
        false,
      );
      assert.equal(snapshot.files.length, PRIMARY_FILE_COUNT);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
});
