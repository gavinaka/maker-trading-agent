import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const STALE_MS = 2 * 60 * 60 * 1000;
const EVIDENCE_FILES = [
  'blockbeats.json',
  'blockbeats.png',
  'coinglass.png',
  'exocharts.png',
  'fedwatch.json',
  'fedwatch.png',
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

export function snapshotEvidence(root, date, slot, runId) {
  if (!/^[0-9a-f-]{16,64}$/.test(runId)) throw new Error('invalid evidence run id');
  const stateDir = path.join(root, 'runtime_state', date);
  const inbox = path.join(root, 'data_sources', 'inbox', date);
  const target = path.join(stateDir, 'evidence', slot, runId);
  if (fs.existsSync(target)) {
    throw new Error(`evidence snapshot already exists: ${target}`);
  }
  fs.mkdirSync(target, { recursive: true });
  const names = new Set(EVIDENCE_FILES);
  if (fs.existsSync(inbox)) {
    for (const name of fs.readdirSync(inbox)) {
      if (/^liqheatmap_.*\.png$/i.test(name)) names.add(name);
    }
  }
  const files = [];
  for (const name of [...names].sort()) {
    const source = path.join(inbox, name);
    if (!fs.existsSync(source)) continue;
    const stat = fs.statSync(source);
    if (!stat.isFile() || stat.size <= 0) continue;
    const destination = path.join(target, name);
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
    files.push({
      path: name,
      sha256: sha256File(destination),
      size: fs.statSync(destination).size,
    });
  }
  return {
    root: path.relative(stateDir, target).replaceAll('\\', '/'),
    created_at: new Date().toISOString(),
    files,
  };
}
