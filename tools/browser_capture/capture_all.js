// 一键跑齐六源采集(顺序执行,全部落当天 inbox/<YYYY-MM-DD>/)
//   ① BlockBeats → blockbeats.png + blockbeats.json (抓取前12小时重要快讯候选池 + 影响top3)
//   ② Coinglass  → coinglass.png        (盘口四面板 1H)
//   ③ Exocharts  → exocharts.png         (Bybit BTCUSD/D/Tick120/Bid-Ask/Imbalance/Candle None/FPBS/vWap)
//   ④ CME        → fedwatch.png          (真实 FedWatch Tool 控件)
//   ⑤ Farside    → farside_btc_etf.png + farside_btc_etf.json (BTC现货ETF流)
//   ⑥ TradingView→ tradingview_btc_{1d,4h,1h,15m}.png (登录态+手绘线+规整缩放)
//   [辅助] Coinglass 清算热力图 → liqheatmap_{3d|48h|24h}.png (辅助印证流动性猎杀概率·周末3天/周中48H+24H·非六源·失败只WARN)
//
// 用法:  legacy: node capture_all.js --slot morning --lease-token <token>
//        vNext:  node capture_all.js --slot morning --vnext-run-id <run-id>
// 前置:  TV/Exo 的登录在 ~/.tv_chrome_profile;采集期间相关独立 Chrome 窗口需保持关闭。

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
import { readCaptureResult } from './exocharts_ui_state.js';
import {
  RATE_ARTIFACTS,
  providerSummaryFromProvenance,
} from './rate_expectation_state.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const slotArg = process.argv.indexOf('--slot');
const SLOT = slotArg >= 0 ? process.argv[slotArg + 1] : 'morning';
const leaseArg = process.argv.indexOf('--lease-token');
const LEASE_TOKEN = leaseArg >= 0 ? process.argv[leaseArg + 1] : '';
const runArg = process.argv.indexOf('--run-id');
const RUN_ID = runArg >= 0 ? process.argv[runArg + 1] : crypto.randomUUID();
const vnextArg = process.argv.indexOf('--vnext-run-id');
const VNEXT_RUN_ID = vnextArg >= 0 ? process.argv[vnextArg + 1] : '';
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
if (!['morning', 'midday', 'evening'].includes(SLOT)) {
  throw new Error(`unsupported capture slot: ${SLOT}`);
}
const SCRIPTS = [
  'capture_blockbeats.js',
  'capture_coinglass.js',
  'capture_exo.js',
  'capture_rate_expectation.js',
  'capture_farside_btc_etf.js',
  'capture_tv.js',
];

// 子脚本退出码:0=有效;2=采到但无效(登录墙/空图/陈旧/面板错);其它=运行错
function run(script, extraEnv = {}) {
  return new Promise((resolve) => {
    console.log(`\n===== ▶ ${script} =====`);
    const child = spawn(process.execPath, [path.join(__dirname, script)], {
      stdio: 'inherit',
      env: { ...process.env, ...extraEnv },
    });
    child.on('exit', (code) => resolve(code ?? -1));
    child.on('error', () => resolve(-1));
  });
}

function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function recordHash(record, field) {
  const clean = { ...record };
  delete clean[field];
  delete clean.manifest_sha256;
  return crypto.createHash('sha256').update(stableJson(clean), 'utf8').digest('hex');
}

function diagnosticArtifact(filePath) {
  if (!fs.existsSync(filePath)) return null;
  const stat = fs.statSync(filePath);
  if (!stat.isFile() || stat.size <= 0) return null;
  return {
    path: path.relative(ROOT, filePath).replaceAll('\\', '/'),
    sha256: crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex'),
    bytes: stat.size,
  };
}

function requireScopedDiagnosticRoot(date) {
  const requested = String(process.env.VNEXT_CAPTURE_ATTEMPT_ROOT || '').trim();
  if (!requested) {
    return path.join(
      ROOT,
      'runtime_state',
      date,
      'capture_diagnostics',
      SLOT,
      RUN_ID,
    );
  }
  if (!VNEXT_RUN_ID) {
    throw new Error('vNext attempt diagnostic root requires --vnext-run-id');
  }
  const resolved = path.resolve(requested);
  const evidenceRoot = path.join(
    ROOT,
    'runtime_state_vnext',
    date,
    SLOT,
    VNEXT_RUN_ID,
    'evidence',
  );
  const relative = path.relative(evidenceRoot, resolved).replaceAll('\\', '/');
  if (!/^attempt-\d{3}$/.test(relative)) {
    throw new Error('vNext capture diagnostic root is not the current evidence attempt');
  }
  const attemptPath = path.join(resolved, 'attempt.json');
  if (!fs.existsSync(attemptPath)) {
    throw new Error('vNext capture attempt record is missing');
  }
  const attempt = JSON.parse(fs.readFileSync(attemptPath, 'utf8'));
  const attemptNumber = Number(relative.slice('attempt-'.length));
  const attemptChecks = {
    schema: attempt.schema_version === 'stage-attempt-vnext-v1',
    hash: attempt.attempt_sha256 === recordHash(attempt, 'attempt_sha256'),
    stage: attempt.stage === 'evidence',
    number: attempt.attempt === attemptNumber,
    status: attempt.status === 'running',
    owner_pid: attempt.owner_pid === process.ppid,
    open: !fs.existsSync(path.join(resolved, 'failure.json'))
      && !fs.existsSync(path.join(resolved, 'manifest.json')),
  };
  const failed = Object.entries(attemptChecks)
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
  if (failed.length) {
    throw new Error(`vNext capture attempt validation failed: ${failed.join(', ')}`);
  }
  return resolved;
}

function requireVnextActiveRun(root, date, slot, runId) {
  if (!/^run-[A-Za-z0-9_.-]{4,80}$/.test(runId)) {
    throw new Error('invalid --vnext-run-id');
  }
  const activePath = path.join(root, 'runtime_state_vnext', 'active_run.json');
  if (!fs.existsSync(activePath)) throw new Error('vNext active-run lease is missing');
  const active = JSON.parse(fs.readFileSync(activePath, 'utf8'));
  const checks = {
    schema: active.schema_version === 'active-run-vnext-v1',
    hash: active.active_sha256 === recordHash(active, 'active_sha256'),
    lifecycle: active.lifecycle === 'running',
    run_id: active.run_id === runId,
    date: active.trading_date === date,
    slot: active.slot === slot,
  };
  const failed = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
  if (failed.length) throw new Error(`vNext active-run validation failed: ${failed.join(', ')}`);
  const runPath = path.join(root, 'runtime_state_vnext', date, slot, runId, 'run.json');
  if (!fs.existsSync(runPath)) throw new Error('vNext run metadata is missing');
  const run = JSON.parse(fs.readFileSync(runPath, 'utf8'));
  if (
    run.run_sha256 !== recordHash(run, 'run_sha256')
    || run.run_id !== runId
    || run.trading_date !== date
    || run.slot !== slot
  ) {
    throw new Error('vNext run metadata differs from active-run lease');
  }
  return active;
}

async function main() {
  const date = localDate();
  if (VNEXT_RUN_ID && LEASE_TOKEN) {
    throw new Error('choose either legacy workflow lease or vNext active run, not both');
  }
  const vnextRun = VNEXT_RUN_ID
    ? requireVnextActiveRun(ROOT, date, SLOT, VNEXT_RUN_ID)
    : null;
  const lease = vnextRun ? null : requireWorkflowLease(ROOT, date, SLOT, LEASE_TOKEN);
  const lock = acquireCaptureLock(ROOT);
  const t0 = Date.now();
  const startedAt = new Date().toISOString();
  try {
    const diagnosticRoot = requireScopedDiagnosticRoot(date);
    const exochartsDiagnosticDir = path.join(diagnosticRoot, 'exocharts');
    const exochartsResultPath = path.join(exochartsDiagnosticDir, 'exocharts_result.json');
    // 先清理过期动态图(只留最近 N 天·绝不碰当天在用的图),再抓今天六源
    await run('cleanup.js');
    const results = {};
    for (const s of SCRIPTS) {
      const captureEnv = {};
      if (s === 'capture_exo.js') {
        Object.assign(captureEnv, {
          EXO_CAPTURE_DIAGNOSTIC_DIR: exochartsDiagnosticDir,
          EXO_CAPTURE_RESULT_PATH: exochartsResultPath,
        });
      }
      if (s === 'capture_tv.js') {
        Object.assign(captureEnv, {
          TRADINGVIEW_CAPTURE_RUN_ID: TRADINGVIEW_PROFILE_BINDING.capture_run_id,
          TRADINGVIEW_CAPTURE_NONCE: TRADINGVIEW_PROFILE_BINDING.capture_nonce,
        });
      }
      if (s === 'capture_rate_expectation.js') {
        Object.assign(captureEnv, {
          RATE_EXPECTATION_CAPTURE_RUN_ID: RUN_ID,
        });
      }
      results[s] = await run(s, captureEnv);
    }
    const exochartsResult = readCaptureResult(
      exochartsResultPath,
      results['capture_exo.js'],
    );
    const exochartsDiagnostic = {
      result: diagnosticArtifact(exochartsResultPath),
      json: diagnosticArtifact(path.join(
        exochartsDiagnosticDir,
        'exocharts_diagnostic.json',
      )),
      screenshot: diagnosticArtifact(path.join(
        exochartsDiagnosticDir,
        'exocharts_diagnostic.png',
      )),
    };
    if (exochartsResult.status !== 'passed' && results['capture_exo.js'] === 0) {
      results['capture_exo.js'] = 2;
    }
    let rateExpectationProvider = null;
    if (results['capture_rate_expectation.js'] === 0) {
      try {
        const provenancePath = path.join(
          ROOT,
          'data_sources',
          'inbox',
          date,
          RATE_ARTIFACTS.provenance,
        );
        const provenance = JSON.parse(fs.readFileSync(provenancePath, 'utf8'));
        rateExpectationProvider = providerSummaryFromProvenance(
          provenance,
          RUN_ID,
          rateExpectationProviderContract,
        );
      } catch {
        results['capture_rate_expectation.js'] = 2;
      }
    }

    // 清算图不单独决定方向，但属于 Coinglass 语义合同的必需辅助证据。
    const auxCode = await run('capture_liqheatmap.js');

    console.log(`\n========== 采集有效性汇总(用时 ${Math.round((Date.now() - t0) / 1000)}s)==========`);
    const bad = [];
    for (const s of SCRIPTS) {
      const c = results[s];
      const tag = c === 0 ? 'OK' : c === 2 ? 'INVALID(登录墙/空图/陈旧/面板错)' : `ERROR(码${c})`;
      console.log(`  ${c === 0 ? '✓' : '✗'} ${s} → ${tag}`);
      if (c !== 0) bad.push(s);
    }
    // 单列显示，但缺失或无效时必须阻断当前证据快照。
    {
      const tag = auxCode === 0 ? 'OK' : auxCode === 2 ? 'INVALID(必需辅助证据)' : `ERROR(码${auxCode})`;
      console.log(`  ${auxCode === 0 ? '✓' : '✗'} capture_liqheatmap.js → ${tag}  [辅助印证·缺失即硬停]`);
    }
    const success = bad.length === 0 && auxCode === 0;
    const sourceFailures = Object.fromEntries(
      bad.map((script) => [
        script,
        script === 'capture_exo.js' ? {
          defect_code: exochartsResult.defect_code,
          result: exochartsDiagnostic.result,
          diagnostic: exochartsResult.diagnostic_available ? {
            integrity: exochartsDiagnostic.json && exochartsDiagnostic.screenshot
              ? 'complete'
              : 'missing',
            json: exochartsDiagnostic.json,
            screenshot: exochartsDiagnostic.screenshot,
          } : {
            integrity: 'not_available',
            json: null,
            screenshot: null,
          },
        } : {
          defect_code: 'capture.source_failed',
        },
      ]),
    );
    const evidenceSnapshot = success
      ? snapshotEvidence(
        ROOT,
        date,
        SLOT,
        RUN_ID,
        startedAt,
        { tradingviewProfileBinding: TRADINGVIEW_PROFILE_BINDING },
      )
      : null;
    const manifest = {
      schema_version: '1.0',
      date,
      slot: SLOT,
      mode: SLOT === 'morning' ? 'full_base' : 'full_recollection',
      run_id: RUN_ID,
      evidence_capture_run_id: RUN_ID,
      tradingview_profile_binding: TRADINGVIEW_PROFILE_BINDING,
      workflow_lease_id: lease?.lease_id ?? null,
      vnext_active_run_id: vnextRun?.run_id ?? null,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - t0,
      results,
      source_failures: sourceFailures,
      auxiliary_code: auxCode,
      rate_expectation_provider: rateExpectationProvider,
      evidence_snapshot: evidenceSnapshot,
      success,
    };
    const manifestPath = immutableManifestPath(
      ROOT,
      manifest.date,
      SLOT,
      manifest.mode,
      RUN_ID,
    );
    writeImmutableJson(manifestPath, manifest);
    console.log(`FULL_CAPTURE_MANIFEST=${manifestPath}`);
    if (!success) {
      const failures = [...bad, ...(auxCode === 0 ? [] : ['capture_liqheatmap.js'])];
      console.log(`\n🟥 [all] 有源未通过有效性门: ${failures.join(', ')}`);
      console.log('🟥 按六源硬停规则:该源视为缺失 → 重登(普通 Chrome 开 --user-data-dir=%USERPROFILE%\\.tv_chrome_profile 让用户登一次)或回退用户手动截图/结构化数据;禁拿无效图当数据读。');
      return 2;
    }
    console.log('\n[all] ✓ 六源全部通过有效性门,可进入评分/出稿。');
    return 0;
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
