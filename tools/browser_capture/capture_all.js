// 一键跑齐四源采集(顺序执行,全部落当天 inbox/<YYYY-MM-DD>/)
//   ② Coinglass  → coinglass.png        (盘口四面板 1H)
//   ① Exocharts  → exocharts.png         (Bybit BTCUSD/D/Tick120/Bid-Ask/FPBS/VWAP)
//   ④ CME        → fedwatch.png          (真实 FedWatch Tool 控件)
//   ③ TradingView→ tradingview_btc_{1d,4h,1h,15m}.png (登录态+手绘线+规整缩放)
//
// 用法:  node capture_all.js   (或 npm run all)
// 前置:  TV/Exo 的登录在 ~/.tv_chrome_profile;采集期间相关独立 Chrome 窗口需保持关闭。

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = [
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

const t0 = Date.now();
// 先清理过期动态图(只留最近 N 天·绝不碰当天在用的图),再抓今天四源
await run('cleanup.js');
const results = {};
for (const s of SCRIPTS) results[s] = await run(s);

console.log(`\n========== 采集有效性汇总(用时 ${Math.round((Date.now() - t0) / 1000)}s)==========`);
const bad = [];
for (const s of SCRIPTS) {
  const c = results[s];
  const tag = c === 0 ? 'OK' : c === 2 ? 'INVALID(登录墙/空图/陈旧/面板错)' : `ERROR(码${c})`;
  console.log(`  ${c === 0 ? '✓' : '✗'} ${s} → ${tag}`);
  if (c !== 0) bad.push(s);
}
if (bad.length) {
  console.log(`\n🟥 [all] 有源未通过有效性门: ${bad.join(', ')}`);
  console.log('🟥 按五源硬停规则:该源视为缺失 → 重登(普通 Chrome 开 --user-data-dir=%USERPROFILE%\\.tv_chrome_profile 让用户登一次)或回退用户手动截图;禁拿无效图当数据读。');
  process.exit(2);
}
console.log('\n[all] ✓ 四源全部通过有效性门,可进入评分/出稿。');
process.exit(0);
