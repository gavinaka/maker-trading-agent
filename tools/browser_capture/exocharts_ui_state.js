import fs from 'fs';
import path from 'path';

export const EXOCHARTS_EXPECTED_CONFIG = Object.freeze({
  symbol: 'Bybit: BTCUSD',
  timeframe: 'D',
  tickMultiplier: '120',
  clusterType: 'Bid-Ask Profile',
  textType: 'Imbalance',
  candleType: 'None',
  fpbs: 'active',
  vwap: 'active',
});

export const EXOCHARTS_DEFECT_CODES = Object.freeze({
  browser: 'capture.exocharts.browser_unavailable',
  navigation: 'capture.exocharts.navigation_failed',
  uiNotReady: 'capture.exocharts.ui_not_ready',
  liveActionMissing: 'capture.exocharts.live_takeover_action_missing',
  liveTakeover: 'capture.exocharts.live_takeover_failed',
  symbol: 'capture.exocharts.symbol_unconfirmed',
  timeframe: 'capture.exocharts.timeframe_unconfirmed',
  tick: 'capture.exocharts.tick_unconfirmed',
  cluster: 'capture.exocharts.cluster_unconfirmed',
  imbalance: 'capture.exocharts.imbalance_unconfirmed',
  candle: 'capture.exocharts.candle_none_unconfirmed',
  fpbs: 'capture.exocharts.fpbs_unconfirmed',
  vwap: 'capture.exocharts.vwap_unconfirmed',
  delayed: 'capture.exocharts.delayed_feed',
  screenshot: 'capture.exocharts.screenshot_failed',
  unexpected: 'capture.exocharts.unclassified',
});

const SAFE_CODE = /^[A-Za-z0-9_.-]{1,120}$/;
const LIVE_CONNECTION_PATTERN = /plan does not allow more live connections/i;
const TAKEOVER_ACTION_TEXTS = new Set([
  'click here',
  'continue',
  'continue here',
  'here',
  'reconnect',
  'refresh',
  'refresh page',
  'reload',
  'reload page',
  'switch here',
  'take over',
  'take over connection',
  'use this connection',
  'use this session',
]);
const CONTROL_NAMES = new Set([
  'live_takeover',
  'symbol',
  'timeframe',
  'tick_multiplier',
  'cluster_type',
  'text_type',
  'candle_type',
  'fpbs',
  'vwap',
  'capture',
]);

export class ExochartsUiError extends Error {
  constructor(code, control = 'capture') {
    const safeCode = SAFE_CODE.test(String(code))
      ? String(code)
      : EXOCHARTS_DEFECT_CODES.unexpected;
    super(safeCode);
    this.name = 'ExochartsUiError';
    this.code = safeCode;
    this.control = CONTROL_NAMES.has(control) ? control : 'capture';
  }
}

export function asExochartsUiError(error, fallbackCode = EXOCHARTS_DEFECT_CODES.unexpected) {
  if (error instanceof ExochartsUiError) return error;
  return new ExochartsUiError(fallbackCode, 'capture');
}

function normalizeText(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function safeCountMap(actionCounts = {}) {
  return Object.fromEntries(
    [...CONTROL_NAMES]
      .filter((name) => Number.isInteger(actionCounts[name]))
      .map((name) => [name, Math.max(0, Math.min(2, actionCounts[name]))]),
  );
}

function correctionCounts(actionCounts = {}) {
  return Object.fromEntries(
    Object.entries(safeCountMap(actionCounts))
      .map(([name, count]) => [name, Math.max(0, count - 1)]),
  );
}

async function visibleEntries(locator) {
  const entries = [];
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = locator.nth(index);
    if (await candidate.isVisible().catch(() => false)) {
      entries.push({
        locator: candidate,
        text: normalizeText(await candidate.innerText().catch(() => '')),
      });
    }
  }
  return entries;
}

async function uniqueVisible(locator) {
  const entries = await visibleEntries(locator);
  return entries.length === 1 ? entries[0] : null;
}

async function uniqueVisibleExact(locator, expected) {
  const normalized = normalizeText(expected).toLowerCase();
  const entries = (await visibleEntries(locator))
    .filter((entry) => entry.text.toLowerCase() === normalized);
  return entries.length === 1 ? entries[0] : null;
}

async function waitUntil(predicate, timeoutMs, pollMs = 125) {
  const deadline = Date.now() + timeoutMs;
  do {
    if (await predicate().catch(() => false)) return true;
    if (Date.now() >= deadline) break;
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  } while (Date.now() <= deadline);
  return false;
}

async function liveConnectionBlocked(page) {
  const entries = await visibleEntries(page.getByText(LIVE_CONNECTION_PATTERN));
  return entries.length > 0;
}

async function controlsReady(page) {
  const periods = await visibleEntries(page.locator('#topPeriodSelector'));
  const chartType = await visibleEntries(page.locator('#topChartTypeSelector'));
  return periods.length === 2 && chartType.length === 1;
}

async function resolveTakeoverAction(page) {
  const candidates = await visibleEntries(page.locator('a, button, [role="button"]'));
  const nearBlocker = [];
  for (const entry of candidates) {
    const isNear = await entry.locator.evaluate((element) => {
      let current = element;
      for (let depth = 0; current && depth < 6; depth += 1) {
        if (/plan does not allow more live connections/i.test(current.textContent || '')) {
          return true;
        }
        current = current.parentElement;
      }
      return false;
    }).catch(() => false);
    if (isNear) nearBlocker.push(entry);
  }
  const allowedNearBlocker = nearBlocker.filter(
    (entry) => TAKEOVER_ACTION_TEXTS.has(entry.text.toLowerCase()),
  );
  if (allowedNearBlocker.length === 1) return allowedNearBlocker[0].locator;
  if (allowedNearBlocker.length > 1) return null;
  const nonemptyNearBlocker = nearBlocker.filter((entry) => entry.text.length > 0);
  if (nonemptyNearBlocker.length === 1) return nonemptyNearBlocker[0].locator;

  const allowed = candidates.filter(
    (entry) => TAKEOVER_ACTION_TEXTS.has(entry.text.toLowerCase()),
  );
  return allowed.length === 1 ? allowed[0].locator : null;
}

export async function ensureLiveConnection(page, {
  actionCounts = {},
  initialTimeoutMs = 30000,
  transitionTimeoutMs = 20000,
} = {}) {
  const settled = await waitUntil(
    async () => (await liveConnectionBlocked(page)) || (await controlsReady(page)),
    initialTimeoutMs,
  );
  if (!settled) {
    throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.uiNotReady, 'live_takeover');
  }
  if (!(await liveConnectionBlocked(page))) return { takeoverRequired: false };

  for (let action = 1; action <= 2; action += 1) {
    const takeover = await resolveTakeoverAction(page);
    if (!takeover) {
      const code = action === 1
        ? EXOCHARTS_DEFECT_CODES.liveActionMissing
        : EXOCHARTS_DEFECT_CODES.liveTakeover;
      throw new ExochartsUiError(code, 'live_takeover');
    }
    actionCounts.live_takeover = action;
    await takeover.click({ timeout: 10000 }).catch(() => {});
    const connected = await waitUntil(
      async () => !(await liveConnectionBlocked(page)) && (await controlsReady(page)),
      transitionTimeoutMs,
    );
    if (connected) {
      return { takeoverRequired: true, correctionUsed: action === 2 };
    }
  }
  throw new ExochartsUiError(EXOCHARTS_DEFECT_CODES.liveTakeover, 'live_takeover');
}

async function periodControls(page) {
  const entries = await visibleEntries(page.locator('#topPeriodSelector'));
  if (entries.length !== 2) return null;
  const symbol = entries.filter((entry) => /^[A-Za-z0-9_.-]+:\s*[A-Za-z0-9_.-]+$/.test(entry.text));
  if (symbol.length !== 1) return null;
  const timeframe = entries.filter((entry) => entry.locator !== symbol[0].locator);
  return timeframe.length === 1 ? { symbol: symbol[0], timeframe: timeframe[0] } : null;
}

function symbolMatches(value) {
  return /^Bybit:\s*BTCUSD$/i.test(normalizeText(value));
}

async function selectBybitBtcUsd(page, symbolControl) {
  await symbolControl.click({ timeout: 10000 });
  const menuReady = await waitUntil(
    async () => Boolean(await uniqueVisibleExact(page.getByText('Bybit:', { exact: true }), 'Bybit:')),
    5000,
  );
  if (!menuReady) return false;
  const bybit = await uniqueVisibleExact(page.getByText('Bybit:', { exact: true }), 'Bybit:');
  if (!bybit) return false;

  let scope = bybit.locator;
  for (let depth = 0; depth < 5; depth += 1) {
    scope = scope.locator('xpath=..');
    const option = await uniqueVisibleExact(scope.locator('.item, [role="option"]'), 'BTCUSD');
    if (option) {
      await option.locator.click({ timeout: 10000 });
      return true;
    }
  }
  return false;
}

async function ensureControl({
  control,
  code,
  verify,
  apply,
  actionCounts,
  verifyTimeoutMs = 6000,
}) {
  if (await verify().catch(() => false)) return;
  for (let action = 1; action <= 2; action += 1) {
    actionCounts[control] = action;
    await apply().catch(() => false);
    if (await waitUntil(verify, verifyTimeoutMs)) return;
  }
  throw new ExochartsUiError(code, control);
}

async function ensureSymbol(page, actionCounts) {
  await ensureControl({
    control: 'symbol',
    code: EXOCHARTS_DEFECT_CODES.symbol,
    actionCounts,
    verify: async () => {
      const controls = await periodControls(page);
      return Boolean(controls && symbolMatches(controls.symbol.text));
    },
    apply: async () => {
      const controls = await periodControls(page);
      return controls ? selectBybitBtcUsd(page, controls.symbol.locator) : false;
    },
  });
}

async function ensureMenuValue(page, {
  selector,
  expectedValue,
  optionLabel = expectedValue,
  control,
  code,
  actionCounts,
}) {
  const resolveControl = () => uniqueVisible(page.locator(selector));
  await ensureControl({
    control,
    code,
    actionCounts,
    verify: async () => {
      const current = await resolveControl();
      return Boolean(current && current.text === expectedValue);
    },
    apply: async () => {
      const current = await resolveControl();
      if (!current) return false;
      await current.locator.click({ timeout: 10000 });
      const optionReady = await waitUntil(
        async () => Boolean(await uniqueVisibleExact(
          page.locator('.item, [role="option"]'),
          optionLabel,
        )),
        4000,
      );
      if (!optionReady) return false;
      const option = await uniqueVisibleExact(page.locator('.item, [role="option"]'), optionLabel);
      if (!option) return false;
      await option.locator.click({ timeout: 10000 });
      return true;
    },
  });
}

async function ensureTimeframe(page, actionCounts) {
  await ensureControl({
    control: 'timeframe',
    code: EXOCHARTS_DEFECT_CODES.timeframe,
    actionCounts,
    verify: async () => {
      const controls = await periodControls(page);
      return Boolean(controls && controls.timeframe.text === EXOCHARTS_EXPECTED_CONFIG.timeframe);
    },
    apply: async () => {
      const controls = await periodControls(page);
      if (!controls) return false;
      await controls.timeframe.locator.click({ timeout: 10000 });
      const optionReady = await waitUntil(
        async () => Boolean(await uniqueVisibleExact(
          page.locator('.item, [role="option"]'),
          'Daily',
        )),
        4000,
      );
      if (!optionReady) return false;
      const option = await uniqueVisibleExact(page.locator('.item, [role="option"]'), 'Daily');
      if (!option) return false;
      await option.locator.click({ timeout: 10000 });
      return true;
    },
  });
}

async function ensureTickMultiplier(page, actionCounts) {
  const resolveControl = () => uniqueVisible(page.locator('input.topTickMultiplier'));
  await ensureControl({
    control: 'tick_multiplier',
    code: EXOCHARTS_DEFECT_CODES.tick,
    actionCounts,
    verify: async () => {
      const control = await resolveControl();
      return Boolean(
        control
        && normalizeText(await control.locator.inputValue().catch(() => ''))
          === EXOCHARTS_EXPECTED_CONFIG.tickMultiplier,
      );
    },
    apply: async () => {
      const control = await resolveControl();
      if (!control) return false;
      await control.locator.fill(EXOCHARTS_EXPECTED_CONFIG.tickMultiplier);
      await control.locator.press('Enter');
      await control.locator.blur().catch(() => {});
      return true;
    },
  });
}

async function toggleState(locator) {
  return locator.evaluate((element) => {
    const truthy = new Set(['true', 'active', 'on', 'selected', 'checked']);
    const falsy = new Set(['false', 'inactive', 'off', 'unselected', 'unchecked']);
    const attributes = [
      element.getAttribute('aria-pressed'),
      element.getAttribute('aria-selected'),
      element.getAttribute('aria-checked'),
      element.getAttribute('data-active'),
      element.getAttribute('data-selected'),
      element.getAttribute('data-state'),
    ].filter((value) => value !== null).map((value) => String(value).toLowerCase());
    if (attributes.some((value) => truthy.has(value))) return 'active';
    if (attributes.some((value) => falsy.has(value))) return 'inactive';

    const classTokens = [...element.classList].map((value) => value.toLowerCase());
    if (classTokens.some((value) => /^(active|selected|checked|is-active|is-selected)$/.test(value))) {
      return 'active';
    }
    if (classTokens.some((value) => /^(inactive|disabled|is-inactive|is-disabled)$/.test(value))) {
      return 'inactive';
    }

    const style = getComputedStyle(element);
    const match = style.color.match(/[\d.]+/g);
    if (!match || match.length < 3 || Number(style.opacity) < 0.5) return 'unknown';
    const [red, green, blue] = match.slice(0, 3).map(Number);
    const max = Math.max(red, green, blue);
    const min = Math.min(red, green, blue);
    const chroma = max - min;
    const perceived = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
    if ((chroma >= 60 && max >= 170 && perceived >= 120) || perceived >= 185) return 'active';
    if (chroma <= 35 && perceived <= 145) return 'inactive';
    return 'unknown';
  }).catch(() => 'unknown');
}

async function resolveToggle(page, label) {
  return uniqueVisibleExact(page.locator('.topColBtn, [role="button"]'), label);
}

async function ensureToggleActive(page, {
  label,
  control,
  code,
  actionCounts,
}) {
  await ensureControl({
    control,
    code,
    actionCounts,
    verify: async () => {
      const toggle = await resolveToggle(page, label);
      return Boolean(toggle && (await toggleState(toggle.locator)) === 'active');
    },
    apply: async () => {
      const toggle = await resolveToggle(page, label);
      if (!toggle) return false;
      await toggle.locator.click({ timeout: 10000 });
      return true;
    },
    verifyTimeoutMs: 3500,
  });
}

function stateClass(value, expected) {
  if (value === null) return 'missing_or_ambiguous';
  return value === expected ? 'expected' : 'unexpected';
}

async function safeMenuState(page, selector, expected) {
  const entry = await uniqueVisible(page.locator(selector));
  return stateClass(entry?.text ?? null, expected);
}

export async function readExochartsUiState(page) {
  const controls = await periodControls(page);
  const tick = await uniqueVisible(page.locator('input.topTickMultiplier'));
  const tickValue = tick
    ? normalizeText(await tick.locator.inputValue().catch(() => ''))
    : null;
  const fpbs = await resolveToggle(page, 'FPBS');
  const vwap = await resolveToggle(page, 'vWap');
  const bodyFlags = await page.locator('body').evaluate((body) => ({
    delayed: /delayed by 24 hours/i.test(body.innerText || ''),
  })).catch(() => ({ delayed: false }));
  return {
    live_connection: (await liveConnectionBlocked(page)) ? 'blocked' : 'not_blocked',
    controls_ready: await controlsReady(page),
    symbol: controls
      ? (symbolMatches(controls.symbol.text) ? 'expected' : 'unexpected')
      : 'missing_or_ambiguous',
    timeframe: stateClass(controls?.timeframe.text ?? null, EXOCHARTS_EXPECTED_CONFIG.timeframe),
    tick_multiplier: stateClass(tickValue, EXOCHARTS_EXPECTED_CONFIG.tickMultiplier),
    cluster_type: await safeMenuState(
      page,
      '#topChartTypeSelector',
      EXOCHARTS_EXPECTED_CONFIG.clusterType,
    ),
    text_type: await safeMenuState(
      page,
      '#topTextTypeSelector',
      EXOCHARTS_EXPECTED_CONFIG.textType,
    ),
    candle_type: await safeMenuState(
      page,
      '#topDCTypeSelector',
      EXOCHARTS_EXPECTED_CONFIG.candleType,
    ),
    fpbs: fpbs ? await toggleState(fpbs.locator) : 'missing_or_ambiguous',
    vwap: vwap ? await toggleState(vwap.locator) : 'missing_or_ambiguous',
    delayed_feed: Boolean(bodyFlags.delayed),
  };
}

export function defectForUiState(state) {
  if (state.live_connection === 'blocked') return EXOCHARTS_DEFECT_CODES.liveTakeover;
  if (state.delayed_feed) return EXOCHARTS_DEFECT_CODES.delayed;
  if (state.symbol !== 'expected') return EXOCHARTS_DEFECT_CODES.symbol;
  if (state.timeframe !== 'expected') return EXOCHARTS_DEFECT_CODES.timeframe;
  if (state.tick_multiplier !== 'expected') return EXOCHARTS_DEFECT_CODES.tick;
  if (state.cluster_type !== 'expected') return EXOCHARTS_DEFECT_CODES.cluster;
  if (state.text_type !== 'expected') return EXOCHARTS_DEFECT_CODES.imbalance;
  if (state.candle_type !== 'expected') return EXOCHARTS_DEFECT_CODES.candle;
  if (state.fpbs !== 'active') return EXOCHARTS_DEFECT_CODES.fpbs;
  if (state.vwap !== 'active') return EXOCHARTS_DEFECT_CODES.vwap;
  return null;
}

export async function configureExocharts(page, { actionCounts = {} } = {}) {
  await ensureSymbol(page, actionCounts);
  await ensureTimeframe(page, actionCounts);
  await ensureTickMultiplier(page, actionCounts);
  await ensureMenuValue(page, {
    selector: '#topChartTypeSelector',
    expectedValue: EXOCHARTS_EXPECTED_CONFIG.clusterType,
    control: 'cluster_type',
    code: EXOCHARTS_DEFECT_CODES.cluster,
    actionCounts,
  });
  await ensureMenuValue(page, {
    selector: '#topTextTypeSelector',
    expectedValue: EXOCHARTS_EXPECTED_CONFIG.textType,
    control: 'text_type',
    code: EXOCHARTS_DEFECT_CODES.imbalance,
    actionCounts,
  });
  await ensureMenuValue(page, {
    selector: '#topDCTypeSelector',
    expectedValue: EXOCHARTS_EXPECTED_CONFIG.candleType,
    control: 'candle_type',
    code: EXOCHARTS_DEFECT_CODES.candle,
    actionCounts,
  });
  await ensureToggleActive(page, {
    label: 'FPBS',
    control: 'fpbs',
    code: EXOCHARTS_DEFECT_CODES.fpbs,
    actionCounts,
  });
  await ensureToggleActive(page, {
    label: 'vWap',
    control: 'vwap',
    code: EXOCHARTS_DEFECT_CODES.vwap,
    actionCounts,
  });
  const state = await readExochartsUiState(page);
  const defect = defectForUiState(state);
  if (defect) throw new ExochartsUiError(defect, 'capture');
  return {
    state,
    action_counts: safeCountMap(actionCounts),
    correction_counts: correctionCounts(actionCounts),
  };
}

function writeExclusiveJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(
    filePath,
    `${JSON.stringify(payload, null, 2)}\n`,
    { encoding: 'utf8', flag: 'wx' },
  );
}

export async function writeSanitizedDiagnostic(page, {
  directory,
  error,
  actionCounts = {},
}) {
  const safeError = asExochartsUiError(error);
  fs.mkdirSync(directory, { recursive: true });
  const screenshotPath = path.join(directory, 'exocharts_diagnostic.png');
  const diagnosticPath = path.join(directory, 'exocharts_diagnostic.json');
  let screenshotWritten = false;
  if (!fs.existsSync(screenshotPath)) {
    const sensitive = page.locator([
      'input',
      'textarea',
      '[data-token]',
      '[data-secret]',
      '[data-testid*="account" i]',
      '[data-testid*="profile" i]',
      '[aria-label*="account" i]',
      '[aria-label*="profile" i]',
      '[class*="account-menu" i]',
      '[class*="user-menu" i]',
      '[class*="avatar" i]',
    ].join(', '));
    screenshotWritten = await page.screenshot({
      path: screenshotPath,
      fullPage: false,
      mask: [sensitive],
      maskColor: '#1f2937',
    }).then(() => true).catch(() => false);
  }
  const state = await readExochartsUiState(page).catch(() => ({
    live_connection: 'unknown',
    controls_ready: false,
    symbol: 'unknown',
    timeframe: 'unknown',
    tick_multiplier: 'unknown',
    cluster_type: 'unknown',
    text_type: 'unknown',
    candle_type: 'unknown',
    fpbs: 'unknown',
    vwap: 'unknown',
    delayed_feed: false,
  }));
  const payload = {
    schema_version: 'exocharts-capture-diagnostic-v1',
    status: 'failed',
    defect_code: safeError.code,
    control: safeError.control,
    captured_at: new Date().toISOString(),
    state,
    action_counts: safeCountMap(actionCounts),
    correction_counts: correctionCounts(actionCounts),
    screenshot_written: screenshotWritten,
    screenshot_file: screenshotWritten ? 'exocharts_diagnostic.png' : null,
    privacy: {
      cookies_included: false,
      browser_storage_included: false,
      free_text_error_included: false,
      sensitive_dom_masked: true,
    },
  };
  if (!fs.existsSync(diagnosticPath)) writeExclusiveJson(diagnosticPath, payload);
  return payload;
}

export function writeCaptureResult(filePath, {
  status,
  defectCode = null,
  diagnosticAvailable = false,
}) {
  if (!['passed', 'failed'].includes(status)) {
    throw new TypeError('unsupported Exocharts capture result status');
  }
  const normalizedCode = status === 'failed'
    ? (SAFE_CODE.test(String(defectCode)) ? String(defectCode) : EXOCHARTS_DEFECT_CODES.unexpected)
    : null;
  const payload = {
    schema_version: 'exocharts-capture-result-v1',
    status,
    defect_code: normalizedCode,
    diagnostic_available: status === 'failed' && diagnosticAvailable === true,
  };
  writeExclusiveJson(filePath, payload);
  return payload;
}

export function readCaptureResult(filePath, exitCode) {
  if (!fs.existsSync(filePath)) {
    return exitCode === 0
      ? {
        status: 'invalid',
        defect_code: 'capture.exocharts.result_missing',
        diagnostic_available: false,
      }
      : {
        status: 'failed',
        defect_code: EXOCHARTS_DEFECT_CODES.unexpected,
        diagnostic_available: false,
      };
  }
  try {
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const code = payload.defect_code;
    const valid = payload.schema_version === 'exocharts-capture-result-v1'
      && ['passed', 'failed'].includes(payload.status)
      && typeof payload.diagnostic_available === 'boolean'
      && ((payload.status === 'passed' && code === null)
        || (payload.status === 'failed'
          && SAFE_CODE.test(String(code))
          && String(code).startsWith('capture.exocharts.')))
      && (payload.status !== 'passed' || payload.diagnostic_available === false);
    if (!valid) {
      return {
        status: 'invalid',
        defect_code: 'capture.exocharts.result_invalid',
        diagnostic_available: false,
      };
    }
    if ((exitCode === 0) !== (payload.status === 'passed')) {
      return {
        status: 'invalid',
        defect_code: 'capture.exocharts.result_mismatch',
        diagnostic_available: false,
      };
    }
    return {
      status: payload.status,
      defect_code: code,
      diagnostic_available: payload.diagnostic_available,
    };
  } catch {
    return {
      status: 'invalid',
      defect_code: 'capture.exocharts.result_invalid',
      diagnostic_available: false,
    };
  }
}
