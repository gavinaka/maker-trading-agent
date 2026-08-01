import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { chromium } from 'playwright';

import {
  EXOCHARTS_DEFECT_CODES,
  ExochartsUiError,
  configureExocharts,
  ensureLiveConnection,
  readCaptureResult,
  writeCaptureResult,
  writeSanitizedDiagnostic,
} from './exocharts_ui_state.js';

function readyControls() {
  return `
    <button id="topPeriodSelector">Bybit: BTCUSD</button>
    <button id="topPeriodSelector">D</button>
    <button id="topChartTypeSelector">Bid-Ask Profile</button>
  `;
}

async function loadFixture(page, html, name) {
  const url = `http://exocharts-fixture.test/${name}`;
  await page.route(url, (route) => route.fulfill({
    status: 200,
    contentType: 'text/html',
    body: html,
  }));
  await page.goto(url);
}

function configuredFixture({ vwapChanges = true, symbolFirstClickIgnored = false } = {}) {
  return `<!doctype html>
  <html><body>
    <div style="display:none">
      <button id="topPeriodSelector">Hidden: BTCUSD</button>
      <button id="topPeriodSelector">1H</button>
      <button class="topColBtn">vWap</button>
    </div>
    <button id="symbol" data-role="symbol">BitMEX: XBTUSD</button>
    <button id="timeframe" data-role="timeframe">1H</button>
    <div id="symbol-menu" hidden>
      <div class="exchange-column"><span>Bybit:</span><button class="item" id="bybit-btc">BTCUSD</button></div>
      <div class="exchange-column"><span>BitMEX:</span><button class="item">BTCUSD</button></div>
    </div>
    <div id="timeframe-menu" hidden><button class="item" id="daily">Daily</button></div>
    <input class="topTickMultiplier" value="60">
    <button id="topChartTypeSelector">Candles</button>
    <div id="chart-menu" hidden><button class="item" id="bidask">Bid-Ask Profile</button></div>
    <button id="topTextTypeSelector">Delta</button>
    <div id="text-menu" hidden><button class="item" id="imbalance">Imbalance</button></div>
    <button id="topDCTypeSelector">Candle</button>
    <div id="candle-menu" hidden><button class="item" id="none">None</button></div>
    <button class="topColBtn" id="fpbs" aria-pressed="false" style="color:rgb(110,110,110)">FPBS</button>
    <button class="topColBtn" id="vwap" style="color:${vwapChanges ? 'rgb(255,193,7)' : 'rgb(110,110,110)'}">vWap</button>
    <script>
      const symbol = document.querySelector('[data-role="symbol"]');
      const timeframe = document.querySelector('[data-role="timeframe"]');
      symbol.id = 'topPeriodSelector';
      timeframe.id = 'topPeriodSelector';
      symbol.addEventListener('click', () => { document.querySelector('#symbol-menu').hidden = false; });
      timeframe.addEventListener('click', () => { document.querySelector('#timeframe-menu').hidden = false; });
      let symbolClicks = 0;
      document.querySelector('#bybit-btc').addEventListener('click', () => {
        symbolClicks += 1;
        document.querySelector('#symbol-menu').hidden = true;
        if (!${symbolFirstClickIgnored ? 'true' : 'false'} || symbolClicks > 1) symbol.textContent = 'Bybit: BTCUSD';
      });
      document.querySelector('#daily').addEventListener('click', () => {
        timeframe.textContent = 'D'; document.querySelector('#timeframe-menu').hidden = true;
      });
      document.querySelector('#topChartTypeSelector').addEventListener('click', () => { document.querySelector('#chart-menu').hidden = false; });
      document.querySelector('#bidask').addEventListener('click', () => {
        document.querySelector('#topChartTypeSelector').textContent = 'Bid-Ask Profile'; document.querySelector('#chart-menu').hidden = true;
      });
      document.querySelector('#topTextTypeSelector').addEventListener('click', () => { document.querySelector('#text-menu').hidden = false; });
      document.querySelector('#imbalance').addEventListener('click', () => {
        document.querySelector('#topTextTypeSelector').textContent = 'Imbalance'; document.querySelector('#text-menu').hidden = true;
      });
      document.querySelector('#topDCTypeSelector').addEventListener('click', () => { document.querySelector('#candle-menu').hidden = false; });
      document.querySelector('#none').addEventListener('click', () => {
        document.querySelector('#topDCTypeSelector').textContent = 'None'; document.querySelector('#candle-menu').hidden = true;
      });
      document.querySelector('#fpbs').addEventListener('click', (event) => {
        event.currentTarget.setAttribute('aria-pressed', 'true'); event.currentTarget.style.color = 'rgb(255,255,255)';
      });
      let vwapClicks = 0;
      document.querySelector('#vwap').addEventListener('click', (event) => {
        vwapClicks += 1;
        if (${vwapChanges ? 'true' : 'false'}) event.currentTarget.style.color = 'rgb(255,193,7)';
      });
      window.fixtureState = () => ({ symbolClicks, vwapClicks });
    </script>
  </body></html>`;
}

const browser = await chromium.launch({ headless: true });
try {
  {
    const page = await browser.newPage();
    await loadFixture(page, `<!doctype html><html><body>
      <div style="display:none">Your plan does not allow more LIVE connections<button>Take over</button></div>
      <section id="blocker">Your plan does not allow more LIVE connections<button id="takeover">Terminate previous connection</button></section>
      <div id="controls" hidden>${readyControls()}</div>
      <script>
        document.querySelector('#takeover').addEventListener('click', () => {
          document.querySelector('#blocker').hidden = true;
          document.querySelector('#controls').hidden = false;
        });
      </script>
    </body></html>`, 'live-takeover');
    const actionCounts = {};
    const result = await ensureLiveConnection(page, {
      actionCounts,
      initialTimeoutMs: 1000,
      transitionTimeoutMs: 1000,
    });
    assert.equal(result.takeoverRequired, true);
    assert.equal(actionCounts.live_takeover, 1);
    assert.equal(await page.locator('#controls').isVisible(), true);
    await page.close();
  }

  {
    const page = await browser.newPage();
    await loadFixture(page, `<!doctype html><html><body>
      <section>Your plan does not allow more LIVE connections
        <button>Dismiss</button><button>Terminate previous connection</button>
      </section>
    </body></html>`, 'ambiguous-live-takeover');
    let caught = null;
    try {
      await ensureLiveConnection(page, {
        initialTimeoutMs: 500,
        transitionTimeoutMs: 500,
      });
    } catch (error) {
      caught = error;
    }
    assert.ok(caught instanceof ExochartsUiError);
    assert.equal(caught.code, EXOCHARTS_DEFECT_CODES.liveActionMissing);
    await page.close();
  }

  {
    const page = await browser.newPage();
    await loadFixture(
      page,
      configuredFixture({ symbolFirstClickIgnored: true }),
      'bounded-correction',
    );
    const actionCounts = {};
    const result = await configureExocharts(page, { actionCounts });
    assert.equal(result.state.symbol, 'expected');
    assert.equal(result.state.timeframe, 'expected');
    assert.equal(result.state.vwap, 'active');
    assert.equal(actionCounts.symbol, 2);
    assert.equal(result.correction_counts.symbol, 1);
    assert.equal(actionCounts.vwap, undefined, 'yellow active vWap must not be toggled off');
    assert.deepEqual(await page.evaluate(() => window.fixtureState()), {
      symbolClicks: 2,
      vwapClicks: 0,
    });
    await page.close();
  }

  {
    const page = await browser.newPage();
    await loadFixture(
      page,
      configuredFixture({ vwapChanges: false }),
      'toggle-failure',
    );
    const actionCounts = {};
    let caught = null;
    try {
      await configureExocharts(page, { actionCounts });
    } catch (error) {
      caught = error;
    }
    assert.ok(caught instanceof ExochartsUiError);
    assert.equal(caught.code, EXOCHARTS_DEFECT_CODES.vwap);
    assert.equal(actionCounts.vwap, 2, 'one initial action plus one local correction only');
    assert.equal((await page.evaluate(() => window.fixtureState())).vwapClicks, 2);

    const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'exo-diagnostic-'));
    try {
      await page.evaluate(() => {
        localStorage.setItem('session_token', 'never-export-this-token');
        const secret = document.createElement('input');
        secret.value = 'never-export-this-token';
        document.body.append(secret);
      });
      const diagnostic = await writeSanitizedDiagnostic(page, {
        directory: tempRoot,
        error: caught,
        actionCounts,
      });
      const diagnosticText = fs.readFileSync(
        path.join(tempRoot, 'exocharts_diagnostic.json'),
        'utf8',
      );
      assert.equal(diagnostic.defect_code, EXOCHARTS_DEFECT_CODES.vwap);
      assert.equal(diagnostic.correction_counts.vwap, 1);
      assert.equal(diagnostic.privacy.cookies_included, false);
      assert.equal(diagnostic.privacy.browser_storage_included, false);
      assert.equal(diagnosticText.includes('never-export-this-token'), false);
      assert.equal(fs.existsSync(path.join(tempRoot, 'exocharts_diagnostic.png')), true);

      const resultPath = path.join(tempRoot, 'exocharts_result.json');
      writeCaptureResult(resultPath, {
        status: 'failed',
        defectCode: EXOCHARTS_DEFECT_CODES.vwap,
        diagnosticAvailable: true,
      });
      assert.deepEqual(readCaptureResult(resultPath, 2), {
        status: 'failed',
        defect_code: EXOCHARTS_DEFECT_CODES.vwap,
        diagnostic_available: true,
      });
      const unsafeResultPath = path.join(tempRoot, 'unsafe_result.json');
      fs.writeFileSync(unsafeResultPath, JSON.stringify({
        schema_version: 'exocharts-capture-result-v1',
        status: 'failed',
        defect_code: 'vWap failed: token=never-export-this-token',
      }));
      assert.deepEqual(readCaptureResult(unsafeResultPath, 2), {
        status: 'invalid',
        defect_code: 'capture.exocharts.result_invalid',
        diagnostic_available: false,
      });
    } finally {
      fs.rmSync(tempRoot, { recursive: true, force: true });
    }
    await page.close();
  }
} finally {
  await browser.close();
}

console.log('exocharts ui state fixtures: PASS');
