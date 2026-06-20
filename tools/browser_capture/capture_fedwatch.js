// CME FedWatch 自动截图(走独立 Chromium,绕过 Claude-in-Chrome 扩展黑名单)。
// FedWatch 无需登录;用独立(非默认)Chrome 配置目录以允许 Playwright 控制。
//
// 用法:
//   node capture_fedwatch.js [url]
//   HEADLESS=1 node capture_fedwatch.js   无头(默认有头,CME 反爬较敏感)
//
// 输出: data_sources/inbox/<YYYY-MM-DD>/fedwatch.png

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROFILE_DIR = path.join(os.homedir(), '.cme_chrome_profile'); // 非默认目录 → 可被控制

const URL = process.argv[2] || 'https://www.cmegroup.com/cn-s/markets/interest-rates/cme-fedwatch-tool.html';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });

const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
  channel: 'chrome',
  headless: process.env.HEADLESS === '1',
  viewport: { width: 2560, height: 1440 }, // 页面视口 2560×1440;工具为固定布局 iframe,截图为其原生尺寸
  screen: { width: 2560, height: 1440 },
  args: ['--window-position=0,0', '--window-size=2576,1500'],
});

const page = ctx.pages()[0] || (await ctx.newPage());

console.log(`[fedwatch] 打开: ${URL}`);
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});

// 关闭 OneTrust cookie 弹窗 —— 隐私优先:只「拒绝非必要」或「关闭」,绝不点「接受」
for (const sel of ['#onetrust-reject-all-handler', '.onetrust-close-btn-handler', '.ot-pc-refuse-all-handler']) {
  const btn = await page.$(sel);
  if (btn) { await btn.click().catch(() => {}); console.log(`[fedwatch] 关闭 cookie 弹窗(拒绝/关闭): ${sel}`); break; }
}

// 真实 FedWatch 工具在 quikstrike iframe(#cmeIframe-...)内,只截这个工具控件
const toolEl = await page.waitForSelector('iframe[id^="cmeIframe-"]', { timeout: 30000 });
await toolEl.scrollIntoViewIfNeeded().catch(() => {});

// 轮询等待工具本体渲染出概率图(在嵌套 frame 里出现 "Target Rate Probabilities")
let ready = false;
for (let i = 0; i < 20 && !ready; i++) {
  for (const f of page.frames()) {
    try { if (await f.$('text=Target Rate Probabilities')) { ready = true; break; } } catch {}
  }
  if (!ready) await page.waitForTimeout(1500);
}
console.log(`[fedwatch] 工具渲染就绪: ${ready}`);
await page.waitForTimeout(2500); // 让柱状图动画/表格定稿

const file = path.join(OUT_DIR, 'fedwatch.png');
await toolEl.screenshot({ path: file });
console.log(`[fedwatch] 已保存 ${file}`);

// 有效性机械门:工具概率图必须已渲染,否则截到的是空壳
if (!ready) {
  console.log('[fedwatch] VALIDITY: FAIL - FedWatch 工具未渲染(无 Target Rate Probabilities)');
  await ctx.close(); process.exit(2);
}
console.log('[fedwatch] VALIDITY: OK');
await ctx.close();
process.exit(0);
