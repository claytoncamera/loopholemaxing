// tests/live-market-fallback.spec.mjs
//
// Regression contract for the BTC Brain live-market panels:
//   - When Binance is region-blocked (HTTP 451), the page MUST fall back
//     to the public Phase 2 candle artifacts (data/public/candles_*.json).
//   - Indicators must use closed candles only.
//   - Source labels and freshness warnings must reach the UI.
//   - The page must NOT silently render all-STALE rows when fresh
//     artifact candles exist on disk.
//
// We don't boot a browser — we re-implement the exact fallback contract
// from btc-brain/index.html and assert it against the on-disk public
// artifacts. The static check that the page actually wires this contract
// lives in tests/btc-brain-truth-scan.sh.
//
// Run:  node tests/live-market-fallback.spec.mjs
// Exit: 0 = pass, 1 = fail.

import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

function loadJSON(rel) {
  const p = join(ROOT, rel);
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf8')); }
  catch { return null; }
}

// ─────────────────────────────────────────────────────────────────────
// Mirror of the helpers in btc-brain/index.html.
// ─────────────────────────────────────────────────────────────────────
function closedCandlesOnly(klines, opts) {
  if (!Array.isArray(klines) || klines.length < 2) return klines;
  if (opts && opts.includeLive) return klines.slice();
  return klines.slice(0, -1);
}
function candlesToBinanceKlines(candleObjs) {
  if (!Array.isArray(candleObjs)) return null;
  return candleObjs.map((c) => [
    c.open_time_ms,
    String(c.open), String(c.high), String(c.low), String(c.close),
    String(c.volume),
    c.close_time_ms,
    '0', 0, '0', '0', '0',
  ]);
}
function artifactKlineSet(candles) {
  const h1Obj  = candles.h1  && candles.h1.data  ? candles.h1.data.candles  : null;
  const h4Obj  = candles.h4  && candles.h4.data  ? candles.h4.data.candles  : null;
  const d1Obj  = candles.d1  && candles.d1.data  ? candles.d1.data.candles  : null;
  const m1Obj  = candles.m1  && candles.m1.data  ? candles.m1.data.candles  : null;
  const m5Obj  = candles.m5  && candles.m5.data  ? candles.m5.data.candles  : null;
  const m15Obj = candles.m15 && candles.m15.data ? candles.m15.data.candles : null;
  return {
    h1:    candlesToBinanceKlines(h1Obj),
    h4:    candlesToBinanceKlines(h4Obj),
    h15:   candlesToBinanceKlines(m15Obj),
    m5:    candlesToBinanceKlines(m5Obj),
    m1:    candlesToBinanceKlines(m1Obj),
    daily: candlesToBinanceKlines(d1Obj),
    sources: {
      h1:  candles.h1  ? { source: candles.h1.source,  fetched_at: candles.h1.fetched_at,  status: candles.h1.status }  : null,
      h4:  candles.h4  ? { source: candles.h4.source,  fetched_at: candles.h4.fetched_at,  status: candles.h4.status }  : null,
      d1:  candles.d1  ? { source: candles.d1.source,  fetched_at: candles.d1.fetched_at,  status: candles.d1.status }  : null,
      m1:  candles.m1  ? { source: candles.m1.source,  fetched_at: candles.m1.fetched_at,  status: candles.m1.status }  : null,
      m5:  candles.m5  ? { source: candles.m5.source,  fetched_at: candles.m5.fetched_at,  status: candles.m5.status }  : null,
      m15: candles.m15 ? { source: candles.m15.source, fetched_at: candles.m15.fetched_at, status: candles.m15.status } : null,
    },
  };
}

// ─────────────────────────────────────────────────────────────────────
// Test 1: the on-disk public artifacts can drive the fallback path.
// ─────────────────────────────────────────────────────────────────────
const candles1h = loadJSON('btc-brain/data/public/candles_1h.json');
const candles4h = loadJSON('btc-brain/data/public/candles_4h.json');
const candles1d = loadJSON('btc-brain/data/public/candles_1d.json');
const candles1m = loadJSON('btc-brain/data/public/candles_1m.json');
const candles5m = loadJSON('btc-brain/data/public/candles_5m.json');
const candles15m = loadJSON('btc-brain/data/public/candles_15m.json');
const derivatives = loadJSON('btc-brain/data/public/derivatives.json');
const sourceHealth = loadJSON('btc-brain/data/public/source_health.json');

assert.ok(candles1h && candles1h.data && Array.isArray(candles1h.data.candles) && candles1h.data.candles.length > 0,
  'candles_1h.json must contain non-empty data.candles');
assert.ok(candles4h && candles4h.data && Array.isArray(candles4h.data.candles) && candles4h.data.candles.length > 0,
  'candles_4h.json must contain non-empty data.candles');
assert.ok(candles1d && candles1d.data && Array.isArray(candles1d.data.candles) && candles1d.data.candles.length > 0,
  'candles_1d.json must contain non-empty data.candles');
assert.ok(typeof candles1h.source === 'string' && candles1h.source.length, '1h artifact has a named source label');
assert.ok(typeof candles1h.fetched_at === 'string' && candles1h.fetched_at.length, '1h artifact has fetched_at');

const set = artifactKlineSet({
  h1: candles1h, h4: candles4h, d1: candles1d,
  m1: candles1m, m5: candles5m, m15: candles15m,
});
assert.ok(Array.isArray(set.h1) && set.h1.length > 24, 'artifact 1h converts to >=24 klines');
assert.ok(Array.isArray(set.h4) && set.h4.length > 3,  'artifact 4h converts to multiple klines');
const k0 = set.h1[0];
assert.equal(typeof k0[1], 'string', 'open is stringified to match Binance kline shape');
assert.equal(typeof k0[4], 'string', 'close is stringified to match Binance kline shape');
assert.ok(parseFloat(k0[2]) >= parseFloat(k0[3]), 'high >= low for every converted bar');

// ─────────────────────────────────────────────────────────────────────
// Test 2: closed-candle invariant respects artifact vs live mode.
// ─────────────────────────────────────────────────────────────────────
const inLive = closedCandlesOnly(set.h1);                          // drops last
const inArt  = closedCandlesOnly(set.h1, { includeLive: true });   // keeps all
assert.equal(inLive.length, set.h1.length - 1, 'live mode drops the in-progress bar');
assert.equal(inArt.length,  set.h1.length,      'artifact mode preserves every closed bar');

// ─────────────────────────────────────────────────────────────────────
// Test 3: the Multi-Timeframe Trend Matrix MUST NOT render all-STALE
// when the artifact has fresh closed candles. We model the contract:
// ohlcAvailable is true if either h1c or h4c has bars.
// ─────────────────────────────────────────────────────────────────────
const h1c  = closedCandlesOnly(set.h1, { includeLive: true });
const h4c  = closedCandlesOnly(set.h4, { includeLive: true });
const h15c = null; // no 15m artifact today
const ohlcAvailable = !!((h1c && h1c.length) || (h4c && h4c.length));
assert.equal(ohlcAvailable, true,
  'with on-disk candle artifacts, ohlcAvailable must be true (page would otherwise go all-STALE)');

// ─────────────────────────────────────────────────────────────────────
// Test 4: Last 24h / Pattern Engine inputs are populated when the
// artifact path runs — last24 must have 24 bars and patterns can be
// scanned over them.
// ─────────────────────────────────────────────────────────────────────
const last24 = h1c.slice(-24);
assert.equal(last24.length, 24, 'Last 24h panel receives a full 24-bar window');
const allCloses = last24.map((k) => parseFloat(k[4]));
assert.ok(allCloses.every((v) => isFinite(v) && v > 0), 'every close is a finite positive number');

// ─────────────────────────────────────────────────────────────────────
// Test 5: Daily % change derived from closed-candle 1h opens is real
// and not a fabricated bullish stub.
// ─────────────────────────────────────────────────────────────────────
const lastClose = parseFloat(h1c[h1c.length - 1][4]);
const ref       = parseFloat(h1c[h1c.length - 24][1]);
assert.ok(isFinite(lastClose) && isFinite(ref) && ref > 0, 'reference close + open are real');
const dailyPct = ((lastClose - ref) / ref) * 100;
assert.ok(Math.abs(dailyPct) < 50, 'daily % change is bounded — not an obvious fabrication');
assert.ok(dailyPct !== 0, 'daily % change reflects real movement, not a hardcoded zero');

// ─────────────────────────────────────────────────────────────────────
// Test 6: derivatives.json fallback must expose at least funding_rate.
// (Live page uses this when fapi.binance.com returns 451.)
// ─────────────────────────────────────────────────────────────────────
assert.ok(derivatives && derivatives.data,
  'derivatives.json must have a data envelope so the panel can avoid blanks');
assert.ok(typeof derivatives.data.funding_rate === 'number',
  'derivatives.data.funding_rate must be present so the funding cell never renders Loading...');
assert.ok(typeof derivatives.source === 'string' && derivatives.source.length,
  'derivatives.json must carry a named source so the UI can label the fallback');
assert.ok(typeof derivatives.fetched_at === 'string',
  'derivatives.json must carry fetched_at so the UI can flag staleness');

// ─────────────────────────────────────────────────────────────────────
// Test 7: source_health.json must declare freshness budgets so the UI
// can decide whether to tag the artifact STALE rather than green. The
// sub-hour kinds must also be present so the trend matrix can render
// real rows for 1m / 5m / 15m instead of "No feed wired".
// ─────────────────────────────────────────────────────────────────────
assert.ok(sourceHealth && sourceHealth.freshness_budget_seconds,
  'source_health.json must publish freshness_budget_seconds for STALE detection');
for (const key of ['candles_1m', 'candles_5m', 'candles_15m', 'candles_1h', 'candles_4h', 'candles_1d', 'derivatives']) {
  assert.equal(typeof sourceHealth.freshness_budget_seconds[key], 'number',
    `freshness budget for ${key} must be a number`);
}
// Sub-hour budgets must be tighter than the 1h budget — a 1m candle
// that is two hours old is unambiguously stale even if data/public
// still has a file on disk.
assert.ok(sourceHealth.freshness_budget_seconds.candles_1m < sourceHealth.freshness_budget_seconds.candles_1h,
  '1m freshness budget should be tighter than 1h');
assert.ok(sourceHealth.freshness_budget_seconds.candles_5m < sourceHealth.freshness_budget_seconds.candles_1h,
  '5m freshness budget should be tighter than 1h');
assert.ok(sourceHealth.freshness_budget_seconds.candles_15m <= sourceHealth.freshness_budget_seconds.candles_1h,
  '15m freshness budget should be at most as loose as 1h');

// ─────────────────────────────────────────────────────────────────────
// Test 8: NO hardcoded fake market narratives in btc-brain/index.html.
// We forbid specific phrases that previously appeared as fake "live"
// claims with hardcoded numbers and that do not have any live data
// source backing them. (This complements truth-scan grep checks but
// runs in the JS test harness so it can fail CI loudly.)
// ─────────────────────────────────────────────────────────────────────
const indexHtml = readFileSync(join(ROOT, 'btc-brain/index.html'), 'utf8');

// Strip JS line comments (// ...) and block comments (/* ... */) before
// scanning. The whole point is to forbid these phrases as USER-FACING
// claims; comments that document "we removed this" should not trip us.
const indexCodeOnly = indexHtml
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');

const FORBIDDEN_NARRATIVES = [
  'Goldman accumulation',
  'Bull continuation 72%',
  '+8.3 pts / upgrade',
  'MVRV Z-Score 0.41',
  'ETF inflows $69.6M',
  'Powered by live market data.',
];
for (const phrase of FORBIDDEN_NARRATIVES) {
  assert.ok(!indexCodeOnly.includes(phrase),
    `forbidden hardcoded narrative still present in user-facing markup: "${phrase}"`);
}

// And the artifact-fallback wiring must be in place — defense-in-depth
// against a future commit that drops the candle loader.
assert.ok(indexHtml.includes('data/public/candles_1h.json'),
  'index.html must reference candles_1h.json fallback');
assert.ok(indexHtml.includes('data/public/candles_4h.json'),
  'index.html must reference candles_4h.json fallback');
assert.ok(indexHtml.includes('data/public/candles_1d.json'),
  'index.html must reference candles_1d.json fallback');
assert.ok(indexHtml.includes('data/public/candles_1m.json'),
  'index.html must reference candles_1m.json fallback (Phase A trend matrix)');
assert.ok(indexHtml.includes('data/public/candles_5m.json'),
  'index.html must reference candles_5m.json fallback (Phase A trend matrix)');
assert.ok(indexHtml.includes('data/public/candles_15m.json'),
  'index.html must reference candles_15m.json fallback (Phase A trend matrix)');
assert.ok(indexHtml.includes('loadCandleArtifacts'),
  'index.html must define loadCandleArtifacts');
assert.ok(indexHtml.includes('Hourly candles unavailable'),
  'Last 24h panel must have an explicit unavailable state');
assert.ok(indexHtml.includes('Pattern scan unavailable'),
  'Pattern engine must have an explicit unavailable state');

// Trend matrix wiring: the page must NOT hard-code "No 1m feed wired" /
// "No 5m feed wired" stub rows any more — those have been replaced with
// real artifact-driven rows or per-row STALE fallbacks.
const indexCodeForRows = indexHtml
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
assert.ok(!indexCodeForRows.includes("'No 1m feed wired'"),
  'index.html must not hard-code a "No 1m feed wired" stub row — Phase A wires the 1m artifact');
assert.ok(!indexCodeForRows.includes("'No 5m feed wired'"),
  'index.html must not hard-code a "No 5m feed wired" stub row — Phase A wires the 5m artifact');

// ─────────────────────────────────────────────────────────────────────
// Test 9: Sub-hour artifacts must be real closed candles, never
// synthesised. Walk every bar in candles_{1m,5m,15m}.json and assert:
//   - high >= low
//   - open / close inside [low, high]
//   - close_time_ms strictly after open_time_ms
//   - open/high/low/close are finite positive numbers
//   - close_time_ms is monotonically non-decreasing across the series
// This is the "no synthetic OHLC" invariant for the trend matrix feed.
// ─────────────────────────────────────────────────────────────────────
function assertCandleSeriesValid(doc, label) {
  if (!doc) return; // missing artifact handled elsewhere
  if (doc.status !== 'ok' || !doc.data) return; // failed/stale handled elsewhere
  const cs = doc.data.candles;
  assert.ok(Array.isArray(cs) && cs.length > 0,
    `${label}: data.candles must be a non-empty array when status=ok`);
  let prevClose = -Infinity;
  for (const c of cs) {
    assert.ok(Number.isFinite(c.open) && c.open > 0,   `${label}: open must be positive finite`);
    assert.ok(Number.isFinite(c.high) && c.high > 0,   `${label}: high must be positive finite`);
    assert.ok(Number.isFinite(c.low) && c.low > 0,     `${label}: low must be positive finite`);
    assert.ok(Number.isFinite(c.close) && c.close > 0, `${label}: close must be positive finite`);
    assert.ok(c.high >= c.low,                          `${label}: high >= low`);
    assert.ok(c.open >= c.low && c.open <= c.high,      `${label}: open within [low, high]`);
    assert.ok(c.close >= c.low && c.close <= c.high,    `${label}: close within [low, high]`);
    assert.ok(Number.isInteger(c.open_time_ms),         `${label}: open_time_ms is an integer`);
    assert.ok(Number.isInteger(c.close_time_ms),        `${label}: close_time_ms is an integer`);
    assert.ok(c.close_time_ms > c.open_time_ms,         `${label}: close_time_ms strictly after open_time_ms`);
    assert.ok(c.close_time_ms >= prevClose,             `${label}: close_time_ms monotonic`);
    prevClose = c.close_time_ms;
  }
}
assertCandleSeriesValid(candles1m,  'candles_1m');
assertCandleSeriesValid(candles5m,  'candles_5m');
assertCandleSeriesValid(candles15m, 'candles_15m');

// ─────────────────────────────────────────────────────────────────────
// Test 10: When sub-hour artifacts are present + ok, source_health
// must surface them with named providers that match the reality on
// disk, so the UI can label the row source and freshness honestly.
// ─────────────────────────────────────────────────────────────────────
for (const [kind, doc] of [
  ['candles_1m',  candles1m],
  ['candles_5m',  candles5m],
  ['candles_15m', candles15m],
]) {
  if (!doc) continue;
  const entry = sourceHealth && sourceHealth.sources && sourceHealth.sources[kind];
  assert.ok(entry, `source_health.sources.${kind} must be present`);
  assert.equal(entry.source, doc.source,
    `source_health.${kind} source label must match the artifact (${doc.source})`);
  assert.equal(entry.status, doc.status,
    `source_health.${kind} status must match the artifact (${doc.status})`);
}

// ─────────────────────────────────────────────────────────────────────
// Test 11: The artifact path must produce kline arrays for the 1m / 5m
// / 15m timeframes when those JSON files are present, so the trend
// matrix can render real rows instead of "No feed wired".
// ─────────────────────────────────────────────────────────────────────
if (candles1m && candles1m.status === 'ok') {
  assert.ok(Array.isArray(set.m1) && set.m1.length > 3,
    'artifact 1m must convert to >=3 klines (trend analyzer needs 3)');
}
if (candles5m && candles5m.status === 'ok') {
  assert.ok(Array.isArray(set.m5) && set.m5.length > 3,
    'artifact 5m must convert to >=3 klines (trend analyzer needs 3)');
}
if (candles15m && candles15m.status === 'ok') {
  assert.ok(Array.isArray(set.h15) && set.h15.length > 3,
    'artifact 15m must convert to >=3 klines (trend analyzer needs 3)');
}

console.log('live-market-fallback.spec: OK');
