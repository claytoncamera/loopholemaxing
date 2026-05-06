// tests/agora-static.spec.mjs
// Static checks for the Agora Alpha (Library of Minds) public surface.
// - catalog.json parses, has expected priority philosophers, every work has a source
// - sources.json (ledger) parses and references real work_ids
// - excerpt files exist and are non-trivial
// - homepage links the agora card
// - agora/index.html references the catalog and ledger

import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

let failed = 0;
function ok(label) { console.log(`  OK: ${label}`); }
function fail(label, msg) { failed++; console.log(`  FAIL: ${label} — ${msg}`); }
function read(p) { return readFileSync(join(root, p), 'utf8'); }

console.log('== Agora static validation ==');

// 1. Catalog JSON parses and is well-formed
let catalog;
try {
  catalog = JSON.parse(read('agora/data/catalog.json'));
  ok('catalog.json parses');
} catch (e) {
  fail('catalog.json parses', e.message);
}

if (catalog) {
  if (!Array.isArray(catalog.philosophers) || catalog.philosophers.length < 5) {
    fail('catalog.philosophers length', `expected >= 5, got ${catalog.philosophers && catalog.philosophers.length}`);
  } else {
    ok(`catalog has ${catalog.philosophers.length} philosophers`);
  }

  // Required priority slugs
  const required = ['plato', 'aristotle', 'socrates', 'heraclitus', 'parmenides'];
  const haveSlugs = new Set(catalog.philosophers.map(p => p.slug));
  for (const slug of required) {
    if (haveSlugs.has(slug)) ok(`catalog includes ${slug}`);
    else fail('catalog includes ' + slug, 'missing');
  }

  // Each philosopher has at least one work and each work has at least one source URL
  for (const p of catalog.philosophers) {
    if (!Array.isArray(p.works) || p.works.length === 0) {
      fail(`works for ${p.slug}`, 'empty');
      continue;
    }
    for (const w of p.works) {
      if (!Array.isArray(w.sources) || w.sources.length === 0) {
        fail(`work ${w.id} sources`, 'empty');
      } else {
        for (const s of w.sources) {
          if (!/^https?:\/\//.test(s.url || '')) {
            fail(`work ${w.id} source url`, 'not http(s)');
          }
        }
      }
    }
  }
  ok('every work has at least one source URL (or failures listed above)');

  // Excerpt files referenced in catalog actually exist and are non-trivial
  let excerptCount = 0;
  for (const p of catalog.philosophers) {
    for (const w of (p.works || [])) {
      if (!w.excerpt_file) continue;
      excerptCount++;
      const txt = existsSync(join(root, w.excerpt_file)) ? read(w.excerpt_file) : '';
      if (txt.length < 400) fail(`excerpt ${w.excerpt_file}`, `< 400 chars (${txt.length})`);
    }
  }
  if (excerptCount < 3) fail('excerpt count', `expected >= 3, got ${excerptCount}`);
  else ok(`${excerptCount} excerpts present and non-trivial`);
}

// 2. Source ledger
let ledger;
try {
  ledger = JSON.parse(read('agora/ledger/sources.json'));
  ok('ledger sources.json parses');
} catch (e) {
  fail('ledger parses', e.message);
}
if (ledger && catalog) {
  const allWorkIds = new Set();
  for (const p of catalog.philosophers) for (const w of (p.works || [])) allWorkIds.add(w.id);
  for (const e of (ledger.entries || [])) {
    if (!allWorkIds.has(e.work_id)) fail(`ledger entry ${e.work_id}`, 'no matching work in catalog');
  }
  ok(`ledger has ${ledger.entries.length} entries, all reference real catalog works (or failures listed above)`);
}

// 3. Homepage integration
const home = read('index.html');
if (home.includes('href="/agora/"') && home.includes('Agora') && home.includes('Library of Minds')) {
  ok('homepage links to /agora/ with Library of Minds branding');
} else {
  fail('homepage agora link', 'card or link missing');
}

// 4. Agora page
const agora = read('agora/index.html');
if (agora.includes('data/catalog.json') && agora.includes('ledger/sources.json')) {
  ok('agora/index.html fetches catalog + ledger');
} else {
  fail('agora page wiring', 'fetch references missing');
}
if (agora.includes('Agora Alpha') && agora.includes('Library of Minds')) {
  ok('agora page has product naming');
} else {
  fail('agora page branding', 'product name missing');
}

// 5. Creation Engine / Atlas section
const engineMarkers = [
  'creation-engine',
  'creation-monetization',
  'creation-roadmap',
  'creation-trust',
  'data/creations.json'
];
let engineMissing = engineMarkers.filter(m => !agora.includes(m));
if (engineMissing.length === 0) {
  ok('agora page has Creation Engine sections (engine, monetization, roadmap, trust) wired to creations.json');
} else {
  fail('agora Creation Engine section', `missing markers: ${engineMissing.join(', ')}`);
}

// 6. Creation registry data file
let creations;
try {
  creations = JSON.parse(read('agora/data/creations.json'));
  ok('creations.json parses');
} catch (e) {
  fail('creations.json parses', e.message);
}
if (creations) {
  // Constellation must include Agora plus the other preserved creations
  if (!Array.isArray(creations.wings) || creations.wings.length < 6) {
    fail('creations.wings length', `expected >= 6, got ${creations.wings && creations.wings.length}`);
  } else {
    ok(`constellation has ${creations.wings.length} creations`);
  }
  const slugs = new Set((creations.wings || []).map(w => w.slug));
  for (const required of ['agora', 'btc-brain', 'uae']) {
    if (slugs.has(required)) ok(`constellation includes ${required}`);
    else fail('constellation includes ' + required, 'missing — existing creation must be preserved');
  }

  // Monetization offers — non-payment primitives required by the brief
  const offers = (creations.monetization && creations.monetization.offers) || [];
  const offerIds = new Set(offers.map(o => o.id));
  for (const expected of ['founding_circle_interest', 'api_access_interest', 'dossier_interest', 'private_archive_interest']) {
    if (offerIds.has(expected)) ok(`monetization offer ${expected} present`);
    else fail('monetization offer ' + expected, 'missing');
  }

  // No real-payment processing language allowed in the data
  const blob = JSON.stringify(creations).toLowerCase();
  const forbidden = ['stripe', 'checkout.session', 'paypal', 'card_number', 'cvv'];
  const hits = forbidden.filter(f => blob.includes(f));
  if (hits.length === 0) ok('no real-payment processors referenced in creations.json');
  else fail('creations.json payment language', `forbidden tokens: ${hits.join(', ')}`);

  // Roadmap + trust
  if (Array.isArray(creations.roadmap) && creations.roadmap.length >= 3) ok(`roadmap has ${creations.roadmap.length} phases`);
  else fail('roadmap', 'expected >= 3 phases');
  if (creations.trust && Array.isArray(creations.trust.promises) && creations.trust.promises.length >= 3) {
    ok(`trust bar has ${creations.trust.promises.length} promises`);
  } else {
    fail('trust bar', 'expected >= 3 promises');
  }
}

console.log(failed === 0 ? '\nAGORA STATIC: PASS' : `\nAGORA STATIC: FAIL (${failed} issue${failed===1?'':'s'})`);
process.exit(failed === 0 ? 0 : 1);
