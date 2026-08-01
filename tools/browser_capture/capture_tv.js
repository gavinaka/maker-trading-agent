// TradingView 四档自动截图(走独立 Chromium,绕过 Claude-in-Chrome 扩展黑名单)。
// 复用 login_tv.js 建立的持久化登录目录 —— 因此能带出你账户里的手绘线/布局。
//
// 生产用法:只允许由 capture_all.js / capture_delta.js 启动；父采集器必须
// 通过环境变量传入本轮 capture_run_id + nonce。直接运行缺少该身份时会硬停，
// 防止生成无法与当前不可变快照绑定的 sidecar。
//
// 输出(每周期 2 张): data_sources/inbox/<YYYY-MM-DD>/
//   tradingview_btc_<tf>.png      ① 结构图(趋势/道氏 HH-HL/SMA20·原固定 zoom·不变)
//   tradingview_btc_<tf>_liq.png  ② 用户手绘成交量分布/流动性区域特写(文件名为兼容合同保留)

import { chromium } from 'playwright';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import {
  hidePlatformProfileOnce,
  isolatePreviousProfileState,
  validateProfileCaptureIdentity,
  writeProfileStateAtomic,
} from './tradingview_profile_state.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const scoringPolicy = JSON.parse(
  fs.readFileSync(path.join(REPO_ROOT, 'scoring', 'scoring_contract.json'), 'utf8'),
);
const profilePolicy = scoringPolicy.tradingview_profile_policy || {};
if (
  profilePolicy.source_mode !== 'user_drawn_manual_only'
  || profilePolicy.platform_indicator_policy !== 'hide_and_never_use'
  || profilePolicy.automated_numeric_values_allowed !== false
) {
  throw new Error('TradingView profile policy is not the certified user_drawn_manual_only mode');
}
const PROFILE_STATE_FILENAME = profilePolicy.state_sidecar_filename;
const PROFILE_STATE_SCHEMA = profilePolicy.state_sidecar_schema_version;
const PROFILE_CAPTURE_RUN_ID = String(process.env.TRADINGVIEW_CAPTURE_RUN_ID || '').trim();
const PROFILE_CAPTURE_NONCE = String(process.env.TRADINGVIEW_CAPTURE_NONCE || '').trim();
validateProfileCaptureIdentity(PROFILE_CAPTURE_RUN_ID, PROFILE_CAPTURE_NONCE);
// 独立(非默认)Chrome 配置目录:
//  - 非默认目录 → Chrome 允许 Playwright 开调试通道控制(默认目录被 Chrome136+ 禁止)
//  - 在此目录里用普通 Chrome 登录一次(见 login_chrome.cmd 生成的启动方式)→ Google 登录不被拦
//  - 就地登录(非复制)→ cookie 能正常解密(避开 App-Bound 加密)
const PROFILE_DIR = path.join(os.homedir(), '.tv_chrome_profile');

const CHART_URL = process.argv[2] || 'https://cn.tradingview.com/chart/TW0SPqia/';

// TradingView 周期快捷输入:键入代码后回车即切换。1D=日线 / 240=4H / 60=1H / 15=15m
// zoom      = Alt+R 重置后贴右侧滚轮放大的步数→①结构图(收窄到:1D≈2月/4H≈15天/1H≈7天/15m≈1天内)。
// zoomExtra = 结构图之后再追加放大的步数→②用户手绘成交量分布/流动性区域特写。
//   平台内置 VRVP 必须隐藏且永不取值；只有用户手绘区域可读时才允许转录区间。
//   若平台指标仍可见/未知或手绘区域不可读，截图仍保留四周期结构，但后续 profile 维度必须标 insufficient。
const TIMEFRAMES = [
  { tf: '1d', key: '1D', zoom: 17, zoomExtra: 8 },   // 宽·覆盖完整日线价值区(全局 HVN/LVN)
  { tf: '4h', key: '240', zoom: 15, zoomExtra: 7 },  // 宽·覆盖 4H 价值区
  { tf: '1h', key: '60', zoom: 9, zoomExtra: 6 },    // ~1周·结构细化
  { tf: '15m', key: '15', zoom: 15, zoomExtra: 7 },  // 紧凑·仅供日内结构与用户手绘区域复核
];

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', today());
fs.mkdirSync(OUT_DIR, { recursive: true });
const profileStatePath = path.join(OUT_DIR, PROFILE_STATE_FILENAME);
let sidecarTargetIsolated = false;
try {
  isolatePreviousProfileState(profileStatePath);
  sidecarTargetIsolated = true;
} catch {
  console.log(
    '[tv] PROFILE_STATE_SIDECAR: ISOLATION_FAILED - '
    + '旧sidecar不得复用；四周期采集继续，下游必须按 unknown + insufficient 降级',
  );
}

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

async function setTimeframe(key, timeframe) {
  await page.keyboard.press('Escape');            // 取消任何选中的画线工具
  await page.mouse.click(1280, 700);              // 点图表区聚焦(默认十字线,不会画线)
  await page.waitForTimeout(300);
  await page.keyboard.type(key, { delay: 60 });   // 键入周期代码
  await page.keyboard.press('Enter');
  await page.waitForTimeout(3500);                // 等重绘
  await page.keyboard.press('Alt+r');             // 重置图表视图(消除继承的过密缩放)
  await page.waitForTimeout(2500);
  const expectedLabels = {
    '1d': ['1天'],
    '4h': ['4小时'],
    '1h': ['1小时'],
    '15m': ['15分', '15分钟'],
  }[timeframe];
  let confirmed = false;
  let confirmedLabel = '';
  for (const expectedLabel of expectedLabels) {
    const candidates = page.getByText(expectedLabel, { exact: true });
    for (let index = 0; index < await candidates.count(); index += 1) {
      const candidate = candidates.nth(index);
      const box = await candidate.boundingBox().catch(() => null);
      if (box && box.y < 100 && await candidate.isVisible().catch(() => false)) {
        confirmed = true;
        confirmedLabel = expectedLabel;
        break;
      }
    }
    if (confirmed) break;
  }
  if (!confirmed) {
    throw new Error(`TradingView toolbar did not confirm timeframe ${timeframe}`);
  }
  console.log(`[tv] 周期机械确认: ${confirmedLabel}`);
}

// 贴右侧滚轮放大,收窄可视区间(保留最新K线,裁掉左侧旧K线)
async function zoomIn(steps) {
  await page.mouse.move(2100, 700);               // 光标贴右侧(缩放以此为锚)
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, -240); await page.waitForTimeout(110); }
  await page.waitForTimeout(1200);
  console.log(`[tv]   滚轮放大 ${steps} 步`);
}

const saved = [];
const profileStates = [];
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
  await setTimeframe(key, tf);
  const profileState = await hidePlatformProfileOnce(page);
  profileStates.push({ timeframe: tf, ...profileState });
  console.log(
    `[tv] 平台VRVP状态: ${profileState.initial} -> ${profileState.final}`
    + ` correction=${profileState.correction_attempted}`
    + ` basis=${profileState.certification_basis}`,
  );
  if (['visible', 'unknown'].includes(profileState.final)) {
    console.log('[tv] PROFILE_DIMENSION: INSUFFICIENT - 平台指标未能认证隐藏；四周期结构截图继续保留');
  }
  if (zoom) await zoomIn(zoom);
  await shot(`tradingview_btc_${tf}.png`);          // ① 结构图(趋势/道氏/SMA20·zoom 不变)
  if (zoomExtra) {                                   // ② 用户手绘成交量分布/流动性区域特写
    await zoomIn(zoomExtra);
    await page.waitForTimeout(1500);
    await shot(`tradingview_btc_${tf}_liq.png`);
  }
}

function aggregatePlatformState(states) {
  const finals = states.map((item) => item.final);
  if (finals.includes('visible')) return 'visible';
  if (finals.includes('unknown')) return 'unknown';
  if (finals.every((state) => state === 'absent')) return 'absent';
  return 'hidden';
}

const profileStateSidecar = {
  schema_version: PROFILE_STATE_SCHEMA,
  capture_run_id: PROFILE_CAPTURE_RUN_ID,
  capture_nonce: PROFILE_CAPTURE_NONCE,
  source_mode: profilePolicy.source_mode,
  platform_indicator_policy: profilePolicy.platform_indicator_policy,
  aggregate_state: aggregatePlatformState(profileStates),
  timeframes: Object.fromEntries(profileStates.map((item) => [
    item.timeframe,
    {
      initial_state: item.initial,
      final_state: item.final,
      correction_attempted: item.correction_attempted,
      certification_basis: item.certification_basis,
    },
  ])),
};
try {
  if (!sidecarTargetIsolated) {
    throw new Error('profile sidecar target was not isolated');
  }
  writeProfileStateAtomic(
    profileStatePath,
    profileStateSidecar,
    PROFILE_CAPTURE_NONCE,
  );
  console.log(`[tv] 已保存去文本化平台状态 sidecar: ${profileStatePath}`);
} catch {
  console.log(
    '[tv] PROFILE_STATE_SIDECAR: UNAVAILABLE - '
    + '不阻断四周期采集；下游必须按 unknown + insufficient 降级',
  );
}

console.log('\n[tv] 完成,共 ' + saved.length + ' 张:');
saved.forEach((f) => console.log('  ' + f));
console.log('[tv] PROFILE_POLICY: user_drawn_manual_only / platform hide_and_never_use');
console.log('[tv] PROFILE_STATES: ' + JSON.stringify(profileStates));

await ctx.close();
process.exit(0);
