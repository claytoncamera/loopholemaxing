import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// Load the browser module without changing this static site's package model.
const code = readFileSync(new URL('../portfolio-ledger.js', import.meta.url), 'utf8');
const { ledgerSummary, refreshLedger } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const now = Date.parse('2026-09-28T22:00:00Z');
const sample = { generated_at: '2026-09-28T21:00:00Z', global: { n: 6515, display_ready: true, hit_rate: .5036, vs_majority_pp: -6.0169 } };
assert.match(ledgerSummary(sample, now).record, /6.0 percentage points behind/);
assert.equal(ledgerSummary(sample, now).count, '6,515');
assert.match(ledgerSummary({ ...sample, generated_at: '2026-09-26T21:00:00Z' }, now).time, /over 24 hours old/);
assert.match(ledgerSummary({ ...sample, global: { ...sample.global, vs_majority_pp: 2 } }, now).record, /ahead of/);
for (const bad of [null, {}, { ...sample, generated_at: '2026-09-29T00:00:00Z' }, { ...sample, generated_at: null }, ...['n', 'hit_rate', 'vs_majority_pp'].map(k => ({ ...sample, global: { ...sample.global, [k]: null } }))]) {
  assert.throws(() => ledgerSummary(bad, now));
}
const counts = Array.from({ length: 5 }, () => ({ textContent: 'old value' })); // includes marquee clone
const ids = { 'btc-record-summary': {}, 'btc-record-time': {} };
const doc = { querySelectorAll: () => counts, getElementById: id => ids[id] };
await refreshLedger(doc, async () => ({ ok: true, json: async () => sample }), now);
assert.ok(counts.every(el => el.textContent === '6,515'));
for (const fetcher of [async () => { throw new Error('offline'); }, async () => ({ ok: false }), async () => ({ ok: true, json: async () => ({}) })]) {
  await refreshLedger(doc, fetcher, now);
  assert.ok(counts.every(el => el.textContent === '—'));
  assert.match(ids['btc-record-summary'].textContent, /unavailable/);
}
const home = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
assert.equal((home.match(/data-btc-resolved>/g) || []).length, 4, 'all four public figure locations share the source');
assert.match(home, /type="module" src="\/portfolio-ledger.js"/);
assert.match(home, /hero-stat-val:not\(\[data-btc-resolved\]\)/, 'count-up must not overwrite fetched values');
console.log('PASS: portfolio ledger validity, baseline units, freshness, shared updates and unavailable states');
