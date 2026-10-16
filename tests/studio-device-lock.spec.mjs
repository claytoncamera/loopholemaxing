// Device-lock behavior only: no browser data, sync requests, or credential values.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../studio/index.html', import.meta.url), 'utf8');
assert.ok(!/default\s+passcode|DEFAULT_PASS_HASH/i.test(html), 'No shared device credential is shipped');
const code = html.slice(html.indexOf('function prepareDeviceLock(){'), html.indexOf('\nfunction lock()'));
assert.ok(code.includes('async function doUnlock'), 'Extract actual device-lock behavior');
function setup(entries = {}) {
  const stored = new Map(Object.entries(entries));
  const session = new Map();
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: '', textContent: '', classList: { add(){}, remove(){} } });
    return nodes.get(id);
  };
  let enters = 0;
  const context = vm.createContext({
    $: node, document: { querySelector: node },
    localStorage: { getItem: key => stored.get(key) || null, setItem: (key, value) => stored.set(key, value) },
    sessionStorage: { setItem: (key, value) => session.set(key, value) },
    sha256: async value => 'hashed:' + value, enterApp: () => enters++,
  });
  vm.runInContext(code, context);
  return { context, node, stored, session, enters: () => enters };
}
const first = setup({ studio_sync_code: 'separately-provided-fixture' });
first.context.prepareDeviceLock();
assert.equal(first.node('gate-confirm-row').hidden, false);
assert.equal(first.node('gate-pass').autocomplete, 'new-password');
first.node('gate-pass').value = 'new-device-test';
first.node('gate-confirm').value = 'different-device-test';
await first.context.doUnlock({ preventDefault(){} });
assert.equal(first.enters(), 0, 'Mismatch does not create a lock or enter');
assert.ok(!first.stored.has('studio_pass_hash'));
first.node('gate-confirm').value = 'new-device-test';
await first.context.doUnlock({ preventDefault(){} });
assert.equal(first.enters(), 1);
assert.equal(first.stored.get('studio_pass_hash'), 'hashed:new-device-test');
assert.equal(first.stored.get('studio_sync_code'), 'separately-provided-fixture', 'First run preserves cloud sync identity');
const existing = setup({ studio_pass_hash: 'hashed:owner-test', studio_sync_code: 'separate-fixture' });
existing.context.prepareDeviceLock();
assert.equal(existing.node('gate-confirm-row').hidden, true);
existing.node('gate-pass').value = 'incorrect-test';
await existing.context.doUnlock({ preventDefault(){} });
assert.equal(existing.enters(), 0);
existing.node('gate-pass').value = 'owner-test';
await existing.context.doUnlock({ preventDefault(){} });
assert.equal(existing.enters(), 1);
assert.equal(existing.stored.get('studio_pass_hash'), 'hashed:owner-test', 'Existing hash remains unchanged');
assert.equal(existing.stored.get('studio_sync_code'), 'separate-fixture');
assert.ok(html.includes("if(localStorage.getItem('studio_pass_hash') && sessionStorage.getItem('studio_unlocked')==='1')"),
          'A prior convenience session alone cannot skip first-run setup');
console.log('OK: Studio creates a local lock, preserves existing identity, rejects mismatches, ships no default');
