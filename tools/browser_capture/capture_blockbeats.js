// BlockBeats 快讯自动采集（Playwright/Chrome，公开页面，无需扩展）。
// 输出：data_sources/inbox/<YYYY-MM-DD>/blockbeats.png + blockbeats.json

import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const URL = 'https://www.theblockbeats.info/newsflash';

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const date = today();
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

  const bodyText = await page.locator('body').innerText();
  const lines = bodyText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  const dateIndex = lines.indexOf(date);
  const section = dateIndex >= 0 ? lines.slice(dateIndex + 1) : [];
  const rows = [];
  let current = null;

  for (const line of section) {
    if (line === '查看更多' || line === '本周大事件') break;
    const match = line.match(/^(\d{2}:\d{2})\s+(.+)$/);
    if (match) {
      if (current) rows.push(current);
      current = { time: match[1], title: match[2], body: '' };
      continue;
    }
    if (!current || line === '重要快讯' || line === '自动更新' || line === '[原文链接]') continue;
    current.body += `${current.body ? '\n' : ''}${line}`;
  }
  if (current) rows.push(current);

  const selected = rows.slice(0, 8).map((row) => ({
    ...row,
    text: `${row.time} ${row.title}`,
  }));
  const screenshot = path.join(outDir, 'blockbeats.png');
  const json = path.join(outDir, 'blockbeats.json');

  await page.screenshot({ path: screenshot, fullPage: false });
  fs.writeFileSync(
    json,
    JSON.stringify(
      {
        fetchedAt: new Date().toISOString(),
        capture_mode: 'playwright_unified_capture',
        important_only: importantOnly,
        title: await page.title(),
        url: page.url(),
        date,
        rows: selected,
      },
      null,
      2,
    ),
    'utf8',
  );

  console.log(`[blockbeats] 已保存 ${screenshot}`);
  console.log(`[blockbeats] 已保存 ${json}`);
  console.log(`[blockbeats] 当日快讯 ${rows.length} 条，保留最新 ${selected.length} 条`);

  const newest = selected[0]?.time || '';
  const valid = importantOnly && dateIndex >= 0 && selected.length >= 3 && /^\d{2}:\d{2}$/.test(newest);
  if (!valid) {
    console.log(`[blockbeats] VALIDITY: FAIL - dateIndex=${dateIndex} rows=${selected.length} newest=${newest || 'none'}`);
    process.exitCode = 2;
  } else {
    console.log(`[blockbeats] VALIDITY: OK - 最新 ${newest}`);
    process.exitCode = 0;
  }
} finally {
  await browser.close();
}
