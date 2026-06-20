// Coinglass 盘口四面板自动截图(Playwright/Chrome,公开无需登录)。
// 对齐用户基准:价格 / 累积CVD / 资金费率 / 持仓OI 四面板,1H。
// 默认「精选指标」预设含 6 面板,需删掉 3 个:成交量(Volume) / 聚合现货CVD / 订单簿深度差值。
//
// 用法: node capture_coinglass.js
// 输出: data_sources/inbox/<YYYY-MM-DD>/coinglass.png

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROFILE_DIR = path.join(os.homedir(), '.coinglass_chrome_profile');
const URL = 'https://www.coinglass.com/tv/zh/Bybit_BTCUSDT';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });

// 视口开宽:右侧固定行情表约占 ~420px,开到 2980×1440 让图表本体撑到 ~2560,裁掉行情表后≈2560×1440
const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
  channel: 'chrome', headless: process.env.HEADLESS === '1',
  viewport: { width: 2964, height: 1440 }, // 行情表约占 404px,2964-404≈2560(裁剪后图表精确 2560 宽)
  screen: { width: 2964, height: 1440 },
  args: ['--window-position=0,0', '--window-size=2980,1500'],
});
const page = ctx.pages()[0] || (await ctx.newPage());

console.log(`[coinglass] 打开: ${URL}`);
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(14000); // 六面板全部渲染较重(含订单簿深度差值)

// 确保 1H 周期
try { await page.getByText('1小时', { exact: true }).first().click({ timeout: 5000 }); await page.waitForTimeout(3000); } catch {}

// TV 图表在 blob: iframe 内,删除按钮 = legend-delete-action
const chartFrame = page.frames().find(f => f.url().startsWith('blob:'));
if (!chartFrame) { console.log('[coinglass] 未找到图表 frame'); }

// 删除按钮 display:none + canvas 拦截 → 在 frame 内派发完整鼠标事件序列(TV 监听 pointer/mouse,非 click)
async function removeByTitle(keyword) {
  const res = await chartFrame.evaluate((kw) => {
    const items = [...document.querySelectorAll('[data-name="legend-source-item"]')];
    const item = items.find((i) => (i.textContent || '').includes(kw));
    if (!item) return 'notfound';
    item.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    item.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    const del = item.querySelector('[data-name="legend-delete-action"]');
    if (!del) return 'nobtn';
    const opts = { bubbles: true, cancelable: true, view: window };
    for (const type of ['pointerover', 'pointerenter', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      try { del.dispatchEvent(type.startsWith('pointer') ? new PointerEvent(type, opts) : new MouseEvent(type, opts)); } catch {}
    }
    return 'dispatched';
  }, keyword).catch((e) => 'err:' + e.message);
  await page.waitForTimeout(1200);
  console.log(`[coinglass] ${keyword} -> ${res}`);
}

// 调试:打印所有图例真实文本
const legendTexts = await chartFrame.evaluate(() =>
  [...document.querySelectorAll('[data-name="legend-source-item"]')].map((i) => (i.textContent || '').trim().slice(0, 60))
).catch(() => []);
console.log('[coinglass] 当前图例:', JSON.stringify(legendTexts));

// 唯一关键词定位待删面板(保留"累积成交量增量"/"资金费率"/"持仓");两遍确保删净
for (let pass = 0; pass < 2; pass++) {
  await removeByTitle('(Volume)');          // 成交量 SMA(CVD标题不含"(Volume)")
  await removeByTitle('聚合现货累积成交量增量'); // 现货 CVD
  await removeByTitle('深度差值');           // 聚合合约订单薄深度差值(注:CG 把"簿"误写成"薄")
}

// 清除删面板时派发 mouseover 残留的"悬停态"(否则面板右上角会显示操作图标)
await chartFrame.evaluate(() => {
  document.querySelectorAll('[data-name="legend-source-item"], [data-name="pane"]').forEach((el) => {
    el.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
  });
});
await page.mouse.move(950, 600);
await page.mouse.move(950, 8); // 移到顶栏,离开所有面板
await page.waitForTimeout(1500);

// 按图表 iframe 右边界裁掉右侧行情表,得到全宽 4 面板图(含顶栏)
const fe = await chartFrame.frameElement();
const box = await fe.boundingBox();
const clip = box
  ? { x: 0, y: 0, width: Math.ceil(box.x + box.width), height: Math.ceil(box.y + box.height) }
  : undefined;
console.log('[coinglass] 图表区:', JSON.stringify(box), '裁剪:', JSON.stringify(clip));

const file = path.join(OUT_DIR, 'coinglass.png');
await page.screenshot({ path: file, clip });
console.log(`[coinglass] 已保存 ${file}`);

// 有效性机械门:保留项(CVD/资金费率/持仓)在、待删项(Volume/聚合现货/深度差值)无。
// (价格主图是 legend-series-item 不计;3 个指标面板是 legend-source-item)
const legends = await chartFrame.evaluate(() =>
  [...document.querySelectorAll('[data-name="legend-source-item"]')].map((e) => e.textContent || '')
).catch(() => []);
const blob = legends.join('｜');
const keep = /累积成交量增量/.test(blob) && /资金费率/.test(blob) && /持仓/.test(blob);
const gone = !/\(Volume\)/.test(blob) && !/聚合现货/.test(blob) && !/深度差值/.test(blob);
if (!(keep && gone) || legends.length !== 3) {
  console.log(`[coinglass] VALIDITY: FAIL - 面板=${legends.length}[${blob.slice(0,80)}](应剩 CVD/资金费率/持仓 三项)`);
  await ctx.close(); process.exit(2);
}
console.log('[coinglass] VALIDITY: OK');
await ctx.close();
process.exit(0);
