// Unique FOMC rate-expectation capture entry.
//
// Closed state machine:
//   1. exactly one CME UI attempt;
//   2. valid CME => select primary and make zero Kalshi calls;
//   3. only a sealed eligible CME technical failure => one Kalshi call;
//   4. every other state => hard stop.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  RATE_ARTIFACTS,
  buildProvenance,
  decideProvider,
  hashRecord,
  sha256File,
  validateCmeResult,
  validateProviderContract,
  writeJsonAtomic,
} from './rate_expectation_state.js';


const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const CONTRACT_PATH = path.join(
  ROOT,
  'data_sources',
  'rate_expectation_provider_contract.json',
);
const CONTRACT = validateProviderContract(
  JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8')),
);


function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}


const OUT_DIR = path.join(ROOT, 'data_sources', 'inbox', localDate());
const CAPTURE_RUN_ID = String(
  process.env.RATE_EXPECTATION_CAPTURE_RUN_ID || crypto.randomUUID(),
).trim();
const PATHS = Object.freeze(Object.fromEntries(
  Object.entries(RATE_ARTIFACTS).map(([key, basename]) => [key, path.join(OUT_DIR, basename)]),
));


function run(executable, args, extraEnv = {}) {
  return new Promise((resolve) => {
    const child = spawn(executable, args, {
      cwd: ROOT,
      stdio: 'inherit',
      env: { ...process.env, ...extraEnv },
    });
    child.on('exit', (code) => resolve(code ?? -1));
    child.on('error', () => resolve(-1));
  });
}


function cleanupMutableOutputs() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  for (const artifactPath of Object.values(PATHS)) {
    if (fs.existsSync(artifactPath)) fs.unlinkSync(artifactPath);
  }
}


function readJson(filePath, label) {
  if (!fs.existsSync(filePath)) throw new Error(`${label} is missing`);
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}


function verifyPrimaryArtifact(result) {
  if (result.status !== 'passed') throw new Error('CME primary did not pass');
  const outputPath = PATHS.primaryImage;
  if (!fs.existsSync(outputPath)) throw new Error('CME primary image is missing');
  const stat = fs.statSync(outputPath);
  if (
    !stat.isFile()
    || stat.size !== result.output.bytes
    || sha256File(outputPath) !== result.output.sha256
  ) {
    throw new Error('CME primary image differs from sealed result');
  }
}


function validateKalshiRaw(raw, cmeResult) {
  if (
    raw?.schema_version !== CONTRACT.kalshi_raw_schema_version
    || raw.capture_run_id !== CAPTURE_RUN_ID
    || raw.provider_id !== CONTRACT.selection_modes.kalshi_plan_c_fallback.provider_id
    || raw.series_ticker !== CONTRACT.kalshi.series_ticker
    || raw.cme_attempt_sha256 !== cmeResult.attempt_sha256
    || !/^[0-9a-f]{64}$/.test(String(raw.raw_sha256 || ''))
    || raw.raw_sha256 !== hashRecord(raw, 'raw_sha256')
  ) {
    throw new Error('Kalshi raw artifact identity or hash is invalid');
  }
  return raw;
}


function writeProvenance(selectionMode, fallbackReasonCode) {
  const provenance = buildProvenance({
    captureRunId: CAPTURE_RUN_ID,
    contract: CONTRACT,
    selectionMode,
    fallbackReasonCode,
  });
  for (const basename of provenance.selected_artifact_paths) {
    if (basename === RATE_ARTIFACTS.provenance) continue;
    const artifactPath = path.join(OUT_DIR, basename);
    const stat = fs.statSync(artifactPath);
    if (!stat.isFile() || stat.size <= 0) {
      throw new Error(`selected rate expectation artifact is invalid: ${basename}`);
    }
  }
  writeJsonAtomic(PATHS.provenance, provenance);
  return provenance;
}


async function main() {
  if (!/^[0-9a-f-]{16,64}$/i.test(CAPTURE_RUN_ID)) {
    throw new Error('invalid rate expectation capture_run_id');
  }
  cleanupMutableOutputs();

  const cmeCode = await run(process.execPath, [path.join(__dirname, 'capture_fedwatch.js')], {
    RATE_EXPECTATION_CAPTURE_RUN_ID: CAPTURE_RUN_ID,
    CME_FEDWATCH_RESULT_PATH: PATHS.cmeResult,
    CME_FEDWATCH_OUTPUT_PATH: PATHS.primaryImage,
  });
  const cmeResult = validateCmeResult(
    readJson(PATHS.cmeResult, RATE_ARTIFACTS.cmeResult),
    CONTRACT,
  );
  if (cmeResult.capture_run_id !== CAPTURE_RUN_ID) {
    throw new Error('CME result belongs to another capture run');
  }
  const decision = decideProvider(cmeResult, CONTRACT);

  if (decision.action === 'select_primary') {
    if (cmeCode !== 0) throw new Error('CME process code contradicts passed result');
    verifyPrimaryArtifact(cmeResult);
    writeProvenance('cme_primary', 'none');
    return 0;
  }

  if (fs.existsSync(PATHS.primaryImage)) {
    throw new Error('failed CME result cannot retain a primary image');
  }
  if (decision.action === 'hard_stop') {
    return 3;
  }
  if (cmeCode !== 2) {
    throw new Error('eligible CME result has an inconsistent process code');
  }
  const pythonExecutable = String(process.env.VNEXT_PYTHON_EXECUTABLE || '').trim();
  if (!pythonExecutable) {
    throw new Error('VNEXT_PYTHON_EXECUTABLE is required before the Plan C call');
  }

  // This is the only Kalshi process invocation in this capture run.
  const kalshiCode = await run(
    process.execPath,
    [path.join(__dirname, 'capture_kalshi_feddecision.js')],
    {
      RATE_EXPECTATION_CAPTURE_RUN_ID: CAPTURE_RUN_ID,
      CME_FEDWATCH_ATTEMPT_SHA256: cmeResult.attempt_sha256,
      KALSHI_FEDDECISION_RAW_PATH: PATHS.kalshiRaw,
    },
  );
  if (kalshiCode !== 0) return 3;
  validateKalshiRaw(
    readJson(PATHS.kalshiRaw, RATE_ARTIFACTS.kalshiRaw),
    cmeResult,
  );

  const normalizeCode = await run(pythonExecutable, [
    '-m',
    'runtime_vnext.rate_expectation',
    'normalize-kalshi',
    '--contract',
    CONTRACT_PATH,
    '--cme-result',
    PATHS.cmeResult,
    '--raw',
    PATHS.kalshiRaw,
    '--output',
    PATHS.normalized,
  ]);
  if (normalizeCode !== 0 || !fs.existsSync(PATHS.normalized)) return 3;
  writeProvenance('kalshi_plan_c_fallback', decision.fallback_reason_code);
  return 0;
}


try {
  process.exitCode = await main();
} catch (error) {
  if (fs.existsSync(PATHS.provenance)) fs.unlinkSync(PATHS.provenance);
  console.error(`[rate-expectation] ${error.message}`);
  process.exitCode = 3;
}
