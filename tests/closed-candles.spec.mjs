// tests/closed-candles.spec.mjs
//
// Lightweight Node-only behavioural checks for the closed-candle drop logic.
// We don't load the whole HTML; we re-implement the helper exactly as it
// appears in btc-brain/index.html and assert the contract.
//
// Run:   node tests/closed-candles.spec.mjs
// Exit:  0 = pass, 1 = fail.

import assert from 'node:assert/strict';

function closedCandlesOnly(klines, opts) {
  if (!Array.isArray(klines) || klines.length < 2) return klines;
  if (opts && opts.includeLive) return klines.slice();
  return klines.slice(0, -1);
}

const sample = [
  // [openTime, open, high, low, close, volume]
  [1, '60000', '60500', '59800', '60200', '10'],
  [2, '60200', '60800', '60000', '60700', '12'],
  [3, '60700', '61000', '60400', '60900', '11'],
  [4, '60900', '61200', '60600', '61100', '8'],   // <-- in-progress live candle
];

const closed = closedCandlesOnly(sample);
assert.equal(closed.length, sample.length - 1, 'should drop the last (live) candle');
assert.equal(closed[closed.length - 1][4], '60900', 'last closed candle close mismatch');

const withLive = closedCandlesOnly(sample, { includeLive: true });
assert.equal(withLive.length, sample.length, 'includeLive should preserve all bars');

// Edge cases
assert.deepEqual(closedCandlesOnly(null), null, 'null passthrough');
assert.deepEqual(closedCandlesOnly([]),   [],   'empty passthrough');
assert.deepEqual(closedCandlesOnly([sample[0]]), [sample[0]], 'single-bar passthrough');

// CoinGecko fallback contract: passing null klines must NOT explode and must
// represent "indicators unavailable". We model the contract here as a
// boolean derivation; the real DOM check is in btc-brain-truth-scan.sh.
function indicatorsAvailable(h1, h4, h15) {
  const c = (k) => k ? closedCandlesOnly(k) : null;
  const h1c = c(h1), h4c = c(h4), h15c = c(h15);
  return !!(h1c && h4c && h15c && h1c.length && h4c.length && h15c.length);
}

assert.equal(indicatorsAvailable(null, null, null), false, 'null feed → indicators unavailable');
assert.equal(indicatorsAvailable(sample, sample, sample), true, 'full feed → indicators available');
assert.equal(indicatorsAvailable(sample, null, sample), false, 'partial feed → indicators unavailable');

console.log('closed-candles.spec: OK');
