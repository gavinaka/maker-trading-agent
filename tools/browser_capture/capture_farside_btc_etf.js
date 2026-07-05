// Capture Farside Bitcoin spot ETF flow evidence.
//
// Outputs:
//   data_sources/inbox/<YYYY-MM-DD>/farside_btc_etf.png
//   data_sources/inbox/<YYYY-MM-DD>/farside_btc_etf.json

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const URL = 'https://farside.co.uk/btc/';
const SOURCE = 'farside_btc_etf';

function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function cleanText(value) {
  return String(value ?? '')
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseUsdMillions(value) {
  const raw = cleanText(value);
  if (!raw || raw === '-' || raw.toLowerCase() === 'n/a') return null;
  const negativeByParentheses = /^\(.+\)$/.test(raw);
  const normalized = raw.replace(/[(),$]/g, '').replace(/,/g, '');
  if (!/^-?\d+(?:\.\d+)?$/.test(normalized)) return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) return null;
  return negativeByParentheses ? -Math.abs(parsed) : parsed;
}

function dateIso(dateText) {
  const match = cleanText(dateText).match(/^(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})$/);
  if (!match) return null;
  const months = {
    Jan: '01',
    Feb: '02',
    Mar: '03',
    Apr: '04',
    May: '05',
    Jun: '06',
    Jul: '07',
    Aug: '08',
    Sep: '09',
    Oct: '10',
    Nov: '11',
    Dec: '12',
  };
  const month = months[match[2]];
  if (!month) return null;
  return `${match[3]}-${month}-${match[1].padStart(2, '0')}`;
}

function flowDirection(total) {
  if (total > 0) return 'inflow';
  if (total < 0) return 'outflow';
  return 'flat';
}

function round1(value) {
  return Math.round(value * 10) / 10;
}

function compareMagnitude(latest, previous) {
  if (!previous || latest.direction === 'flat' || previous.direction === 'flat') {
    return 'not_comparable';
  }
  if (Math.abs(latest.total_usd_m) > Math.abs(previous.total_usd_m)) {
    return 'expanding';
  }
  if (Math.abs(latest.total_usd_m) < Math.abs(previous.total_usd_m)) {
    return 'contracting';
  }
  return 'unchanged';
}

const date = localDate();
const outDir = path.join(REPO_ROOT, 'data_sources', 'inbox', date);
fs.mkdirSync(outDir, { recursive: true });
const pngPath = path.join(outDir, 'farside_btc_etf.png');
const jsonPath = path.join(outDir, 'farside_btc_etf.json');

const browser = await chromium.launch({
  channel: 'chrome',
  headless: process.env.HEADLESS !== '0',
  args: ['--disable-blink-features=AutomationControlled'],
});

let exitCode = 0;
try {
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1100 },
    locale: 'en-GB',
    timezoneId: 'Asia/Shanghai',
    userAgent: (
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      + 'AppleWebKit/537.36 (KHTML, like Gecko) '
      + 'Chrome/126.0.0.0 Safari/537.36'
    ),
  });

  console.log(`[farside_btc_etf] open: ${URL}`);
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2500);

  const parsed = await page.evaluate(() => {
    const normalize = (value) => String(value ?? '')
      .replace(/\u00a0/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    const tables = [...document.querySelectorAll('table')];
    const table = tables.find((candidate) => {
      const text = normalize(candidate.innerText);
      return (
        text.includes('IBIT')
        && text.includes('FBTC')
        && text.includes('GBTC')
        && text.includes('Total')
      );
    });
    if (!table) {
      return {
        page_title: document.title,
        body_title: normalize(document.body?.innerText || '').slice(0, 120),
        table_found: false,
        rows: [],
      };
    }
    return {
      page_title: document.title,
      body_title: normalize(document.querySelector('h1')?.innerText || ''),
      table_found: true,
      rows: [...table.rows].map((row) => (
        [...row.cells].map((cell) => normalize(cell.innerText))
      )),
    };
  });

  const headerRow = parsed.rows[1] || [];
  const topRow = parsed.rows[0] || [];
  const columns = headerRow.map((name, index) => {
    if (index === 0) return 'date';
    if (name) return name;
    if (topRow[index]) return topRow[index];
    return `column_${index}`;
  });
  const totalIndex = columns.findIndex((name) => name.toLowerCase() === 'total');
  const dailyRows = parsed.rows
    .filter((cells) => /^\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}$/.test(cleanText(cells[0])))
    .map((cells) => {
      const funds = {};
      columns.slice(1).forEach((name, offset) => {
        const index = offset + 1;
        if (index === totalIndex || !name || name === `column_${index}`) return;
        funds[name] = parseUsdMillions(cells[index]);
      });
      const total = parseUsdMillions(cells[totalIndex]);
      return {
        date: cleanText(cells[0]),
        date_iso: dateIso(cells[0]),
        total_usd_m: total,
        direction: Number.isFinite(total) ? flowDirection(total) : 'invalid',
        funds,
        raw_cells: cells,
      };
    });
  dailyRows.sort((a, b) => String(a.date_iso).localeCompare(String(b.date_iso)));
  const latest = dailyRows.at(-1) || null;
  const previous = dailyRows.at(-2) || null;
  const recent = dailyRows.slice(-5);
  const latestWithTrend = latest
    ? {
        ...latest,
        previous_total_usd_m: previous?.total_usd_m ?? null,
        previous_direction: previous?.direction ?? null,
        same_direction_as_previous: (
          Boolean(previous)
          && latest.direction !== 'flat'
          && latest.direction === previous.direction
        ),
        magnitude_vs_previous: compareMagnitude(latest, previous),
      }
    : null;

  const validity = {
    title_match: /Bitcoin ETF Flow \(US\$m\)/i.test(
      `${parsed.page_title} ${parsed.body_title}`,
    ),
    table_found: parsed.table_found === true,
    has_total_column: totalIndex >= 0,
    daily_row_count: dailyRows.length,
    latest_daily_row: Boolean(latest?.date_iso),
    latest_total_is_number: Number.isFinite(latest?.total_usd_m),
  };
  const valid = (
    validity.title_match
    && validity.table_found
    && validity.has_total_column
    && dailyRows.length >= 2
    && validity.latest_daily_row
    && validity.latest_total_is_number
  );

  await page.screenshot({ path: pngPath, fullPage: true });
  fs.writeFileSync(
    jsonPath,
    `${JSON.stringify(
      {
        schema_version: '1.0',
        source: SOURCE,
        url: URL,
        captured_at: new Date().toISOString(),
        capture_date: date,
        title: parsed.body_title || parsed.page_title,
        unit: 'US$m',
        columns,
        latest: latestWithTrend,
        previous,
        recent_rows: recent,
        recent_5d_net_usd_m: round1(
          recent.reduce((sum, row) => sum + (row.total_usd_m ?? 0), 0),
        ),
        rows: dailyRows,
        validity,
        interpretation_contract: {
          bullish_confirmation: 'price up with ETF inflow, stronger when inflow expands',
          bearish_confirmation: 'price down with ETF outflow, stronger when outflow expands',
          divergence: 'price and ETF flow direction disagree; treat rebound/drop health as weaker',
        },
      },
      null,
      2,
    )}\n`,
    'utf8',
  );

  console.log(`[farside_btc_etf] saved ${pngPath}`);
  console.log(`[farside_btc_etf] saved ${jsonPath}`);
  if (!valid) {
    console.log(`[farside_btc_etf] VALIDITY: FAIL ${JSON.stringify(validity)}`);
    exitCode = 2;
  } else {
    console.log(
      `[farside_btc_etf] VALIDITY: OK latest=${latest.date} total=${latest.total_usd_m} ${latest.direction}`,
    );
  }
} catch (error) {
  console.error(`[farside_btc_etf] ERROR: ${error.message}`);
  exitCode = 3;
} finally {
  await browser.close();
}

process.exit(exitCode);
