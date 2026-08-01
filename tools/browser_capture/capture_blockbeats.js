// BlockBeats 快讯自动采集（Playwright/Chrome，公开页面，无需扩展）。
// 输出：data_sources/inbox/<YYYY-MM-DD>/blockbeats.png + blockbeats.json
// 规则：每次抓取必须覆盖抓取前 12 小时「重要快讯」候选池，并按基本面优先级筛出影响最大的 3 条。

import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { classifyImpact, selectTopRowsByPriority } from './blockbeats_priority.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const URL = 'https://www.theblockbeats.info/newsflash';
const WINDOW_HOURS = 12;
const TOP_N = 3;
const MAX_LOAD_MORE_CLICKS = 14;

function partsInShanghai(date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

function shanghaiDate(date) {
  const p = partsInShanghai(date);
  return `${p.year}-${p.month}-${p.day}`;
}

function rowEpochMs(dateText, timeText) {
  return Date.parse(`${dateText}T${timeText}:00+08:00`);
}

function parseRowsFromBody(bodyText) {
  const lines = bodyText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  const rows = [];
  let activeDate = null;
  let current = null;

  function pushCurrent() {
    if (!current) return;
    current.datetime = `${current.date}T${current.time}:00+08:00`;
    current.epoch_ms = rowEpochMs(current.date, current.time);
    current.text = `${current.time} ${current.title}`;
    if (Number.isFinite(current.epoch_ms)) rows.push(current);
    current = null;
  }

  for (const line of lines) {
    const dateMatch = line.match(/^(20\d{2}-\d{2}-\d{2})$/);
    if (dateMatch) {
      pushCurrent();
      activeDate = dateMatch[1];
      continue;
    }
    const timeMatch = line.match(/^(\d{2}:\d{2})\s+(.+)$/);
    if (timeMatch && activeDate) {
      pushCurrent();
      current = {
        date: activeDate,
        time: timeMatch[1],
        title: timeMatch[2],
        body: '',
      };
      continue;
    }
    if (
      !current
      || line === '重要快讯'
      || line === '自动更新'
      || line === '[原文链接]'
      || line === '查看更多'
      || line === '本周大事件'
    ) {
      continue;
    }
    current.body += `${current.body ? '\n' : ''}${line}`;
  }
  pushCurrent();
  return rows;
}

async function readRows(page) {
  const bodyText = await page.locator('body').innerText();
  return parseRowsFromBody(bodyText);
}

const now = new Date();
const date = shanghaiDate(now);
const nowMs = now.getTime();
const windowStartMs = nowMs - WINDOW_HOURS * 60 * 60 * 1000;
const windowStartIso = new Date(windowStartMs).toISOString();
const outDir = path.join(REPO_ROOT, 'data_sources', 'inbox', date);
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  args: ['--disable-blink-features=AutomationControlled'],
});

try {
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1000 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  });

  console.log(`[blockbeats] 打开: ${URL}`);
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(8000);

  const notificationLater = page.locator('#onesignal-slidedown-cancel-button');
  if (await notificationLater.isVisible().catch(() => false)) {
    await notificationLater.click({ force: true });
  }
  const importantOnlyLabel = page.locator('label.el-checkbox').filter({ hasText: '重要快讯' }).first();
  await importantOnlyLabel.waitFor({ state: 'visible', timeout: 15000 });
  const importantOnlyCheckbox = importantOnlyLabel.locator('input[type="checkbox"]');
  if (!(await importantOnlyCheckbox.isChecked())) {
    await importantOnlyCheckbox.evaluate((element) => element.click());
    await page.waitForFunction(
      () => {
        const labels = [...document.querySelectorAll('label.el-checkbox')];
        const label = labels.find((node) => node.textContent?.includes('重要快讯'));
        return label?.querySelector('input[type="checkbox"]')?.checked === true;
      },
      null,
      { timeout: 10000 },
    );
    await page.waitForTimeout(3000);
  }
  const importantOnly = await importantOnlyCheckbox.isChecked();
  if (!importantOnly) {
    throw new Error('[blockbeats] 重要快讯筛选未能保持选中');
  }

  let allRows = [];
  let windowCovered = false;
  let oldestLoadedMs = Infinity;
  let oldestLoadedAt = null;
  let loadMoreVisibleAfterLoop = false;
  for (let attempt = 0; attempt <= MAX_LOAD_MORE_CLICKS; attempt += 1) {
    allRows = await readRows(page);
    oldestLoadedMs = allRows.length ? Math.min(...allRows.map((row) => row.epoch_ms)) : Infinity;
    const oldestRow = allRows.find((row) => row.epoch_ms === oldestLoadedMs);
    oldestLoadedAt = oldestRow?.datetime || null;
    const inWindow = allRows.filter((row) => row.epoch_ms >= windowStartMs && row.epoch_ms <= nowMs + 60000);
    if (oldestLoadedMs <= windowStartMs && inWindow.length >= TOP_N) {
      windowCovered = true;
      break;
    }
    const more = page.getByText('查看更多', { exact: true }).last();
    loadMoreVisibleAfterLoop = await more.isVisible().catch(() => false);
    if (!loadMoreVisibleAfterLoop) {
      windowCovered = inWindow.length >= TOP_N;
      break;
    }
    await more.click({ timeout: 5000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1800);
  }

  const candidateRows = allRows
    .filter((row) => row.epoch_ms >= windowStartMs && row.epoch_ms <= nowMs + 60000)
    .map((row) => ({
      ...row,
      analysis_priority: classifyImpact(row, nowMs, WINDOW_HOURS),
    }));
  const selected = selectTopRowsByPriority(candidateRows, TOP_N)
    .map((row, index) => ({
      ...row,
      selected_rank: index + 1,
    }));
  const screenshot = path.join(outDir, 'blockbeats.png');
  const json = path.join(outDir, 'blockbeats.json');

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await page.screenshot({ path: screenshot, fullPage: false });
  fs.writeFileSync(
    json,
    JSON.stringify(
      {
        fetchedAt: new Date().toISOString(),
        capture_mode: 'playwright_unified_capture',
        important_only: importantOnly,
        capture_window_hours: WINDOW_HOURS,
        selection_policy: 'last_12h_all_important_then_top3_by_fundamental_priority',
        event_family_deduplication_policy: 'ppi_by_jurisdiction_and_reported_period',
        selected_count_required: TOP_N,
        window_start: windowStartIso,
        window_end: now.toISOString(),
        window_covered: windowCovered,
        oldest_loaded_at: oldestLoadedAt,
        load_more_visible_after_loop: loadMoreVisibleAfterLoop,
        title: await page.title(),
        url: page.url(),
        date,
        candidate_count: candidateRows.length,
        candidate_rows: candidateRows,
        selected_rows: selected,
        rows: selected,
      },
      null,
      2,
    ),
    'utf8',
  );

  console.log(`[blockbeats] 已保存 ${screenshot}`);
  console.log(`[blockbeats] 已保存 ${json}`);
  console.log(`[blockbeats] 12小时候选 ${candidateRows.length} 条，筛选影响最大 ${selected.length} 条`);

  const newest = selected[0]?.time || '';
  const valid = (
    importantOnly
    && windowCovered
    && candidateRows.length >= TOP_N
    && selected.length === TOP_N
    && selected.every((row) => row.epoch_ms >= windowStartMs && row.epoch_ms <= nowMs + 60000)
    && /^\d{2}:\d{2}$/.test(newest)
  );
  if (!valid) {
    console.log(`[blockbeats] VALIDITY: FAIL - covered=${windowCovered} oldest=${oldestLoadedAt || 'none'} windowRows=${candidateRows.length} selected=${selected.length} newest=${newest || 'none'}`);
    process.exitCode = 2;
  } else {
    console.log(`[blockbeats] VALIDITY: OK - 12h候选 ${candidateRows.length}，Top3首条时间 ${newest}`);
    process.exitCode = 0;
  }
} finally {
  await browser.close();
}
