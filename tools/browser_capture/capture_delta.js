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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const PLAN_ONLY = process.argv.includes('--plan-only');
const VALID_DELTA_SLOTS = new Set(['midday', 'evening']);
const RUN_ID = crypto.randomUUID();

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
    script: 'capture_fedwatch.js',
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
    'capture_all.js once only for failed, missing, stale, or invalid core evidence'
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
      results[item.script] = await run(item.script);
    }
    const auxiliaryCode = await run('capture_liqheatmap.js');
    const failed = Object.entries(results)
      .filter(([, code]) => code !== 0)
      .map(([script]) => script);

    let fullFallbackUsed = false;
    let fallbackCode = null;
    let fallbackManifest = null;
    if (failed.length) {
      console.error(`delta capture failed: ${failed.join(', ')}`);
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
        fallbackManifest = {
          path: path.relative(path.join(ROOT, 'runtime_state', date), fallbackPath)
            .replaceAll('\\', '/'),
          sha256: fileSha256(fallbackPath),
        };
      }
    }

    const evidenceSnapshot = snapshotEvidence(ROOT, date, SLOT, RUN_ID);
    const manifest = {
      ...plan,
      run_id: RUN_ID,
      workflow_lease_id: lease.lease_id,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - started,
      results,
      auxiliary_code: auxiliaryCode,
      full_fallback_used: fullFallbackUsed,
      fallback_code: fallbackCode,
      fallback_manifest: fallbackManifest,
      fallback_reasons: failed.length
        ? [`core capture failed or invalid: ${failed.join(', ')}`]
        : [],
      evidence_snapshot: evidenceSnapshot,
      success: failed.length === 0 || fallbackCode === 0,
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
