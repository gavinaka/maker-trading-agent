import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isCompleteFarsideRow,
  selectCompleteFarsideRows,
} from '../tools/browser_capture/farside_row_policy.js';

test('all-dash fund row with placeholder total zero is incomplete', () => {
  const row = {
    date_iso: '2026-07-14',
    total_usd_m: 0,
    direction: 'flat',
    funds: { IBIT: null, FBTC: null, GBTC: null },
  };
  assert.equal(isCompleteFarsideRow(row), false);
});

test('latest complete row skips a newer unpublished placeholder row', () => {
  const complete = {
    date_iso: '2026-07-13',
    total_usd_m: -424.7,
    direction: 'outflow',
    funds: { IBIT: -185.5, FBTC: -245.6 },
  };
  const placeholder = {
    date_iso: '2026-07-14',
    total_usd_m: 0,
    direction: 'flat',
    funds: { IBIT: null, FBTC: null },
  };
  const selected = selectCompleteFarsideRows([placeholder, complete]);
  assert.equal(selected.latest.date_iso, '2026-07-13');
  assert.equal(selected.latestDisplayed.date_iso, '2026-07-14');
  assert.equal(selected.completeRows.length, 1);
});
