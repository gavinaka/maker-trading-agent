// 一键跑齐五源采集(顺序执行,全部落当天 inbox/<YYYY-MM-DD>/)
//   ① BlockBeats → blockbeats.png + blockbeats.json (当日实时快讯)
//   ② Coinglass  → coinglass.png        (盘口四面板 1H)
//   ③ Exocharts  → exocharts.png         (Bybit BTCUSD/D/Tick120/Bid-Ask/FPBS/VWAP)
//   ④ CME        → fedwatch.png          (真实 FedWatch Tool 控件)
//   ⑤ TradingView→ tradingview_btc_{1d,4h,1h,15m}.png (登录态+手绘线+规整缩放)
//   [辅助] Coinglass 清算热力图 → liqheatmap_{3d|48h|24h}.png (辅助印证流动性猎杀概率·周末3天/周中48H+24H·非五源·失败只WARN)
//
// 用法:  node capture_all.js   (或 npm run all)
// 前置:  TV/Exo 的登录在 ~/.tv_chrome_profile;采集期间相关独立 Chrome 窗口需保持关闭。

import { spawn } from 'child_process';
import crypto from 'crypto';
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
const slotArg = process.argv.indexOf('--slot');
const SLOT = slotArg >= 0 ? process.argv[slotArg + 1] : 'morning';
const leaseArg = process.argv.indexOf('--lease-token');
const LEASE_TOKEN = leaseArg >= 0 ? process.argv[leaseArg + 1] : '';
const runArg = process.argv.indexOf('--run-id');
const RUN_ID = runArg >= 0 ? process.argv[runArg + 1] : crypto.randomUUID();
if (!['morning', 'midday', 'evening'].includes(SLOT)) {
  throw new Error(`unsupported capture slot: ${SLOT}`);
}
const SCRIPTS = [
  'capture_blockbeats.js',
  'capture_coinglass.js',
  'capture_exo.js',
  'capture_fedwatch.js',
  'capture_tv.js',
];

// 子脚本退出码:0=有效;2=采到但无效(登录墙/空图/陈旧/面板错);其它=运行错
function run(script) {
  return new Promise((resolve) => {
    console.log(`\n===== ▶ ${script} =====`);
    const child = spawn(process.execPath, [path.join(__dirname, script)], { stdio: 'inherit' });
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

async function main() {
  const date = localDate();
  const lease = requireWorkflowLease(ROOT, date, SLOT, LEASE_TOKEN);
  const lock = acquireCaptureLock(ROOT);
  const t0 = Date.now();
  const startedAt = new Date().toISOString();
  try {
    // 先清理过期动态图(只留最近 N 天·绝不碰当天在用的图),再抓今天五源
    await run('cleanup.js');
    const results = {};
    for (const s of SCRIPTS) results[s] = await run(s);

    // 辅助源(非五源·辅助印证流动性猎杀概率): Coinglass 清算热力图。失败只 WARN·不硬停。
    const auxCode = await run('capture_liqheatmap.js');

    console.log(`\n========== 采集有效性汇总(用时 ${Math.round((Date.now() - t0) / 1000)}s)==========`);
    const bad = [];
    for (const s of SCRIPTS) {
      const c = results[s];
      const tag = c === 0 ? 'OK' : c === 2 ? 'INVALID(登录墙/空图/陈旧/面板错)' : `ERROR(码${c})`;
      console.log(`  ${c === 0 ? '✓' : '✗'} ${s} → ${tag}`);
      if (c !== 0) bad.push(s);
    }
    // 辅助源单列(不计入五源硬停)
    {
      const tag = auxCode === 0 ? 'OK' : auxCode === 2 ? 'PARTIAL/INVALID(辅助·不硬停·登录墙?)' : `ERROR(码${auxCode})`;
      console.log(`  ${auxCode === 0 ? '✓' : '⚠'} capture_liqheatmap.js → ${tag}  [辅助印证·非五源]`);
    }
    const evidenceSnapshot = snapshotEvidence(ROOT, date, SLOT, RUN_ID);
    const success = bad.length === 0;
    const manifest = {
      schema_version: '1.0',
      date,
      slot: SLOT,
      mode: SLOT === 'morning' ? 'full_base' : 'full_recollection',
      run_id: RUN_ID,
      workflow_lease_id: lease.lease_id,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - t0,
      results,
      auxiliary_code: auxCode,
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
      console.log(`\n🟥 [all] 有源未通过有效性门: ${bad.join(', ')}`);
      console.log('🟥 按五源硬停规则:该源视为缺失 → 重登(普通 Chrome 开 --user-data-dir=%USERPROFILE%\\.tv_chrome_profile 让用户登一次)或回退用户手动截图;禁拿无效图当数据读。');
      return 2;
    }
    console.log('\n[all] ✓ 五源全部通过有效性门,可进入评分/出稿。');
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
