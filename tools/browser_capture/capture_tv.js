// TradingView 四档自动截图(走独立 Chromium,绕过 Claude-in-Chrome 扩展黑名单)。
// 复用 login_tv.js 建立的持久化登录目录 —— 因此能带出你账户里的手绘线/布局。
//
// 用法:
//   npm run tv                      使用默认图表 URL
//   node capture_tv.js <chartUrl>   指定图表 URL
//   HEADLESS=1 npm run tv           无头模式(登录稳定后可用,默认有头更不易被风控)
//
// 输出(每周期 2 张): data_sources/inbox/<YYYY-MM-DD>/
//   tradingview_btc_<tf>.png      ① 结构图(趋势/道氏 HH-HL/SMA20·原固定 zoom·不变)
//   tradingview_btc_<tf>_liq.png  ② 流动性高低点+VRVP 特写(再放大·读各周期摆动高/低=候选猎杀位+POC/VAH/VAL·2026-06-21 加)

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
// 独立(非默认)Chrome 配置目录:
//  - 非默认目录 → Chrome 允许 Playwright 开调试通道控制(默认目录被 Chrome136+ 禁止)
//  - 在此目录里用普通 Chrome 登录一次(见 login_chrome.cmd 生成的启动方式)→ Google 登录不被拦
//  - 就地登录(非复制)→ cookie 能正常解密(避开 App-Bound 加密)
const PROFILE_DIR = path.join(os.homedir(), '.tv_chrome_profile');

const CHART_URL = process.argv[2] || 'https://cn.tradingview.com/chart/TW0SPqia/';

// TradingView 周期快捷输入:键入代码后回车即切换。1D=日线 / 240=4H / 60=1H / 15=15m
// zoom      = Alt+R 重置后贴右侧滚轮放大的步数→①结构图(收窄到:1D≈2月/4H≈15天/1H≈7天/15m≈1天内)。
// zoomExtra = 结构图之后再追加放大的步数→②流动性特写(把最近摆动高/低点+VRVP 放大到精确可读·读猎杀位)。
//   ✅ 已实跑核对锁定(2026-06-21 晚)：8/7/6/7 产出的 _liq 特写【裁剪右侧 VRVP 直方图+价格轴区后】VRVP/POC/VAH/VAL
//      节点价精确可读——15m 紧凑(±3000 点·最佳)、1h ~1周、1d/4h 宽但覆盖完整价值区(符合高周期看全局 HVN/LVN 的用途)。
//   🟥 勿盲目加大(尤其 15m 已紧凑·再大=只剩几根 K 致 POC 失真)；勿减小(高周期需看全价值区)。VRVP 按可见区间实时重算。
//   🟥 读法纪律(SKILL §1⑤)：_liq 必【裁剪放大】读(像读 SMA 轴标)、禁拿 Read 直读缩略图当读过(否则抓了等于没用)。
const TIMEFRAMES = [
  { tf: '1d', key: '1D', zoom: 17, zoomExtra: 8 },   // 宽·覆盖完整日线价值区(全局 HVN/LVN)
  { tf: '4h', key: '240', zoom: 15, zoomExtra: 7 },  // 宽·覆盖 4H 价值区
  { tf: '1h', key: '60', zoom: 9, zoomExtra: 6 },    // ~1周·结构细化
  { tf: '15m', key: '15', zoom: 15, zoomExtra: 7 },  // 紧凑(±3000点)·日内摆动高低+VRVP 精确(最佳)
];

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });

const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
  channel: 'chrome', // 用真实 Chrome 就地打开独立目录(能解密自家 cookie)
  headless: process.env.HEADLESS === '1',
  viewport: { width: 2560, height: 1440 }, // 输出统一 2560×1440(提升读数准确性)
  screen: { width: 2560, height: 1440 },
  args: ['--window-position=0,0', '--window-size=2576,1500'],
});

const page = ctx.pages()[0] || (await ctx.newPage());

console.log(`[tv] 打开图表: ${CHART_URL}`);
await page.goto(CHART_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(9000); // TV 图表渲染较重,留足时间

// 有效性机械门:必须是登录态图表,而非"需要登录/无法打开此图表布局"墙(掉登录→四档全废)
const wall = await page.evaluate(() =>
  /无法为您打开此图表布局|需要登录|need to log in|要查看它/i.test(document.body.innerText || '')
).catch(() => true);
if (wall) {
  console.log('[tv] VALIDITY: FAIL - 落在登录墙/图表布局打不开(TV 掉登录)→需重登 ~/.tv_chrome_profile');
  await ctx.close(); process.exit(2);
}
console.log('[tv] VALIDITY: OK(登录态正常)');

// 宽视口(2560)下 TV 会自动展开右侧自选表面板,基准里没有 → 折叠它(保留细图标条)
try {
  const wlVisible = await page.locator('[data-name="symbol-list-wrap"]').first().isVisible().catch(() => false);
  if (wlVisible) {
    await page.locator('[data-name="base"]').first().click({ timeout: 5000 });
    await page.waitForTimeout(1500);
    console.log('[tv] 已折叠右侧自选表面板');
  } else { console.log('[tv] 右侧面板未展开,跳过'); }
} catch (e) { console.log('[tv] 折叠面板失败:', e.message); }

async function setTimeframe(key) {
  await page.keyboard.press('Escape');            // 取消任何选中的画线工具
  await page.mouse.click(1280, 700);              // 点图表区聚焦(默认十字线,不会画线)
  await page.waitForTimeout(300);
  await page.keyboard.type(key, { delay: 60 });   // 键入周期代码
  await page.keyboard.press('Enter');
  await page.waitForTimeout(3500);                // 等重绘
  await page.keyboard.press('Alt+r');             // 重置图表视图(消除继承的过密缩放)
  await page.waitForTimeout(2500);
}

// VRVP 必须可见；布局若被用户手动隐藏，则自动点“显示”。
async function ensureVrvpVisible() {
  const result = await page.evaluate(() => {
    const titles = [...document.querySelectorAll('[data-qa-id="title-wrapper legend-source-title"]')];
    const title = titles.find((el) => (el.textContent || '').trim() === 'VRVP');
    const item = title?.closest('div[class*="noWrapWrapper"]') || title?.parentElement?.parentElement;
    const button = item?.querySelector('[data-qa-id="legend-show-hide-action"]');
    if (!button) return 'not-found';
    const label = button.getAttribute('aria-label') || button.getAttribute('title') || '';
    if (/显示|show/i.test(label)) {
      button.click();
      return 'shown';
    }
    return 'already-visible';
  }).catch((e) => `error:${e.message}`);
  await page.waitForTimeout(2500);
  console.log(`[tv] VRVP: ${result}`);
  return result;
}

// 贴右侧滚轮放大,收窄可视区间(保留最新K线,裁掉左侧旧K线)
async function zoomIn(steps) {
  await page.mouse.move(2100, 700);               // 光标贴右侧(缩放以此为锚)
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, -240); await page.waitForTimeout(110); }
  await page.waitForTimeout(1200);
  console.log(`[tv]   滚轮放大 ${steps} 步`);
}

const saved = [];
async function shot(name) {
  await page.keyboard.press('Escape');            // 截图前移走十字线焦点
  await page.mouse.move(1280, 8);                 // 移走十字线
  await page.waitForTimeout(500);
  const file = path.join(OUT_DIR, name);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`[tv] 已保存 ${file}`);
  saved.push(file);
}
for (const { tf, key, zoom, zoomExtra } of TIMEFRAMES) {
  console.log(`[tv] 切换周期 -> ${tf} (${key})`);
  await setTimeframe(key);
  await ensureVrvpVisible();
  if (zoom) await zoomIn(zoom);
  await shot(`tradingview_btc_${tf}.png`);          // ① 结构图(趋势/道氏/SMA20·zoom 不变)
  if (zoomExtra) {                                   // ② 流动性高低点+VRVP 特写(再放大·读猎杀位+POC/VAH/VAL)
    await zoomIn(zoomExtra);
    await page.waitForTimeout(5000);                  // VRVP 按可见区间重算较慢，未稳定前截图会只剩 K 线
    await shot(`tradingview_btc_${tf}_liq.png`);
  }
}

console.log('\n[tv] 完成,共 ' + saved.length + ' 张:');
saved.forEach((f) => console.log('  ' + f));

await ctx.close();
process.exit(0);
