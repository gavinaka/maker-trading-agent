// CME-only collector for the FOMC rate-expectation source.
//
// This file never selects or calls a fallback provider. It produces one sealed
// cme_fedwatch_result.json which the provider state machine must validate before
// it can either select CME or consider Plan C.

import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

import {
  RATE_ARTIFACTS,
  hashRecord,
  sha256File,
  validateCmeResult,
  validateProviderContract,
  writeJsonAtomic,
} from './rate_expectation_state.js';


const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const CONTRACT_PATH = path.join(
  REPO_ROOT,
  'data_sources',
  'rate_expectation_provider_contract.json',
);
const CONTRACT = validateProviderContract(
  JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8')),
);
const URL = CONTRACT.cme.official_url;
const READY_MARKER = CONTRACT.cme.ready_marker;
const PROFILE_DIR = path.join(os.homedir(), '.cme_chrome_profile');


function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}


const OUT_DIR = path.join(REPO_ROOT, 'data_sources', 'inbox', localDate());
fs.mkdirSync(OUT_DIR, { recursive: true });


function artifactPath(envName, basename) {
  const requested = String(process.env[envName] || '').trim();
  const resolved = requested ? path.resolve(requested) : path.join(OUT_DIR, basename);
  if (path.dirname(resolved) !== OUT_DIR || path.basename(resolved) !== basename) {
    throw new Error(`${envName} must name ${basename} in the current inbox`);
  }
  return resolved;
}


const RESULT_PATH = artifactPath('CME_FEDWATCH_RESULT_PATH', RATE_ARTIFACTS.cmeResult);
const OUTPUT_PATH = artifactPath('CME_FEDWATCH_OUTPUT_PATH', RATE_ARTIFACTS.primaryImage);
const CAPTURE_RUN_ID = String(
  process.env.RATE_EXPECTATION_CAPTURE_RUN_ID || crypto.randomUUID(),
).trim();


function sealedResult({ startedAt, status, defectCode, output }) {
  const result = {
    schema_version: CONTRACT.cme_attempt_schema_version,
    capture_run_id: CAPTURE_RUN_ID,
    provider_id: CONTRACT.selection_modes.cme_primary.provider_id,
    status,
    defect_code: defectCode,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    output,
    attempt_sha256: '',
  };
  const hashField = CONTRACT.cme.attempt_artifact.hash_field;
  result[hashField] = hashRecord(result, hashField);
  validateCmeResult(result, CONTRACT);
  writeJsonAtomic(RESULT_PATH, result);
  return result;
}


async function pageText(page) {
  const parts = [];
  for (const frame of page.frames()) {
    try {
      const text = await frame.locator('body').innerText({ timeout: 1500 });
      if (text) parts.push(text);
    } catch {
      // Cross-origin or still-loading frames are expected; classification uses
      // only text that was actually readable.
    }
  }
  return parts.join('\n');
}


function technicalFailureCode(text, responseStatus) {
  if ([401, 403, 429, 451].includes(responseStatus)) return 'cme_access_blocked';
  if (Number.isInteger(responseStatus) && responseStatus >= 500 && responseStatus <= 599) {
    return 'cme_navigation_transport_failure';
  }
  if (/there was a problem loading this content or tool/i.test(text)) {
    return 'cme_tool_content_load_error';
  }
  if (
    /access denied|request unsuccessful|sorry, you have been blocked|forbidden|captcha/i
      .test(text)
  ) {
    return 'cme_access_blocked';
  }
  return null;
}


async function capture() {
  const startedAt = new Date().toISOString();
  let context = null;
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
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode: 'cme_browser_launch_failure',
        output: null,
      });
      return 3;
    }

    const page = context.pages()[0] || await context.newPage();
    let response;
    try {
      response = await page.goto(URL, {
        waitUntil: 'domcontentloaded',
        timeout: 60000,
      });
    } catch {
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode: 'cme_navigation_transport_failure',
        output: null,
      });
      return 2;
    }
    await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});

    for (const selector of [
      '#onetrust-reject-all-handler',
      '.onetrust-close-btn-handler',
      '.ot-pc-refuse-all-handler',
    ]) {
      const button = await page.$(selector);
      if (button) {
        await button.click().catch(() => {});
        break;
      }
    }

    const toolElement = await page
      .waitForSelector('iframe[id^="cmeIframe-"]', { timeout: 30000 })
      .catch(() => null);
    if (toolElement) await toolElement.scrollIntoViewIfNeeded().catch(() => {});

    let ready = false;
    if (toolElement) {
      for (let index = 0; index < 20 && !ready; index += 1) {
        for (const frame of page.frames()) {
          try {
            if (await frame.getByText(READY_MARKER, { exact: false }).first().isVisible()) {
              ready = true;
              break;
            }
          } catch {
            // Continue through the bounded render wait.
          }
        }
        if (!ready) await page.waitForTimeout(1500);
      }
    }

    if (!ready) {
      const text = await pageText(page);
      const explicitTechnicalFailure = technicalFailureCode(text, response?.status());
      const defectCode = explicitTechnicalFailure
        || (toolElement
          ? 'cme_probability_tool_unrendered'
          : 'cme_page_schema_unclassified');
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode,
        output: null,
      });
      return CONTRACT.cme.eligible_fallback_codes.includes(defectCode) ? 2 : 3;
    }

    await page.waitForTimeout(2500);
    try {
      await toolElement.screenshot({ path: OUTPUT_PATH });
    } catch {
      if (fs.existsSync(OUTPUT_PATH)) fs.unlinkSync(OUTPUT_PATH);
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode: 'cme_local_artifact_write_failure',
        output: null,
      });
      return 3;
    }
    const stat = fs.statSync(OUTPUT_PATH);
    if (!stat.isFile() || stat.size <= 0) {
      if (fs.existsSync(OUTPUT_PATH)) fs.unlinkSync(OUTPUT_PATH);
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode: 'cme_result_integrity_failure',
        output: null,
      });
      return 3;
    }
    sealedResult({
      startedAt,
      status: 'passed',
      defectCode: null,
      output: {
        path: RATE_ARTIFACTS.primaryImage,
        sha256: sha256File(OUTPUT_PATH),
        bytes: stat.size,
      },
    });
    return 0;
  } catch {
    if (fs.existsSync(OUTPUT_PATH)) fs.unlinkSync(OUTPUT_PATH);
    if (!fs.existsSync(RESULT_PATH)) {
      sealedResult({
        startedAt,
        status: 'failed',
        defectCode: 'cme_result_integrity_failure',
        output: null,
      });
    }
    return 3;
  } finally {
    if (context) await context.close().catch(() => {});
  }
}


process.exitCode = await capture();
