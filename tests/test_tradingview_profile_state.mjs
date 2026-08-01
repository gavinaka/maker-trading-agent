import assert from 'node:assert/strict';
import test from 'node:test';

import {
  inspectPlatformProfileInPage,
  inspectPlatformProfileState,
} from '../tools/browser_capture/tradingview_profile_state.js';


function element(spec) {
  const button = spec.buttonLabel == null ? null : {
    isConnected: true,
    getClientRects: () => [1],
    getAttribute: (name) => (name === 'aria-label' ? spec.buttonLabel : null),
  };
  const item = {
    querySelectorAll: () => (button ? [button] : []),
  };
  return {
    textContent: spec.title,
    _hidden: spec.hidden === true,
    isConnected: true,
    getClientRects: () => [1],
    closest: () => item,
    parentElement: null,
  };
}


function installDom(inventory, readyState = 'complete') {
  globalThis.window = {
    getComputedStyle: (item) => ({
      display: item._hidden ? 'none' : 'block',
      visibility: item._hidden ? 'hidden' : 'visible',
    }),
  };
  globalThis.document = {
    readyState,
    querySelectorAll: () => inventory.map(element),
  };
}


function pageFor(inventories, { readyState = 'complete' } = {}) {
  let index = 0;
  return {
    evaluate: async (fn) => {
      const inventory = inventories[Math.min(index, inventories.length - 1)];
      index += 1;
      installDom(inventory, readyState);
      return fn();
    },
    waitForTimeout: async () => {},
  };
}


test('one DOM read never certifies absence, even with exact SMA20', () => {
  installDom([{ title: 'SMA 20' }]);
  assert.deepEqual(inspectPlatformProfileInPage(), {
    state: 'absence_candidate',
    certification_basis: 'unverified',
    inventory_signature: '["sma 20"]',
  });
});


test('only an exact stable SMA20 inventory can certify absence', async () => {
  const page = pageFor([
    [{ title: 'SMA 20' }],
    [{ title: 'SMA 20' }],
    [{ title: 'SMA 20' }],
  ]);
  assert.deepEqual(await inspectPlatformProfileState(page), {
    state: 'absent',
    certification_basis: 'certified_legend_inventory',
  });
});


test('SMA50, MA200, and period-free anchors fail closed to unknown', async () => {
  for (const title of [
    'SMA 50',
    'MA 200',
    'MA 20',
    'SMA',
    'MA',
    'Simple Moving Average 50',
    '移动平均线50',
    '移动平均线20',
  ]) {
    const page = pageFor([[{ title }]]);
    assert.deepEqual(
      await inspectPlatformProfileState(page),
      { state: 'unknown', certification_basis: 'unverified' },
      title,
    );
  }
});


test('a delayed profile title prevents certified absence', async () => {
  const page = pageFor([
    [{ title: 'SMA 20' }],
    [
      { title: 'SMA 20' },
      { title: 'VRVP', buttonLabel: '隐藏' },
    ],
  ]);
  assert.deepEqual(await inspectPlatformProfileState(page), {
    state: 'visible',
    certification_basis: 'profile_control',
  });
});


test('a connected but visually hidden profile title also fails closed', async () => {
  const page = pageFor([[
    { title: 'SMA 20' },
    { title: 'VRVP', buttonLabel: '隐藏', hidden: true },
  ]]);
  assert.deepEqual(await inspectPlatformProfileState(page), {
    state: 'unknown',
    certification_basis: 'unverified',
  });
});


test('a changing or incomplete legend inventory stays unknown', async () => {
  const changing = pageFor([
    [{ title: 'SMA 20' }],
    [{ title: 'SMA 20' }, { title: 'RSI' }],
    [{ title: 'SMA 20' }, { title: 'RSI' }],
  ]);
  assert.deepEqual(await inspectPlatformProfileState(changing), {
    state: 'unknown',
    certification_basis: 'unverified',
  });

  const loading = pageFor([[{ title: 'SMA 20' }]], { readyState: 'loading' });
  assert.deepEqual(await inspectPlatformProfileState(loading), {
    state: 'unknown',
    certification_basis: 'unverified',
  });
});
