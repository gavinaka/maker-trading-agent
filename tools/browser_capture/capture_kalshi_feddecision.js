// One bounded Plan C acquisition from Kalshi public market-data API.
// Selection authority remains in capture_rate_expectation.js; this collector
// only writes a hash-bound raw artifact and never produces normalized metrics.

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

import {
  RATE_ARTIFACTS,
  hashRecord,
  sha256Canonical,
  writeJsonAtomic,
} from './rate_expectation_state.js';


const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const CONTRACT_PATH = path.join(
  ROOT,
  'data_sources',
  'rate_expectation_provider_contract.json',
);
const CONTRACT = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8'));


function localDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}


const OUT_DIR = path.join(ROOT, 'data_sources', 'inbox', localDate());
const RAW_PATH = path.resolve(
  String(process.env.KALSHI_FEDDECISION_RAW_PATH || path.join(
    OUT_DIR,
    RATE_ARTIFACTS.kalshiRaw,
  )),
);
const CAPTURE_RUN_ID = String(process.env.RATE_EXPECTATION_CAPTURE_RUN_ID || '').trim();
const CME_ATTEMPT_SHA256 = String(process.env.CME_FEDWATCH_ATTEMPT_SHA256 || '').trim();


function requireInvocationIdentity() {
  if (
    path.dirname(RAW_PATH) !== OUT_DIR
    || path.basename(RAW_PATH) !== RATE_ARTIFACTS.kalshiRaw
  ) {
    throw new Error('Kalshi raw artifact must stay in the current inbox');
  }
  if (!/^[0-9a-f-]{16,64}$/i.test(CAPTURE_RUN_ID)) {
    throw new Error('missing or invalid RATE_EXPECTATION_CAPTURE_RUN_ID');
  }
  if (!/^[0-9a-f]{64}$/.test(CME_ATTEMPT_SHA256)) {
    throw new Error('missing or invalid CME_FEDWATCH_ATTEMPT_SHA256');
  }
}


async function fetchResponse(url, { binary = false } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { accept: binary ? 'application/pdf' : 'application/json' },
      signal: controller.signal,
    });
    const retrievedAt = new Date().toISOString();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (binary) {
      const bytes = Buffer.from(await response.arrayBuffer());
      return {
        url,
        status_code: response.status,
        retrieved_at: retrievedAt,
        bytes,
      };
    }
    const wire = await response.text();
    const payload = JSON.parse(wire);
    return {
      url,
      status_code: response.status,
      retrieved_at: retrievedAt,
      body_sha256: sha256Canonical(payload),
      wire_sha256: crypto
        .createHash('sha256')
        .update(wire, 'utf8')
        .digest('hex'),
      payload,
    };
  } finally {
    clearTimeout(timeout);
  }
}


function mappingForMarket(market) {
  const strike = market?.custom_strike;
  if (!strike || typeof strike !== 'object' || Array.isArray(strike)) return null;
  return CONTRACT.kalshi.outcome_mappings.find((mapping) => (
    Object.keys(strike).length === 1
    && strike[mapping.custom_strike_key] === mapping.custom_strike_value
    && market.subtitle === mapping.subtitle
  )) ?? null;
}


function selectNextEvent(eventsPayload, nowMs) {
  const candidates = [];
  for (const event of (Array.isArray(eventsPayload?.events) ? eventsPayload.events : [])) {
    if (event?.series_ticker !== CONTRACT.kalshi.series_ticker) continue;
    const strikeMs = Date.parse(event.strike_date);
    if (!Number.isFinite(strikeMs)) {
      throw new Error('Kalshi FOMC event strike_date is invalid');
    }
    if (strikeMs > nowMs) candidates.push(event);
  }
  candidates.sort((left, right) => Date.parse(left.strike_date) - Date.parse(right.strike_date));
  if (!candidates.length) throw new Error('no future Kalshi FOMC event');
  const earliestStrike = Date.parse(candidates[0].strike_date);
  const earliest = candidates.filter(
    (event) => Date.parse(event.strike_date) === earliestStrike,
  );
  if (earliest.length !== 1) {
    throw new Error('ambiguous earliest Kalshi FOMC event');
  }
  const event = earliest[0];
  if (
    typeof event.event_ticker !== 'string'
    || !event.event_ticker
    || event.mutually_exclusive !== true
    || !Array.isArray(event.markets)
    || event.markets.length !== 5
  ) {
    throw new Error('earliest Kalshi FOMC event is structurally incomplete');
  }
  const outcomeMarketMap = {};
  let listedQuoteSum = 0;
  for (const market of event.markets) {
    const mapping = mappingForMarket(market);
    const bidText = market?.yes_bid_dollars;
    const askText = market?.yes_ask_dollars;
    const quotePattern = /^(?:0\.\d{4}|1\.0000)$/;
    const bid = Number(bidText);
    const ask = Number(askText);
    if (
      !mapping
      || outcomeMarketMap[mapping.outcome_key]
      || market.status !== 'active'
      || !Number.isFinite(Date.parse(market.close_time))
      || Date.parse(market.close_time) <= nowMs
      || (Object.hasOwn(market, 'is_provisional') && market.is_provisional !== false)
      || typeof market.ticker !== 'string'
      || !market.ticker.startsWith(`${event.event_ticker}-`)
      || typeof bidText !== 'string'
      || typeof askText !== 'string'
      || !quotePattern.test(bidText)
      || !quotePattern.test(askText)
      || !Number.isFinite(bid)
      || !Number.isFinite(ask)
      || bid < 0
      || ask > 1
      || bid > ask
    ) {
      throw new Error('earliest Kalshi FOMC event is structurally incomplete');
    }
    outcomeMarketMap[mapping.outcome_key] = market.ticker;
    listedQuoteSum += bid + ask;
  }
  const expectedOutcomes = CONTRACT.kalshi.outcome_mappings
    .map((mapping) => mapping.outcome_key)
    .sort();
  if (
    JSON.stringify(Object.keys(outcomeMarketMap).sort())
      !== JSON.stringify(expectedOutcomes)
  ) {
    throw new Error('earliest Kalshi FOMC event is structurally incomplete');
  }
  if (
    CONTRACT.kalshi.normalization.reject_all_listed_midpoints_zero === true
    && listedQuoteSum === 0
  ) {
    throw new Error('earliest Kalshi FOMC event has all-zero listed quotes');
  }
  return { event, outcomeMarketMap };
}


function validateSeries(seriesPayload) {
  const series = seriesPayload?.series;
  if (
    series?.ticker !== CONTRACT.kalshi.series_ticker
    || series.contract_terms_url !== CONTRACT.kalshi.contract_terms_url
    || !Array.isArray(series.settlement_sources)
    || !series.settlement_sources.some(
      (item) => item?.name === CONTRACT.kalshi.settlement_source_name,
    )
  ) {
    throw new Error('Kalshi series authority identity is invalid');
  }
}


function validateCandlesticks(candlesticks, marketTickers) {
  const payload = candlesticks.payload;
  if (
    !payload
    || !Array.isArray(payload.market_tickers)
    || !Array.isArray(payload.market_candlesticks)
    || payload.market_tickers.length !== marketTickers.length
    || payload.market_candlesticks.length !== marketTickers.length
    || JSON.stringify([...payload.market_tickers].sort())
      !== JSON.stringify([...marketTickers].sort())
    || payload.market_candlesticks.some((series) => !Array.isArray(series) || !series.length)
  ) {
    throw new Error('Kalshi candlestick response is structurally incomplete');
  }
}


async function main() {
  requireInvocationIdentity();
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const base = CONTRACT.kalshi.api_base_url.replace(/\/$/, '');
  const seriesTicker = encodeURIComponent(CONTRACT.kalshi.series_ticker);
  const seriesUrl = `${base}/series/${seriesTicker}`;
  const eventsUrl = `${base}/events?series_ticker=${seriesTicker}`
    + '&status=open&limit=200&with_nested_markets=true';
  const series = await fetchResponse(seriesUrl);
  validateSeries(series.payload);
  const events = await fetchResponse(eventsUrl);
  const nowMs = Date.now();
  const { event, outcomeMarketMap } = selectNextEvent(events.payload, nowMs);

  const observedTs = Math.floor(nowMs / 1000);
  // The normalizer seals raw.retrieved_at after all responses. A bounded future
  // end_ts keeps the requested range covering that seal time without shifting
  // the oldest required anchor forward.
  const endTs = observedTs + 300;
  const longestOffset = Math.max(
    ...Object.values(CONTRACT.kalshi.history.anchor_offsets_seconds),
  );
  const startTs = observedTs
    - longestOffset
    - CONTRACT.kalshi.history.max_anchor_age_seconds;
  const eventTicker = encodeURIComponent(event.event_ticker);
  const candlesticksUrl = `${base}/series/${seriesTicker}/events/${eventTicker}/candlesticks`
    + `?start_ts=${startTs}&end_ts=${endTs}`
    + `&period_interval=${CONTRACT.kalshi.history.period_interval_minutes}`;
  const candlesticks = await fetchResponse(candlesticksUrl);
  const marketTickers = event.markets.map((market) => market.ticker);
  validateCandlesticks(candlesticks, marketTickers);

  const terms = await fetchResponse(CONTRACT.kalshi.contract_terms_url, { binary: true });
  const termsSha256 = crypto
    .createHash('sha256')
    .update(terms.bytes)
    .digest('hex');
  if (termsSha256 !== CONTRACT.kalshi.contract_terms_sha256) {
    throw new Error('Kalshi contract terms hash differs from pinned authority');
  }

  const raw = {
    schema_version: CONTRACT.kalshi_raw_schema_version,
    capture_run_id: CAPTURE_RUN_ID,
    provider_id: CONTRACT.selection_modes.kalshi_plan_c_fallback.provider_id,
    series_ticker: CONTRACT.kalshi.series_ticker,
    retrieved_at: new Date().toISOString(),
    api_base_url: CONTRACT.kalshi.api_base_url,
    cme_attempt_sha256: CME_ATTEMPT_SHA256,
    selected_event: {
      event_ticker: event.event_ticker,
      strike_date: event.strike_date,
      mutually_exclusive: event.mutually_exclusive,
      market_tickers: marketTickers,
      outcome_market_map: outcomeMarketMap,
    },
    responses: {
      series,
      events,
      candlesticks,
    },
    contract_terms: {
      url: terms.url,
      status_code: terms.status_code,
      retrieved_at: terms.retrieved_at,
      bytes: terms.bytes.length,
      sha256: termsSha256,
      expected_sha256: CONTRACT.kalshi.contract_terms_sha256,
      matches_expected: true,
    },
    raw_sha256: '',
  };
  raw.raw_sha256 = hashRecord(raw, 'raw_sha256');
  writeJsonAtomic(RAW_PATH, raw);
  return 0;
}


const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = await main();
  } catch (error) {
    if (fs.existsSync(RAW_PATH)) fs.unlinkSync(RAW_PATH);
    console.error(`[kalshi-plan-c] ${error.message}`);
    process.exitCode = 2;
  }
}


export { selectNextEvent };
