// Exocharts 足迹自动截图(Playwright/Chrome)。
// 严格基准: Bybit BTCUSD / D / Tick120 / Bid-Ask Profile / Imbalance /
// Candle None / FPBS / vWap。每个控件最多一次局部纠正，不做整轮重试。

import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';

import { chromium } from 'playwright';

import {
  EXOCHARTS_DEFECT_CODES,
  ExochartsUiError,
  asExochartsUiError,
  configureExocharts,
  defectForUiState,
  ensureLiveConnection,
  readExochartsUiState,
  writeCaptureResult,
  writeSanitizedDiagnostic,
} from './exocharts_ui_state.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PROFILE_DIR = path.join(os.homedir(), '.tv_chrome_profile');
const URL = 'https://exocharts.com/web/';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function requireRepoPath(value, fallback) {
  const resolved = path.resolve(value || fallback);
  const relative = path.relative(REPO_ROOT, resolved);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.unexpected, 'capture');
  }
  return resolved;
}

const date = today();
const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', date);
const invocationId = crypto.randomUUID();
const diagnosticDir = requireRepoPath(
  process.env.EXO_CAPTURE_DIAGNOSTIC_DIR,
  path.join(
    REPO_ROOT,
    'runtime_state',
    date,
    'capture_diagnostics',
    'exocharts',
    invocationId,
  ),
);
const resultPath = requireRepoPath(
  process.env.EXO_CAPTURE_RESULT_PATH,
  path.join(diagnosticDir, 'exocharts_result.json'),
);

async function dismissTrialNotice(page) {
  const labels = page.getByText(/Trial user/i);
  const visible = [];
  for (let index = 0; index < await labels.count(); index += 1) {
    const candidate = labels.nth(index);
    if (await candidate.isVisible().catch(() => false)) visible.push(candidate);
  }
  if (!visible.length) return false;

  let scope = visible[0];
  for (let depth = 0; depth < 5; depth += 1) {
    scope = scope.locator('xpath=..');
    const controls = scope.locator(
      '[aria-label="close" i], button, [role="button"], .close',
    );
    const closers = [];
    for (let index = 0; index < await controls.count(); index += 1) {
      const candidate = controls.nth(index);
      if (!(await candidate.isVisible().catch(() => false))) continue;
      const label = String(
        await candidate.getAttribute('aria-label')
        || await candidate.innerText().catch(() => ''),
      ).replace(/\s+/g, ' ').trim().toLowerCase();
      if (['close', 'x', '×'].includes(label)) closers.push(candidate);
    }
    if (closers.length === 1) {
      await closers[0].click({ timeout: 5000 }).catch(() => {});
      return true;
    }
    if (closers.length > 1) return false;
  }
  return false;
}

async function latestChartHoverPoint(page) {
  return page.evaluate(() => {
    const canvases = [...document.querySelectorAll('canvas')]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
      })
      .filter((rect) => rect.width > 800 && rect.height > 400)
      .sort((left, right) => (
        (right.width * right.height) - (left.width * left.height)
      ));
    if (!canvases.length) return null;
    const chart = canvases[0];
    return {
      x: Math.round(chart.x + (chart.width * 0.92)),
      y: Math.round(chart.y + (chart.height * 0.45)),
    };
  });
}

async function waitForChartCanvas(page, timeoutMs = 20000) {
  await page.waitForFunction(() => [...document.querySelectorAll('canvas')].some((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 800 && rect.height > 400;
  }), null, { timeout: timeoutMs, polling: 125 });
}

function writeResultSafely(status, defectCode = null, diagnosticAvailable = false) {
  if (fs.existsSync(resultPath)) return;
  writeCaptureResult(resultPath, { status, defectCode, diagnosticAvailable });
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const actionCounts = {};
  let context = null;
  let page = null;
  let failure = null;
  let diagnosticAvailable = false;

  try {
    try {
      context = await chromium.launchPersistentContext(PROFILE_DIR, {
        channel: 'chrome',
        headless: process.env.HEADLESS === '1',
        viewport: { width: 2560, height: 1440 },
        screen: { width: 2560, height: 1440 },
        args: ['--window-position=0,0', '--window-size=2576,1500'],
      });
    } catch {
      throw new ExochartsUiError(
        EXOCHARTS_DEFECT_CODES.browser,
        'capture',
      );
    }
    page = context.pages()[0] || (await context.newPage());
    console.log(`[exo] 打开: ${URL}`);
    try {
      await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    } catch {
      throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.navigation, 'capture');
    }

    await ensureLiveConnection(page, { actionCounts });
    await configureExocharts(page, { actionCounts });
    await dismissTrialNotice(page);
    try {
      await waitForChartCanvas(page);
    } catch {
      throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.uiNotReady, 'capture');
    }

    const hoverPoint = await latestChartHoverPoint(page);
    if (!hoverPoint) {
      throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.uiNotReady, 'capture');
    }
    await page.mouse.move(hoverPoint.x, hoverPoint.y);
    await page.evaluate(() => new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    }));

    const state = await readExochartsUiState(page);
    const stateDefect = defectForUiState(state);
    if (stateDefect) throw new ExochartsUiError(stateDefect, 'capture');

    const screenshotPath = path.join(OUT_DIR, 'exocharts.png');
    try {
      await page.screenshot({ path: screenshotPath, fullPage: false });
    } catch {
      throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.screenshot, 'capture');
    }
    writeResultSafely('passed');
    console.log('[exo] CONFIGURATION: OK');
    console.log(`[exo] 已保存 ${screenshotPath}`);
    console.log('[exo] VALIDITY: OK');
    return 0;
  } catch (error) {
    failure = asExochartsUiError(error);
    if (page) {
      diagnosticAvailable = await writeSanitizedDiagnostic(page, {
        directory: diagnosticDir,
        error: failure,
        actionCounts,
      }).then(() => true).catch(() => false);
    }
    writeResultSafely('failed', failure.code, diagnosticAvailable);
    console.log(`[exo] FAILURE_CODE=${failure.code}`);
    console.log('[exo] VALIDITY: FAIL');
    return 2;
  } finally {
    await context?.close().catch(() => {});
  }
}

process.exitCode = await main();
