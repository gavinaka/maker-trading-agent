// Conservative midday/evening delta capture.
//
// Business logic stays unchanged:
//   - every report slot refreshes all six required sources;
//   - any core failure triggers one bounded full capture fallback;
//   - all scripts remain sequential because browser profiles are exclusive.

import { spawn } from 'child_process';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import {
  acquireCaptureLock,
  immutableManifestPath,
  releaseCaptureLock,
  requireWorkflowLease,
  snapshotEvidence,
  writeImmutableJson,
} from './capture_lock.js';
import {
  RATE_ARTIFACTS,
  decideFullCaptureFallback,
  providerSummaryFromProvenance,
} from './rate_expectation_state.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const PLAN_ONLY = process.argv.includes('--plan-only');
const VALID_DELTA_SLOTS = new Set(['midday', 'evening']);
const RUN_ID = crypto.randomUUID();
const profilePolicy = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'scoring', 'scoring_contract.json'), 'utf8'),
).tradingview_profile_policy;
const rateExpectationProviderContract = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'data_sources', 'rate_expectation_provider_contract.json'),
  'utf8',
));
const TRADINGVIEW_PROFILE_BINDING = Object.freeze({
  schema_version: profilePolicy.state_sidecar_binding_schema_version,
  capture_run_id: RUN_ID,
  capture_nonce: crypto.randomUUID(),
  sidecar_filename: profilePolicy.state_sidecar_filename,
  sidecar_schema_version: profilePolicy.state_sidecar_schema_version,
});

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return null;
  const value = process.argv[index + 1];
  if (!value || value.startsWith('--')) {
    throw new Error(`${name} requires a value`);
  }
  return value;
}

function parseSlot() {
  const slot = argValue('--slot');
  const legacyEvening = process.argv.includes('--evening');
  if (slot && legacyEvening && slot !== 'evening') {
    throw new Error('--evening cannot be combined with --slot other than evening');
  }
  const resolved = slot ?? (legacyEvening ? 'evening' : null);
  if (!resolved) {
    throw new Error('missing --slot; capture_delta.js requires --slot midday|evening');
  }
  if (!VALID_DELTA_SLOTS.has(resolved)) {
    throw new Error(`unsupported delta slot: ${resolved}; use --slot midday|evening`);
  }
  return resolved;
}

function parseOrExit(fn) {
  try {
    return fn();
  } catch (error) {
    console.error(error.message);
    process.exit(3);
  }
}

const SLOT = parseOrExit(parseSlot);
const LEASE_TOKEN = parseOrExit(() => argValue('--lease-token') ?? '');

function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function fileSha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function run(script, args = [], extraEnv = {}) {
  return new Promise((resolve) => {
    console.log(`\n===== delta ▶ ${script} =====`);
    const child = spawn(process.execPath, [path.join(__dirname, script), ...args], {
      stdio: 'inherit',
      env: { ...process.env, ...extraEnv },
    });
    child.on('exit', (code) => resolve(code ?? -1));
    child.on('error', () => resolve(-1));
  });
}

const date = localDate();

const corePlan = [
  { script: 'capture_blockbeats.js', reason: 'news cursor may advance' },
  { script: 'capture_coinglass.js', reason: '1H orderflow is decision-dynamic' },
  { script: 'capture_exo.js', reason: 'orderflow confirmation is decision-dynamic' },
  {
    script: 'capture_rate_expectation.js',
    reason: 'macro source must be refreshed for every report slot',
  },
  {
    script: 'capture_farside_btc_etf.js',
    reason: 'spot ETF flow confirms spot-side liquidity direction and health',
  },
  {
    script: 'capture_tv.js',
    reason: 'visual source has no trustworthy remote change token; refresh conservatively',
  },
];

const plan = {
  schema_version: '1.0',
  date,
  slot: SLOT,
  generated_at: new Date().toISOString(),
  mode: 'conservative_delta',
  captures: corePlan,
  auxiliary: ['capture_liqheatmap.js'],
  fallback: (
    'capture_all.js once only for eligible non-rate core evidence failure; '
    + 'rate-provider failure or consumed Plan C hard-stops without full fallback'
  ),
};

console.log(JSON.stringify(plan, null, 2));
if (PLAN_ONLY) process.exit(0);

async function main() {
  const lease = requireWorkflowLease(ROOT, date, SLOT, LEASE_TOKEN);
  const lock = acquireCaptureLock(ROOT);
  const started = Date.now();
  const startedAt = new Date().toISOString();
  try {
    await run('cleanup.js');
    const results = {};
    for (const item of corePlan) {
      const captureEnv = {};
      if (item.script === 'capture_tv.js') {
        Object.assign(captureEnv, {
          TRADINGVIEW_CAPTURE_RUN_ID: TRADINGVIEW_PROFILE_BINDING.capture_run_id,
          TRADINGVIEW_CAPTURE_NONCE: TRADINGVIEW_PROFILE_BINDING.capture_nonce,
        });
      }
      if (item.script === 'capture_rate_expectation.js') {
        Object.assign(captureEnv, {
          RATE_EXPECTATION_CAPTURE_RUN_ID: RUN_ID,
        });
      }
      results[item.script] = await run(item.script, [], captureEnv);
    }
    let rateExpectationProvider = null;
    if (results['capture_rate_expectation.js'] === 0) {
      try {
        const provenance = JSON.parse(fs.readFileSync(
          path.join(
            ROOT,
            'data_sources',
            'inbox',
            date,
            RATE_ARTIFACTS.provenance,
          ),
          'utf8',
        ));
        rateExpectationProvider = providerSummaryFromProvenance(
          provenance,
          RUN_ID,
          rateExpectationProviderContract,
        );
      } catch {
        results['capture_rate_expectation.js'] = 2;
      }
    }
    const auxiliaryCode = await run('capture_liqheatmap.js');
    const failed = Object.entries(results)
      .filter(([, code]) => code !== 0)
      .map(([script]) => script);
    if (auxiliaryCode !== 0) failed.push('capture_liqheatmap.js');

    let fullFallbackUsed = false;
    let fullFallbackSuppressedReasonCode = null;
    let fallbackCode = null;
    let fallbackManifest = null;
    let fallbackPayload = null;
    if (failed.length) {
      console.error(`delta capture failed: ${failed.join(', ')}`);
      const fallbackDecision = decideFullCaptureFallback(
        failed,
        rateExpectationProvider,
      );
      fullFallbackSuppressedReasonCode = fallbackDecision.suppressed_reason_code;
      if (fallbackDecision.run_full_fallback) {
        console.error('running one bounded full capture fallback');
        fullFallbackUsed = true;
        const fallbackRunId = crypto.randomUUID();
        const fallbackPath = immutableManifestPath(
          ROOT,
          date,
          SLOT,
          'full_recollection',
          fallbackRunId,
        );
        fallbackCode = await run(
          'capture_all.js',
          [
            '--slot', SLOT,
            '--lease-token', LEASE_TOKEN,
            '--run-id', fallbackRunId,
          ],
          { TRADING_CAPTURE_LOCK_TOKEN: lock.token },
        );
        if (fallbackCode === 0) {
          if (!fs.existsSync(fallbackPath)) {
            throw new Error('full fallback succeeded without an immutable manifest');
          }
          fallbackPayload = JSON.parse(fs.readFileSync(fallbackPath, 'utf8'));
          if (
            fallbackPayload.success !== true
            || !fallbackPayload.evidence_snapshot
            || !fallbackPayload.tradingview_profile_binding
            || !fallbackPayload.rate_expectation_provider
          ) {
            throw new Error('full fallback manifest is missing bound evidence identity');
          }
          fallbackManifest = {
            path: path.relative(path.join(ROOT, 'runtime_state', date), fallbackPath)
              .replaceAll('\\', '/'),
            sha256: fileSha256(fallbackPath),
          };
        }
      }
    }

    const success = failed.length === 0 || fallbackCode === 0;
    const fallbackSucceeded = fullFallbackUsed && fallbackCode === 0;
    const evidenceCaptureRunId = fallbackSucceeded
      ? fallbackPayload.evidence_capture_run_id
      : RUN_ID;
    const tradingviewProfileBinding = fallbackSucceeded
      ? fallbackPayload.tradingview_profile_binding
      : TRADINGVIEW_PROFILE_BINDING;
    const effectiveRateExpectationProvider = fallbackSucceeded
      ? fallbackPayload.rate_expectation_provider
      : rateExpectationProvider;
    let evidenceSnapshot = null;
    if (success && fallbackSucceeded) {
      evidenceSnapshot = fallbackPayload.evidence_snapshot;
    } else if (success) {
      evidenceSnapshot = snapshotEvidence(
        ROOT,
        date,
        SLOT,
        RUN_ID,
        startedAt,
        { tradingviewProfileBinding },
      );
    }
    const manifest = {
      ...plan,
      run_id: RUN_ID,
      evidence_capture_run_id: evidenceCaptureRunId,
      tradingview_profile_binding: tradingviewProfileBinding,
      workflow_lease_id: lease.lease_id,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - started,
      results,
      auxiliary_code: auxiliaryCode,
      full_fallback_used: fullFallbackUsed,
      full_fallback_suppressed_reason_code: fullFallbackSuppressedReasonCode,
      rate_expectation_provider: effectiveRateExpectationProvider,
      fallback_code: fallbackCode,
      fallback_manifest: fallbackManifest,
      fallback_reasons: failed.length
        ? [`core capture failed or invalid: ${failed.join(', ')}`]
        : [],
      evidence_snapshot: evidenceSnapshot,
      success,
    };
    const manifestPath = immutableManifestPath(
      ROOT,
      date,
      SLOT,
      'conservative_delta',
      RUN_ID,
    );
    writeImmutableJson(manifestPath, manifest);
    console.log(`DELTA_MANIFEST=${manifestPath}`);
    return manifest.success ? 0 : 2;
  } finally {
    releaseCaptureLock(lock);
  }
}

try {
  process.exitCode = await main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 3;
}
