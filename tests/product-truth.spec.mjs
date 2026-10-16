// Public offer/capability regression guard. Static only: no form submissions,
// external requests, daemon execution or payment calls.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const ultron = read('ultron/index.html');
const visible = ultron.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
const creations = JSON.parse(read('agora/data/creations.json'));

assert.doesNotMatch(ultron, /14[-\s]day|signed trial token|send my trial token|can't go rogue|clayton@moneymakingsolutionsai\.com/i,
  'ULTRON must not promise an unsupported hosted trial, token or absolute safety');
assert.doesNotMatch(ultron, /<(?:a|button)\b[^>]*>\s*Start (?:your |a )?(?:free )?trial/i);
assert.doesNotMatch(visible, /\$(?:19|99)\b|most popular/i,
  'unavailable hosted plans must not read as purchasable monthly plans');
assert.match(visible, /no active paid plans, checkout or trial is available/i);
assert.match(visible, /Hosted Pro · Planned/);
assert.match(visible, /Team · Planned/);
assert.match(visible, /proposed capabilities/i);
assert.match(visible, /no launch date is promised/i);
assert.match(ultron, /href="#waitlist" class="btn-cyan">Join the hosted waitlist/);
assert.match(ultron, /id="waitlist"/);
assert.match(visible, /sample proposals/i);
assert.match(visible, /do not execute live tools, trades or deployments/i);
assert.match(ultron, /title="ULTRON Command Deck — sample proposals"/);
assert.match(visible, /local prototype with source access by request/i);
assert.match(visible, /public source download is not currently available/i);
assert.match(ultron, /mailto:clayton\.camera@icloud\.com\?subject=ULTRON%20source%20access/);
assert.doesNotMatch(ultron, /href="https:\/\/github\.com\/claytoncamera\/ultron[^"]*"/,
  'the private repository must not be offered as an accessible public download');
assert.doesNotMatch(visible, /clone on github|open source|fork freely|self-host now/i);
assert.doesNotMatch(ultron, /href="[^\"]*(?:buy\.stripe\.com|checkout\.stripe\.com|paypal\.com)/i,
  'hosted-interest signup must not imply checkout');
assert.match(ultron, /mailto:clayton\.camera@icloud\.com\?subject=ULTRON/);
assert.match(ultron, /wireCaptureForm\(\{ form: 'trialForm', input: 'trialEmail', okEl: 'trialOk',\s+list: 'ULTRON Pro Waitlist', note: 'Interest in planned hosted ULTRON options; waitlist only' \}\)/,
  'preserve capture IDs, contract and existing CRM list; describe new signups truthfully');
assert.match(ultron, /src="\/capture\.js"/);
assert.match(ultron, /"@id": "https:\/\/claytoncamera\.com\/#person"/);
assert.match(ultron, /<link rel="canonical" href="https:\/\/loopholemaxing\.com\/ultron\/">/);
for (const [, hash] of ultron.matchAll(/href="#([^"]+)"/g)) {
  assert.ok(ultron.includes(`id="${hash}"`), `local ULTRON link #${hash} resolves`);
}
console.log('OK: ULTRON offers are interest-only; sample UI, source access by request and capture contract remain explicit');

const orbit = creations.wings.find(wing => wing.slug === 'orbitroute');
assert.ok(orbit, 'OrbitRoute remains in the public registry');
assert.doesNotMatch(JSON.stringify(orbit), /\b35\s*%|cost savings|savings (?:vs\.?|versus)\s*(?:AWS|GCP|Azure)|fraction of hyperscaler/i,
  'Agora must not reintroduce the wrong-signed orbital savings pitch');
assert.match(orbit.summary, /model|simulat/i,
  'the public registry must distinguish modeled orbital capability');
for (const wing of [...creations.wings, ...(creations.engagement || [])]) {
  if (!wing.url) continue;
  const destination = new URL(wing.url, 'https://loopholemaxing.com');
  assert.doesNotMatch(destination.pathname, /^\/(?:army-link|studio|analytics-hub|creation-command-center|business-anywhere)(?:\/|$)/i,
    `${wing.slug} must not expose a private owner surface through the public registry`);
  assert.doesNotMatch(destination.hostname, /(?:^|[.-])(?:hubapi|analytics-hub|rclx)(?:[.-]|$)/i,
    `${wing.slug} must not link to a private API or owner dashboard`);
}
console.log('OK: Agora excludes wrong-signed orbital savings and private owner destinations');
