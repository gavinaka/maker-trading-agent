import fs from 'fs';
import path from 'path';

const ABSENCE_STABILITY_SAMPLES = 3;
const ABSENCE_STABILITY_WAIT_MS = 400;

// This function is deliberately self-contained so Playwright can serialize it
// into the page. A single DOM read never proves absence. It may only return an
// internal absence candidate when the document is complete and the exact
// legend selector contains one certified SMA20 anchor. The Node-side wrapper
// then requires the complete visible-title inventory to remain identical over
// multiple reads before it upgrades the candidate to certified absence.
function inspectPlatformProfileInPage() {
  function normalize(value) {
    return String(value || '')
      .normalize('NFKC')
      .replace(/[\s_\-–—:：·()（）]+/g, ' ')
      .trim()
      .toLowerCase();
  }
  function isProfile(value) {
    const normalized = normalize(value);
    if (/^(?:vrvp|vpvr)(?:\b|$)/.test(normalized)) return true;
    const words = new Set(normalized.split(' '));
    if (
      words.has('visible')
      && words.has('range')
      && words.has('volume')
      && words.has('profile')
    ) return true;
    const compact = normalized.replace(/\s+/g, '');
    return (
      compact.includes('可见范围')
      && (compact.includes('成交量分布') || compact.includes('成交量轮廓'))
    );
  }
  function isAnchor(value) {
    const normalized = normalize(value);
    const compact = normalized.replace(/\s+/g, '');
    return (
      /^sma\s*20(?:\D|$)/i.test(normalized)
      || /(?:^|\s)simple moving average\s*20(?:\D|$)/i.test(normalized)
      || /^简单移动平均(?:线)?20(?:\D|$)/.test(compact)
    );
  }

  const connectedTitles = [
    ...document.querySelectorAll('[data-qa-id="title-wrapper legend-source-title"]'),
  ].filter((element) => element.isConnected);
  const titles = connectedTitles.filter((element) => {
    const style = window.getComputedStyle(element);
    return (
      element.getClientRects().length > 0
      && style.display !== 'none'
      && style.visibility !== 'hidden'
    );
  });
  if (
    connectedTitles.some((element) => isProfile(element.textContent))
    && !titles.some((element) => isProfile(element.textContent))
  ) {
    return { state: 'unknown', certification_basis: 'unverified' };
  }
  const profileTitles = titles.filter((element) => isProfile(element.textContent));
  if (profileTitles.length > 1) {
    return { state: 'unknown', certification_basis: 'unverified' };
  }
  const title = profileTitles[0];
  if (!title) {
    const normalizedTitles = connectedTitles.map((element) => normalize(element.textContent));
    const anchorCount = titles.filter((element) => isAnchor(element.textContent)).length;
    if (document.readyState !== 'complete' || anchorCount !== 1) {
      return { state: 'unknown', certification_basis: 'unverified' };
    }
    return {
      state: 'absence_candidate',
      certification_basis: 'unverified',
      inventory_signature: JSON.stringify(normalizedTitles),
    };
  }
  const item = title.closest('div[class*="noWrapWrapper"]') || title.parentElement?.parentElement;
  const buttons = item
    ? [...item.querySelectorAll('[data-qa-id="legend-show-hide-action"]')]
      .filter((element) => {
        const style = window.getComputedStyle(element);
        return (
          element.isConnected
          && element.getClientRects().length > 0
          && style.display !== 'none'
          && style.visibility !== 'hidden'
        );
      })
    : [];
  if (buttons.length !== 1) {
    return { state: 'unknown', certification_basis: 'unverified' };
  }
  const button = buttons[0];
  const label = [
    button.getAttribute('aria-label'),
    button.getAttribute('title'),
    button.getAttribute('data-tooltip'),
  ].filter(Boolean).join(' ').trim();
  if (/(?:显示|\bshow\b)/i.test(label)) {
    return { state: 'hidden', certification_basis: 'profile_control' };
  }
  if (/(?:隐藏|\bhide\b)/i.test(label)) {
    return { state: 'visible', certification_basis: 'profile_control' };
  }
  return { state: 'unknown', certification_basis: 'unverified' };
}

function clickVisiblePlatformProfileInPage() {
  const titles = [...document.querySelectorAll('[data-qa-id="title-wrapper legend-source-title"]')]
    .filter((element) => {
      const style = window.getComputedStyle(element);
      return (
        element.isConnected
        && element.getClientRects().length > 0
        && style.display !== 'none'
        && style.visibility !== 'hidden'
      );
    });
  const normalize = (value) => String(value || '')
    .normalize('NFKC')
    .replace(/[\s_\-–—:：·()（）]+/g, ' ')
    .trim()
    .toLowerCase();
  const isProfile = (value) => {
    const normalized = normalize(value);
    if (/^(?:vrvp|vpvr)(?:\b|$)/.test(normalized)) return true;
    const words = new Set(normalized.split(' '));
    const english = words.has('visible') && words.has('range')
      && words.has('volume') && words.has('profile');
    const compact = normalized.replace(/\s+/g, '');
    return english || (
      compact.includes('可见范围')
      && (compact.includes('成交量分布') || compact.includes('成交量轮廓'))
    );
  };
  const profileTitles = titles.filter((element) => isProfile(element.textContent));
  if (profileTitles.length !== 1) return false;
  const title = profileTitles[0];
  const item = title?.closest('div[class*="noWrapWrapper"]') || title?.parentElement?.parentElement;
  const buttons = item
    ? [...item.querySelectorAll('[data-qa-id="legend-show-hide-action"]')]
      .filter((element) => {
        const style = window.getComputedStyle(element);
        return (
          element.isConnected
          && element.getClientRects().length > 0
          && style.display !== 'none'
          && style.visibility !== 'hidden'
        );
      })
    : [];
  if (buttons.length !== 1) return false;
  const button = buttons[0];
  button.click();
  return true;
}

export async function inspectPlatformProfileState(page) {
  const fallback = { state: 'unknown', certification_basis: 'unverified' };
  const candidates = [];
  for (let sample = 0; sample < ABSENCE_STABILITY_SAMPLES; sample += 1) {
    const inspection = await page.evaluate(inspectPlatformProfileInPage).catch(() => fallback);
    if (inspection.state !== 'absence_candidate') {
      return {
        state: inspection.state,
        certification_basis: inspection.certification_basis,
      };
    }
    candidates.push(inspection.inventory_signature);
    if (sample + 1 < ABSENCE_STABILITY_SAMPLES) {
      const waited = await page.waitForTimeout(ABSENCE_STABILITY_WAIT_MS)
        .then(() => true)
        .catch(() => false);
      if (!waited) return fallback;
    }
  }
  if (
    candidates.length === ABSENCE_STABILITY_SAMPLES
    && new Set(candidates).size === 1
  ) {
    return { state: 'absent', certification_basis: 'certified_legend_inventory' };
  }
  return fallback;
}

export async function hidePlatformProfileOnce(page) {
  const initialInspection = await inspectPlatformProfileState(page);
  if (initialInspection.state !== 'visible') {
    return {
      initial: initialInspection.state,
      final: initialInspection.state,
      correction_attempted: false,
      certification_basis: initialInspection.certification_basis,
    };
  }
  const clicked = await page.evaluate(clickVisiblePlatformProfileInPage).catch(() => false);
  if (clicked) await page.waitForTimeout(1200);
  const finalInspection = clicked
    ? await inspectPlatformProfileState(page)
    : { state: 'unknown', certification_basis: 'unverified' };
  return {
    initial: initialInspection.state,
    final: finalInspection.state,
    correction_attempted: true,
    certification_basis: finalInspection.certification_basis,
  };
}

export function validateProfileCaptureIdentity(captureRunId, captureNonce) {
  const identityPattern = /^[0-9a-f-]{16,64}$/i;
  if (!identityPattern.test(String(captureRunId || ''))) {
    throw new Error('invalid TradingView profile capture run id');
  }
  if (!identityPattern.test(String(captureNonce || ''))) {
    throw new Error('invalid TradingView profile capture nonce');
  }
}

export function isolatePreviousProfileState(target) {
  if (!fs.existsSync(target)) return;
  const stat = fs.lstatSync(target);
  if (!stat.isFile()) {
    throw new Error('TradingView profile sidecar target is not a regular file');
  }
  fs.unlinkSync(target);
}

export function writeProfileStateAtomic(target, payload, captureNonce) {
  const directory = path.dirname(target);
  fs.mkdirSync(directory, { recursive: true });
  const temporary = path.join(directory, `.${path.basename(target)}.${captureNonce}.tmp`);
  let descriptor = null;
  try {
    descriptor = fs.openSync(temporary, 'wx');
    fs.writeFileSync(descriptor, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = null;
    if (fs.existsSync(target)) {
      throw new Error('TradingView profile sidecar target reappeared before atomic replace');
    }
    fs.renameSync(temporary, target);
  } finally {
    if (descriptor !== null) fs.closeSync(descriptor);
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

// Exported only for lightweight source-level tests; capture uses the page-safe
// functions above and never reads browser storage, cookies, or account tokens.
export { inspectPlatformProfileInPage };
