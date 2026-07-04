// Coinglass 清算热力图自动截图(Playwright/Chrome)——③Coinglass 辅助源·辅助印证流动性猎杀概率。
// 周期规则(用户口径): 周末(六/日) 流动性极低→看 3天; 周一至五→48H + 24H。
// Binance BTC/USDT 永续 · 流动性阈值固定 0.85 · 黄=最强磁吸(上方带=空头流动性/下方带=多头流动性)。
//
// 用法: node capture_liqheatmap.js
// 输出: data_sources/inbox/<YYYY-MM-DD>/liqheatmap_{3d|48h|24h}.png
// 退出码: 0=全部目标周期成功; 2=采到但无效/部分失败(辅助源·capture_all 只 WARN 不硬停)
//
// 🟥 前置: 该图属 Coinglass Prime,需在 ~/.tv_chrome_profile 登录 Coinglass 一次(2026-06-21 已登)。
// 🟥 选择器(周期下拉/symbol/截图区)按页面 DOM 推断,首次须实跑核对——失败会打印诊断,据此微调。

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
// 用户口径"都用那个独立 Chrome"=复用 TV/Exo 的登录目录(Coinglass Prime 也在此登录)
const PROFILE_DIR = path.join(os.homedir(), '.tv_chrome_profile');
const URL = 'https://www.coinglass.com/zh/pro/futures/LiquidationHeatMap?coin=BTC';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });

// 周期规则: 周末看3天, 周中看48H+24H (与用户手动抓取一致)
const dow = new Date().getDay(); // 0=周日 6=周六
const WEEKEND = dow === 0 || dow === 6;
const TARGETS = WEEKEND
  ? [{ label: '3天', tag: '3d' }]
  : [{ label: '48小时', tag: '48h' }, { label: '24小时', tag: '24h' }];
console.log(`[liqheatmap] ${today()} dow=${dow} ${WEEKEND ? '周末→3天' : '周中→48H+24H'}; 目标:`, TARGETS.map(t => t.label).join('/'));

// 视口对齐用户截图格式(约 1500×1000 的热力图面板)
const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
  channel: 'chrome', headless: process.env.HEADLESS === '1',
  viewport: { width: 1600, height: 1040 },
  screen: { width: 1600, height: 1040 },
  args: ['--window-position=0,0', '--window-size=1620,1100'],
});
const page = ctx.pages()[0] || (await ctx.newPage());

console.log(`[liqheatmap] 打开: ${URL}`);
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(12000); // echarts 热力图渲染较重

// 关闭可能弹出的广告/引导弹窗(best-effort)
for (const kw of ['同意', '接受', '我知道了', 'Got it', 'Accept']) {
  try { await page.getByText(kw, { exact: false }).first().click({ timeout: 1500 }); await page.waitForTimeout(500); } catch {}
}

// 设周期: 该周期控件是顶部右侧的下拉(显示当前如"3天")。多策略 best-effort。
async function setPeriod(label) {
  // 策略1: 原生 <select>
  try {
    const sel = page.locator('select').first();
    if (await sel.count()) { await sel.selectOption({ label }).catch(() => {}); await page.waitForTimeout(4000); }
  } catch {}
  // 策略2: 点开下拉再点选项文本
  try {
    // 当前周期标签(任一已知周期值)作为下拉触发点
    const trigger = page.getByText(/^(3天|48小时|24小时|12小时|7天|1天|8小时|4小时)$/).first();
    await trigger.click({ timeout: 4000 });
    await page.waitForTimeout(800);
    await page.getByText(label, { exact: true }).last().click({ timeout: 4000 });
    await page.waitForTimeout(4500);
    return true;
  } catch (e) {
    console.log(`[liqheatmap] setPeriod(${label}) 下拉点选失败: ${e.message.slice(0, 60)}`);
    return false;
  }
}

// 截图区: 优先抓最大的 canvas(echarts 热力图本体);否则退化为面板区域裁剪
async function shoot(file) {
  const VPW = 1600;
  let clip;
  try {
    const boxes = await page.$$eval('canvas', (cs) =>
      cs.map((c) => { const r = c.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })
    );
    const big = boxes.filter(b => b.w > 600 && b.h > 400).sort((a, b) => b.w * b.h - a.w * a.h)[0];
    if (big) {
      // 🟥 canvas 仅绘图区·价格轴/时间轴/强度色阶在 canvas 外→须扩边纳入(否则读不到磁吸带精确价位·违 §九D 读位精度)
      // 左 -40(强度色阶)·上 -8(标题)·右延到视口边(价格轴)·下 +56(时间轴)
      const x0 = Math.max(0, Math.floor(big.x) - 40);
      const y0 = Math.max(0, Math.floor(big.y) - 8);
      clip = { x: x0, y: y0, width: Math.min(VPW - x0, Math.floor(big.w) + 320), height: Math.floor(big.h) + 56 };
    }
  } catch {}
  if (!clip) clip = { x: 0, y: 110, width: VPW, height: 920 }; // 退化裁剪(去顶栏)
  await page.screenshot({ path: file, clip });
  return clip;
}

// 有效性: 页面含"清算"字样(非登录墙) + 文件非空
async function valid(file) {
  const hasText = await page.locator('text=清算').count().catch(() => 0);
  let sz = 0; try { sz = fs.statSync(file).size; } catch {}
  return hasText > 0 && sz > 20000;
}

let okCount = 0;
for (const t of TARGETS) {
  await setPeriod(t.label);
  const file = path.join(OUT_DIR, `liqheatmap_${t.tag}.png`);
  const clip = await shoot(file);
  const ok = await valid(file);
  console.log(`[liqheatmap] ${t.label} → ${path.basename(file)}  clip=${JSON.stringify(clip)}  ${ok ? 'OK' : 'INVALID(登录墙/空图)'}`);
  if (ok) okCount++;
}

await ctx.close();
if (okCount === TARGETS.length) { console.log('[liqheatmap] VALIDITY: OK'); process.exit(0); }
console.log(`[liqheatmap] VALIDITY: PARTIAL/FAIL (${okCount}/${TARGETS.length}) —— 辅助源·不硬停;若登录墙请在 ~/.tv_chrome_profile 登录 Coinglass Prime 后重跑`);
process.exit(2);
