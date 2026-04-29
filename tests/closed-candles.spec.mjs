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
//
// Updated contract (artifact fallback): the matrix renders REAL rows when
// at least one of {1h, 4h} is available — partial OHLC is preserved
// rather than wiped to all-STALE.
function indicatorsAvailable(h1, h4, h15, opts) {
  const isArt = opts && opts.artifact;
  const c = (k) => k ? closedCandlesOnly(k, { includeLive: !!isArt }) : null;
  const h1c = c(h1), h4c = c(h4), h15c = c(h15);
  return !!((h1c && h1c.length) || (h4c && h4c.length) || (h15c && h15c.length));
}

assert.equal(indicatorsAvailable(null, null, null), false, 'null feed → indicators unavailable');
assert.equal(indicatorsAvailable(sample, sample, sample), true, 'full feed → indicators available');
assert.equal(indicatorsAvailable(sample, null, sample), true, 'partial feed (1h+15m) → still available');
assert.equal(indicatorsAvailable(sample, sample, null), true, 'partial feed (1h+4h, no 15m) → still available — artifact path');

// Artifact → Binance-kline conversion contract. The backend candle
// objects must be flattened into the [openTime, o, h, l, c, v, closeTime, ...]
// tuple shape that the rest of the page expects.
function candlesToBinanceKlines(candleObjs) {
  if (!Array.isArray(candleObjs)) return null;
  return candleObjs.map((c) => ([
    c.open_time_ms,
    String(c.open), String(c.high), String(c.low), String(c.close),
    String(c.volume),
    c.close_time_ms,
    '0', 0, '0', '0', '0',
  ]));
}

const artifactCandles = [
  { open: 60000, high: 60500, low: 59800, close: 60200, volume: 10, open_time_ms: 1, close_time_ms: 2 },
  { open: 60200, high: 60800, low: 60000, close: 60700, volume: 12, open_time_ms: 2, close_time_ms: 3 },
  { open: 60700, high: 61000, low: 60400, close: 60900, volume: 11, open_time_ms: 3, close_time_ms: 4 },
];
const klArt = candlesToBinanceKlines(artifactCandles);
assert.equal(klArt.length, 3, 'kline conversion preserves candle count');
assert.equal(klArt[0][1], '60000', 'open mapped to index 1');
assert.equal(klArt[0][4], '60200', 'close mapped to index 4');
assert.equal(klArt[2][2], '61000', 'high mapped to index 2');

// In artifact mode the last bar is ALREADY closed — closedCandlesOnly with
// includeLive: true must preserve all bars so we don't drop a real one.
const closedArtifact = closedCandlesOnly(klArt, { includeLive: true });
assert.equal(closedArtifact.length, 3, 'artifact path keeps every closed bar');

// In live (Binance) mode the last bar is the in-progress candle and must
// be dropped from indicator inputs.
const closedLive = closedCandlesOnly(klArt);
assert.equal(closedLive.length, 2, 'live path drops the in-progress bar');

// Edge: empty artifact array survives conversion + drop.
assert.deepEqual(candlesToBinanceKlines([]), [], 'empty artifact → empty klines');
assert.deepEqual(candlesToBinanceKlines(null), null, 'null artifact → null klines');

// Stale 24h close → close % change derivation: when the live ticker
// is unavailable, the page falls back to deriving daily change from the
// first vs last close in the trailing 24 closed 1h candles. This is the
// authoritative formula — make sure it matches what we compute on the
// same raw data and that "all bars closed" is the precondition.
function dailyChangePctFromArtifact(klines, currentPrice) {
  if (!Array.isArray(klines) || klines.length < 24 || !isFinite(currentPrice)) return null;
  const ref = parseFloat(klines[klines.length - 24][1]); // open of -24h bar
  if (!isFinite(ref) || ref <= 0) return null;
  return ((currentPrice - ref) / ref) * 100;
}

const fakeSeries = [];
for (let i = 0; i < 30; i++) fakeSeries.push([i, '60000', '60100', '59900', String(60000 + i * 10), '5', i+1]);
const dpct = dailyChangePctFromArtifact(fakeSeries, 60290);
// Open at idx 6 = '60000' (first of trailing 24); current 60290 -> 0.4833...%
assert.ok(dpct != null && Math.abs(dpct - 0.483333333) < 1e-3, '24h % derived from closed-1h opens');

console.log('closed-candles.spec: OK');
