import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

import {
  RATE_ARTIFACTS,
  validateProvenance,
} from './rate_expectation_state.js';

const STALE_MS = 2 * 60 * 60 * 1000;
const MODULE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const RATE_EXPECTATION_PROVIDER_CONTRACT = JSON.parse(fs.readFileSync(
  path.join(
    MODULE_ROOT,
    'data_sources',
    'rate_expectation_provider_contract.json',
  ),
  'utf8',
));
const REQUIRED_EVIDENCE_FILES = [
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
];
const OPTIONAL_EVIDENCE_FILES = [];

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

export function acquireCaptureLock(root) {
  const lockPath = path.join(root, 'runtime_state', '.capture.lock');
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });

  const inheritedToken = process.env.TRADING_CAPTURE_LOCK_TOKEN;
  if (inheritedToken) {
    if (!fs.existsSync(lockPath)) {
      throw new Error('inherited capture lock is missing');
    }
    const current = fs.readFileSync(lockPath, 'utf8').trim();
    if (current !== inheritedToken) {
      throw new Error('inherited capture lock owner mismatch');
    }
    return { lockPath, token: inheritedToken, owned: false };
  }

  const token = `${process.pid}:${crypto.randomUUID()}`;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const descriptor = fs.openSync(lockPath, 'wx');
      fs.writeFileSync(descriptor, token, 'utf8');
      fs.closeSync(descriptor);
      return { lockPath, token, owned: true };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const age = Date.now() - fs.statSync(lockPath).mtimeMs;
      if (attempt === 0 && age > STALE_MS) {
        fs.unlinkSync(lockPath);
        continue;
      }
      throw new Error(`capture already running: ${lockPath}`);
    }
  }
  throw new Error(`cannot acquire capture lock: ${lockPath}`);
}

export function releaseCaptureLock(lock) {
  if (!lock?.owned || !fs.existsSync(lock.lockPath)) return;
  const current = fs.readFileSync(lock.lockPath, 'utf8').trim();
  if (current === lock.token) fs.unlinkSync(lock.lockPath);
}

export function workflowLeaseId(token) {
  return crypto.createHash('sha256').update(token, 'ascii').digest('hex');
}

export function requireWorkflowLease(root, date, slot, token) {
  if (!token) throw new Error('missing --lease-token; run begin-session first');
  const leasePath = path.join(root, 'runtime_state', 'workflow_lease.json');
  if (!fs.existsSync(leasePath)) throw new Error('workflow lease is missing');
  const lease = JSON.parse(fs.readFileSync(leasePath, 'utf8'));
  const expectedId = workflowLeaseId(token);
  const checks = {
    active: lease.status === 'active',
    date: lease.trading_date === date,
    slot: lease.slot === slot,
    token: lease.token === token,
    lease_id: lease.lease_id === expectedId,
  };
  const failed = Object.entries(checks)
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
  if (failed.length) {
    throw new Error(`workflow lease validation failed: ${failed.join(', ')}`);
  }
  return lease;
}

export function immutableManifestPath(root, date, slot, mode, runId) {
  if (!/^[0-9a-f-]{16,64}$/.test(runId)) throw new Error('invalid capture run id');
  return path.join(
    root,
    'runtime_state',
    date,
    'captures',
    slot,
    `${mode}_${runId}.json`,
  );
}

export function writeImmutableJson(target, payload) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const descriptor = fs.openSync(target, 'wx');
  try {
    fs.writeFileSync(descriptor, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
}

export function profileBindingMatchesRun(binding, captureRunId) {
  if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return false;
  const expectedKeys = new Set([
    'schema_version',
    'capture_run_id',
    'capture_nonce',
    'sidecar_filename',
    'sidecar_schema_version',
  ]);
  if (
    Object.keys(binding).length !== expectedKeys.size
    || Object.keys(binding).some((key) => !expectedKeys.has(key))
  ) return false;
  if (
    binding.schema_version !== 'tradingview-profile-capture-binding-v1'
    || binding.capture_run_id !== captureRunId
    || !/^[0-9a-f-]{16,64}$/i.test(String(binding.capture_run_id || ''))
    || !/^[0-9a-f-]{16,64}$/i.test(String(binding.capture_nonce || ''))
    || path.basename(String(binding.sidecar_filename || '')) !== binding.sidecar_filename
    || !String(binding.sidecar_schema_version || '').startsWith('tradingview-profile-state-v')
  ) return false;
  return true;
}

export function profileSidecarMatchesBinding(filePath, binding, captureRunId = null) {
  const expectedRunId = captureRunId ?? binding?.capture_run_id;
  if (!profileBindingMatchesRun(binding, expectedRunId)) return false;
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile() || stat.size <= 0) return false;
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    return (
      payload
      && typeof payload === 'object'
      && !Array.isArray(payload)
      && payload.schema_version === binding.sidecar_schema_version
      && payload.capture_run_id === binding.capture_run_id
      && payload.capture_nonce === binding.capture_nonce
    );
  } catch {
    return false;
  }
}

export function snapshotEvidence(
  root,
  date,
  slot,
  runId,
  startedAt,
  { tradingviewProfileBinding = null } = {},
) {
  if (!/^[0-9a-f-]{16,64}$/.test(runId)) throw new Error('invalid evidence run id');
  const startedAtMs = Date.parse(startedAt);
  if (!Number.isFinite(startedAtMs)) throw new Error('invalid evidence capture startedAt');
  if (
    tradingviewProfileBinding !== null
    && !profileBindingMatchesRun(tradingviewProfileBinding, runId)
  ) {
    throw new Error('TradingView profile binding does not match current evidence run');
  }
  const stateDir = path.join(root, 'runtime_state', date);
  const inbox = path.join(root, 'data_sources', 'inbox', date);
  const target = path.join(stateDir, 'evidence', slot, runId);
  if (fs.existsSync(target)) {
    throw new Error(`evidence snapshot already exists: ${target}`);
  }
  fs.mkdirSync(target, { recursive: true });
  const observedDate = new Date(`${date}T12:00:00+08:00`);
  const weekend = observedDate.getUTCDay() === 0 || observedDate.getUTCDay() === 6;
  const liquidationFiles = weekend
    ? ['liqheatmap_3d.png']
    : ['liqheatmap_48h.png', 'liqheatmap_24h.png'];
  const rateProvenancePath = path.join(inbox, RATE_ARTIFACTS.provenance);
  if (!fs.existsSync(rateProvenancePath)) {
    throw new Error(`current-run evidence incomplete: missing=${RATE_ARTIFACTS.provenance}`);
  }
  let rateProvenance;
  try {
    rateProvenance = validateProvenance(
      JSON.parse(fs.readFileSync(rateProvenancePath, 'utf8')),
      runId,
      RATE_EXPECTATION_PROVIDER_CONTRACT,
    );
  } catch (error) {
    throw new Error(`rate expectation provenance invalid: ${error.message}`);
  }
  const rateExpectationFiles = [
    ...rateProvenance.selected_artifact_paths,
    RATE_ARTIFACTS.provenance,
  ];
  const requiredNames = [
    ...REQUIRED_EVIDENCE_FILES,
    ...rateExpectationFiles,
    ...liquidationFiles,
  ];
  const names = new Set(requiredNames);
  for (const name of OPTIONAL_EVIDENCE_FILES) {
    if (fs.existsSync(path.join(inbox, name))) names.add(name);
  }
  const profileSidecarName = String(
    tradingviewProfileBinding?.sidecar_filename || '',
  );
  if (profileSidecarName) {
    const sidecarPath = path.join(inbox, profileSidecarName);
    if (profileSidecarMatchesBinding(sidecarPath, tradingviewProfileBinding, runId)) {
      names.add(profileSidecarName);
    }
  }
  const missing = [];
  const stale = [];
  const minimumMtimeMs = startedAtMs;
  for (const name of requiredNames) {
    const source = path.join(inbox, name);
    if (!fs.existsSync(source)) {
      missing.push(name);
      continue;
    }
    const stat = fs.statSync(source);
    if (!stat.isFile() || stat.size <= 0) missing.push(name);
    else if (stat.mtimeMs < minimumMtimeMs) stale.push(name);
  }
  if (missing.length || stale.length) {
    const defects = [];
    if (missing.length) defects.push(`missing=${missing.join(',')}`);
    if (stale.length) defects.push(`stale=${stale.join(',')}`);
    throw new Error(`current-run evidence incomplete: ${defects.join('; ')}`);
  }
  const files = [];
  for (const name of [...names].sort()) {
    const source = path.join(inbox, name);
    if (!fs.existsSync(source)) continue;
    const stat = fs.statSync(source);
    if (!stat.isFile() || stat.size <= 0 || stat.mtimeMs < minimumMtimeMs) continue;
    const destination = path.join(target, name);
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
    if (
      name === profileSidecarName
      && !profileSidecarMatchesBinding(destination, tradingviewProfileBinding, runId)
    ) {
      throw new Error('TradingView profile sidecar changed during evidence snapshot');
    }
    files.push({
      path: name,
      sha256: sha256File(destination),
      size: fs.statSync(destination).size,
      modified_at: stat.mtime.toISOString(),
    });
  }
  return {
    root: path.relative(stateDir, target).replaceAll('\\', '/'),
    created_at: new Date().toISOString(),
    files,
  };
}
