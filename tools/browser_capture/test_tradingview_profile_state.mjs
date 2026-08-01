import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import {
  hidePlatformProfileOnce,
  inspectPlatformProfileState,
  isolatePreviousProfileState,
  validateProfileCaptureIdentity,
  writeProfileStateAtomic,
} from './tradingview_profile_state.js';

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="隐藏"></button>
    </div>
    <script>
      document.querySelector('button').addEventListener('click', (event) => {
        event.currentTarget.setAttribute('aria-label', '显示');
      });
    </script>
  `);
  assert.deepEqual(await inspectPlatformProfileState(page), {
    state: 'visible',
    certification_basis: 'profile_control',
  });
  assert.deepEqual(await hidePlatformProfileOnce(page), {
    initial: 'visible',
    final: 'hidden',
    correction_attempted: true,
    certification_basis: 'profile_control',
  });

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="显示指标"></button>
    </div>
  `);
  assert.deepEqual(await hidePlatformProfileOnce(page), {
    initial: 'hidden',
    final: 'hidden',
    correction_attempted: false,
    certification_basis: 'profile_control',
  });

  // No title match alone can never certify absence.
  await page.setContent('<div>legend has not loaded</div>');
  assert.deepEqual(await hidePlatformProfileOnce(page), {
    initial: 'unknown',
    final: 'unknown',
    correction_attempted: false,
    certification_basis: 'unverified',
  });

  // Absence is accepted only when the exact legend selector proves that the
  // certified SMA anchor is loaded and the profile title is not in inventory.
  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">SMA 20</span>
    </div>
  `);
  assert.deepEqual(await hidePlatformProfileOnce(page), {
    initial: 'absent',
    final: 'absent',
    correction_attempted: false,
    certification_basis: 'certified_legend_inventory',
  });

  await page.setContent(`
    <div style="display:none">
      <span data-qa-id="title-wrapper legend-source-title">SMA 20</span>
    </div>
  `);
  assert.equal((await inspectPlatformProfileState(page)).state, 'unknown');

  // Selector drift is not certified absence even if a lookalike title exists.
  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="changed-title-selector">SMA 20</span>
    </div>
  `);
  assert.equal((await inspectPlatformProfileState(page)).state, 'unknown');

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="显示"></button>
    </div>
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="显示"></button>
    </div>
  `);
  assert.equal((await inspectPlatformProfileState(page)).state, 'unknown');

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="显示"></button>
      <button data-qa-id="legend-show-hide-action" aria-label="隐藏"></button>
    </div>
  `);
  assert.equal((await inspectPlatformProfileState(page)).state, 'unknown');

  for (const title of [
    'Visible Range Volume Profile',
    'Volume Profile — Visible Range',
    'VPVR',
    'VRVP 30 rows',
    '可见范围：成交量分布',
    '成交量轮廓（可见范围）',
  ]) {
    await page.setContent(`
      <div class="noWrapWrapper-fixture">
        <span data-qa-id="title-wrapper legend-source-title">${title}</span>
        <button data-qa-id="legend-show-hide-action" title="Show indicator"></button>
      </div>
    `);
    assert.equal((await inspectPlatformProfileState(page)).state, 'hidden', title);
  }

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
    </div>
  `);
  assert.equal((await inspectPlatformProfileState(page)).state, 'unknown');

  await page.setContent(`
    <div class="noWrapWrapper-fixture">
      <span data-qa-id="title-wrapper legend-source-title">VRVP</span>
      <button data-qa-id="legend-show-hide-action" aria-label="toggle"></button>
    </div>
  `);
  assert.deepEqual(await hidePlatformProfileOnce(page), {
    initial: 'unknown',
    final: 'unknown',
    correction_attempted: false,
    certification_basis: 'unverified',
  });
} finally {
  await browser.close();
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'tv-profile-sidecar-'));
try {
  const target = path.join(temporary, 'tradingview_profile_state.json');
  const captureRunId = '11111111-1111-4111-8111-111111111111';
  const captureNonce = '22222222-2222-4222-8222-222222222222';
  validateProfileCaptureIdentity(captureRunId, captureNonce);
  assert.throws(
    () => validateProfileCaptureIdentity('old-run', captureNonce),
    /invalid TradingView profile capture run id/,
  );

  fs.writeFileSync(target, '{"capture_run_id":"stale"}\n', 'utf8');
  isolatePreviousProfileState(target);
  assert.equal(fs.existsSync(target), false);
  const payload = {
    schema_version: 'tradingview-profile-state-v2',
    capture_run_id: captureRunId,
    capture_nonce: captureNonce,
  };
  writeProfileStateAtomic(target, payload, captureNonce);
  assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), payload);
  assert.equal(
    fs.readdirSync(temporary).some((name) => name.endsWith('.tmp')),
    false,
  );

  isolatePreviousProfileState(target);
  fs.writeFileSync(target, '{"capture_run_id":"racing-writer"}\n', 'utf8');
  assert.throws(
    () => writeProfileStateAtomic(target, payload, captureNonce),
    /target reappeared/,
  );
  assert.equal(
    JSON.parse(fs.readFileSync(target, 'utf8')).capture_run_id,
    'racing-writer',
  );
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

console.log('TradingView profile visibility and sidecar fixtures passed');
