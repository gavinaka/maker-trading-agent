// Exocharts 足迹自动截图(Playwright/Chrome)。
// 目标对齐基准:Bybit BTCUSD · D · Tick×120 · Bid-Ask Profile · 底部 Footprint bar statistics。
//
// 用法: node capture_exo.js
// 输出: data_sources/inbox/<YYYY-MM-DD>/exocharts.png

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
// 与 TV 共用同一个已登录的独立 Chrome 配置目录(登录态在普通 Chrome 里就地建立)
const PROFILE_DIR = path.join(os.homedir(), '.tv_chrome_profile');
const URL = 'https://exocharts.com/web/';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });

const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
  channel: 'chrome', headless: process.env.HEADLESS === '1',
  viewport: { width: 2560, height: 1440 }, // 输出统一 2560×1440(提升读数准确性)
  screen: { width: 2560, height: 1440 },
  args: ['--window-position=0,0', '--window-size=2576,1500'],
});
const page = ctx.pages()[0] || (await ctx.newPage());

console.log(`[exo] 打开: ${URL}`);
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(12000);

// ---- 设置参数对齐基准:Bybit BTCUSD / D / Tick×120 / Bid-Ask Profile ----

// 1) 交易对 -> Bybit BTCUSD(弹窗按交易所分列,Bybit 列在 x≈152,其下 BTCUSD 即 Bybit 反向永续)
try {
  await page.locator('#topPeriodSelector').first().click();
  await page.waitForTimeout(1000);
  await page.locator('.labelRow', { hasText: /^BTCUSD$/ }).first().click();
  await page.waitForTimeout(2500); // 换标的后图表重载
  console.log('[exo] 交易对设为 Bybit BTCUSD');
} catch (e) { console.log('[exo] 交易对失败:', e.message); }

// 2) Tick 倍数 -> 120
try {
  const tick = page.locator('input.topTickMultiplier');
  await tick.click(); await tick.fill('120'); await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
  console.log('[exo] Tick 设为 120');
} catch (e) { console.log('[exo] Tick 失败:', e.message); }

// 3) 簇类型 -> Bid-Ask Profile
try {
  await page.locator('#topChartTypeSelector').click();
  await page.waitForTimeout(600);
  await page.getByText('Bid-Ask Profile', { exact: true }).first().click();
  await page.waitForTimeout(2000);
  console.log('[exo] 簇类型设为 Bid-Ask Profile');
} catch (e) { console.log('[exo] 簇类型失败:', e.message); }

// 4) FPBS = Footprint Bar Statistics(底部足迹统计面板)-> 打开
try {
  await page.getByText('FPBS', { exact: true }).first().click();
  await page.waitForTimeout(1500);
  console.log('[exo] 已点 FPBS(底部足迹统计)');
} catch (e) { console.log('[exo] FPBS 失败:', e.message); }

// 5) vWap -> 打开(基准里连接各日 profile 的黄色 VWAP 线)
try {
  await page.getByText('vWap', { exact: true }).first().click();
  await page.waitForTimeout(1500);
  console.log('[exo] 已点 vWap(VWAP 线)');
} catch (e) { console.log('[exo] vWap 失败:', e.message); }

// 关闭 "Trial user" 提示:定位弹窗盒子,点其右上角 X
try {
  const box = await page.evaluate(() => {
    const el = [...document.querySelectorAll('div,span,section')].find((e) => {
      const t = (e.textContent || '');
      const r = e.getBoundingClientRect();
      return t.includes('Trial user') && r.width > 150 && r.width < 460 && r.height > 40 && r.height < 160;
    });
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width) };
  });
  if (box) {
    await page.mouse.click(box.x + box.w - 16, box.y + 16); // 右上角 X
    await page.waitForTimeout(800);
    console.log('[exo] 关闭 Trial 提示 @', JSON.stringify(box));
  } else { console.log('[exo] 未定位到 Trial 弹窗'); }
} catch (e) { console.log('[exo] 关提示失败:', e.message); }

await page.waitForTimeout(2500); // 等数据加载完(OHLC)
const probe = await page.evaluate(() => ({ title: document.title })).catch(() => ({}));
console.log('[exo] title:', probe.title);

const file = path.join(OUT_DIR, 'exocharts.png');
await page.screenshot({ path: file, fullPage: false });
console.log(`[exo] 已保存 ${file}`);

// 有效性机械门:顶栏须 Bybit BTCUSD + Bid-Ask Profile,且非"24h延迟"(免费/掉登录态)
const chk = await page.evaluate(() => {
  const top = document.querySelector('#exo-center')?.textContent || '';
  const body = document.body.innerText || '';
  return { top, delayed: /delayed by 24 hours/i.test(body) };
}).catch(() => ({ top: '', delayed: true }));
const valid = /BTCUSD/.test(chk.top) && /Bid-Ask Profile/.test(chk.top) && !chk.delayed;
if (!valid) {
  console.log(`[exo] VALIDITY: FAIL - 顶栏="${chk.top.slice(0,60)}" delayed=${chk.delayed}(需 Bybit BTCUSD/Bid-Ask 且非24h延迟·可能掉登录)`);
  await ctx.close(); process.exit(2);
}
console.log('[exo] VALIDITY: OK');
await ctx.close();
process.exit(0);
