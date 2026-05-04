#!/usr/bin/env node
/**
 * tests/army-link-server-mode.spec.mjs
 *
 * Validates the Phase B contract for /army-link/index.html:
 *
 *   1. The page declares a configurable Hub API origin/path with the documented
 *      defaults (https://hubapi.loopholemaxing.com + /api/v1/army-link/unlock).
 *   2. The page exposes a server-mode auth indicator that can read "soft" /
 *      "server" / "probing" — the UI tells the truth about which mode is active.
 *   3. The unlock script POSTs to the server endpoint when in server mode and
 *      consumes a server-returned Nexus URL only on { ok: true } responses.
 *   4. The script fails CLOSED when the server is reachable but rejects the
 *      passkey: it does not silently fall back to the soft path after submitting
 *      the plaintext.
 *   5. No plaintext passkey appears in the bundle (sliding-window scan over the
 *      page content; we never embed plaintext in this script).
 *   6. The "no trading / no execution" disclaimers are intact.
 *
 * Run: node tests/army-link-server-mode.spec.mjs
 *
 * Exit 0 = pass, exit 1 = at least one assertion failed.
 */

import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import crypto from "node:crypto";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const GATE_PATH = path.join(ROOT, "army-link", "index.html");

const EXPECTED_DIGEST =
  "c93bb622e9a68df1e5c5540a25231246f31dfa8e911d7983adda1ed6dab35d8d";
const PASSKEY_LEN = 17;

let failures = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`  ok   ${name}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}${detail ? "  — " + detail : ""}`);
  }
}

console.log("== army-link server-mode contract ==");

if (!fs.existsSync(GATE_PATH)) {
  console.log(`FAIL: ${GATE_PATH} missing`);
  process.exit(1);
}
const html = fs.readFileSync(GATE_PATH, "utf8");

// 1. Configurable API origin + path with documented defaults.
check(
  "data-api-origin attribute present",
  /data-api-origin\s*=\s*"https:\/\/hubapi\.loopholemaxing\.com"/.test(html),
  "expected default origin https://hubapi.loopholemaxing.com",
);
check(
  "data-api-path attribute present",
  /data-api-path\s*=\s*"\/api\/v1\/army-link\/unlock"/.test(html),
  "expected default path /api/v1/army-link/unlock",
);
check(
  "ARMY_LINK_API_ORIGIN window override is honored",
  /window\.ARMY_LINK_API_ORIGIN/.test(html),
);
check(
  "ARMY_LINK_API_PATH window override is honored",
  /window\.ARMY_LINK_API_PATH/.test(html),
);

// 2. Auth-mode indicator that reflects truth.
check(
  "auth-mode element exposes data-auth-mode",
  /id="authMode"[^>]*data-auth-mode/.test(html),
);
for (const mode of ["probing", "server", "soft"]) {
  check(
    `auth mode "${mode}" referenced in script`,
    new RegExp(`['"]${mode}['"]`).test(html),
  );
}
check(
  "soft-mode label states 'server auth not active yet'",
  /server auth not active yet/i.test(html),
);

// 3. Server unlock POSTs to the resolved URL with JSON body.
check(
  "serverUnlock uses POST",
  /method:\s*['"]POST['"]/.test(html),
);
check(
  "serverUnlock sends JSON content type",
  /['"]Content-Type['"]\s*:\s*['"]application\/json['"]/.test(html),
);
check(
  "serverUnlock body wraps the passkey field",
  /JSON\.stringify\(\s*{\s*passkey\s*:\s*passkey\s*}\s*\)/.test(html),
);
check(
  "serverUnlock consumes nexus_url from response body",
  /body\.nexus_url/.test(html),
);
// Finalized Hub PR #4 returns { unlocked: true, nexus_url }. We must accept that
// shape AND also tolerate { ok: true, nexus_url } (forward compatibility). Both
// must be checked against strict `=== true` so truthy non-boolean values do not
// pass. Either flag alone is insufficient — a valid http(s) nexus_url is still
// required (covered by applyNexusUrl scheme assertion above).
check(
  "serverUnlock accepts strict body.unlocked === true",
  /body\.unlocked\s*===\s*true/.test(html),
  "Hub PR #4 success body uses { unlocked: true, nexus_url }",
);
check(
  "serverUnlock accepts strict body.ok === true",
  /body\.ok\s*===\s*true/.test(html),
  "forward-compat with an { ok: true, nexus_url } shape",
);
check(
  "serverUnlock requires at least one of unlocked/ok before reading nexus_url",
  /body\.unlocked\s*===\s*true\s*\|\|\s*body\.ok\s*===\s*true/.test(html) ||
    /body\.ok\s*===\s*true\s*\|\|\s*body\.unlocked\s*===\s*true/.test(html),
  "missing flag must short-circuit to bad-body before consuming nexus_url",
);
check(
  "applyNexusUrl validates http(s) scheme",
  /\/\^https\?:\\\/\\\/\/i\.test\(/.test(html) ||
    /\/\^https\?:\/\/\/i\.test\(/.test(html),
);

// 4. Fail-closed: in server-mode, a 401/403/!ok response must NOT silently fall back.
//    We confirm by string-locating the rejection branch and ensuring it sets an error
//    message and does NOT call softUnlock afterward.
const serverModeBranch = html.match(
  /if\s*\(\s*serverMode\s*===\s*['"]server['"]\s*\)[\s\S]*?\}\s*\n\s*\n\s*\/\//,
);
check(
  "server-mode branch is locatable in tryUnlock",
  !!serverModeBranch,
);
if (serverModeBranch) {
  const block = serverModeBranch[0];
  check(
    "server-mode branch contains rejection messaging",
    /Incorrect passkey or server rejected/.test(block),
    "fail-closed message expected",
  );
  check(
    "server-mode branch does NOT call softUnlock as a silent fallback",
    !/softUnlock\s*\(/.test(block),
    "must not fall back to soft after sending plaintext",
  );
  check(
    "server-mode branch returns on rejected/bad responses",
    /return;\s*\}\s*\/\/[\s\S]*?Network died/.test(block) ||
      /return;\s*\}\s*\n\s*\/\//.test(block),
  );
}

// 5. Soft path is reached only when serverMode !== 'server' (i.e., probe set 'soft').
check(
  "soft path is gated by serverMode !== 'server'",
  /\/\/ Soft-gate fallback/.test(html) && /softUnlock\s*\(/.test(html),
);

// 6. Disclaimers intact.
check(
  "disclaimer mentions no trading execution",
  /no trading/i.test(html),
);
check(
  "disclaimer mentions no order routing",
  /no order routing/i.test(html),
);
check(
  "disclaimer mentions no broker connection",
  /no broker/i.test(html),
);
check(
  "soft-gate disclaimer block is present",
  /Soft-gate disclaimer/.test(html),
);

// 7. No plaintext passkey in the bundle. Sliding-window SHA-256 over the file's
//    raw bytes; we compare against the expected digest WITHOUT ever embedding the
//    plaintext in this script.
const buf = fs.readFileSync(GATE_PATH);
let leakFound = false;
if (buf.length >= PASSKEY_LEN) {
  for (let i = 0; i + PASSKEY_LEN <= buf.length; i++) {
    const win = buf.subarray(i, i + PASSKEY_LEN);
    // Skip windows containing nul/newline/cr — passkey is a single ASCII line.
    if (win.includes(0x00) || win.includes(0x0a) || win.includes(0x0d)) continue;
    const h = crypto.createHash("sha256").update(win).digest("hex");
    if (h === EXPECTED_DIGEST) {
      leakFound = true;
      break;
    }
  }
}
check(
  "no plaintext passkey appears in army-link/index.html",
  !leakFound,
  "sliding-window SHA-256 matched the expected digest",
);

// 8. Expected digest itself is still the comparison target for the soft path.
check(
  "expected SHA-256 digest is referenced (used by soft fallback)",
  html.includes(EXPECTED_DIGEST),
);

// 9. No console.log of input.
const leakPatterns = [
  /console\.log\(\s*value\b/,
  /console\.log\(\s*input\b/,
  /console\.log\(\s*passkey\b/,
];
for (const p of leakPatterns) {
  check(`no input leak: ${p}`, !p.test(html));
}

if (failures > 0) {
  console.log(`\nFAILED: ${failures} assertion(s) in army-link server-mode contract`);
  process.exit(1);
}
console.log("\nOK: army-link server-mode contract passed");
process.exit(0);
