#!/usr/bin/env node
/**
 * tests/army-link-unlock-behavior.spec.mjs
 *
 * Behavioural cross-check of the Army Link server-mode unlock against the
 * finalized Hub PR #4 contract:
 *
 *   POST /api/v1/army-link/unlock
 *     Success:  200 { "unlocked": true,  "nexus_url": "https://..." }
 *     Bad key:  401 { "error":     "invalid_passkey" }
 *     Disabled: 503 { "error":     "unlock_disabled" }
 *     Throttle: 429 { "error":     "too_many_attempts" }
 *
 * Static markers are covered by tests/army-link-server-mode.spec.mjs. This
 * file extracts the actual `serverUnlock` function source from the page and
 * runs it inside a sandbox with a stubbed `fetch`, asserting:
 *
 *   1. Hub-shape success { unlocked: true, nexus_url } resolves ok with the
 *      server-returned URL.
 *   2. Forward-compat success { ok: true, nexus_url } is also accepted.
 *   3. Either flag without a valid http(s) nexus_url fails closed.
 *   4. A 200 with neither flag fails closed (does not leak any URL the body
 *      may happen to contain).
 *   5. 401, 403, 429, 503, and 5xx all fail closed with no nexus_url.
 *   6. Both flags must be STRICT === true; truthy values like "true" / 1 do
 *      not unlock.
 *
 * Run: node tests/army-link-unlock-behavior.spec.mjs
 */

import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const GATE_PATH = path.join(ROOT, "army-link", "index.html");

const html = fs.readFileSync(GATE_PATH, "utf8");

// Extract the `serverUnlock` function source. We slice from `async function
// serverUnlock` through the matching closing brace at the function level.
function extractServerUnlock(src) {
  const startNeedle = "async function serverUnlock";
  const start = src.indexOf(startNeedle);
  if (start < 0) throw new Error("serverUnlock not found in army-link page");
  // Walk braces from the first `{` after the signature.
  const openIdx = src.indexOf("{", start);
  if (openIdx < 0) throw new Error("serverUnlock body brace not found");
  let depth = 0;
  let i = openIdx;
  for (; i < src.length; i++) {
    const ch = src[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  if (depth !== 0) throw new Error("serverUnlock body unmatched braces");
  return src.slice(start, i + 1);
}

const fnSource = extractServerUnlock(html);

// We also need `resolveApiUrl` since serverUnlock calls it. Provide a stub
// that matches the page's default origin/path so the network leg is well-defined.
const harness = `
  function resolveApiUrl() {
    return "https://hubapi.loopholemaxing.com/api/v1/army-link/unlock";
  }
  ${fnSource}
  globalThis.__serverUnlock = serverUnlock;
`;

let failures = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`  ok   ${name}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}${detail ? "  — " + detail : ""}`);
  }
}

console.log("== army-link unlock behavior (Hub PR #4 contract) ==");

function makeContext(fetchImpl) {
  const ctx = {
    fetch: fetchImpl,
    AbortController: globalThis.AbortController,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    JSON,
    console: { log() {}, warn() {}, error() {} },
  };
  vm.createContext(ctx);
  vm.runInContext(harness, ctx);
  return ctx;
}

function jsonResp(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

async function run() {
  // 1. Hub-shape success: { unlocked: true, nexus_url }
  {
    const ctx = makeContext(async () =>
      jsonResp(200, { unlocked: true, nexus_url: "https://nexus.example.com/x" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "Hub success { unlocked:true, nexus_url } → ok with server URL",
      out.ok === true && out.nexus_url === "https://nexus.example.com/x",
      JSON.stringify(out),
    );
  }

  // 2. Forward-compat success: { ok: true, nexus_url }
  {
    const ctx = makeContext(async () =>
      jsonResp(200, { ok: true, nexus_url: "https://nexus.example.com/y" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "forward-compat { ok:true, nexus_url } → ok with server URL",
      out.ok === true && out.nexus_url === "https://nexus.example.com/y",
      JSON.stringify(out),
    );
  }

  // 3. Flag set but no nexus_url → fail closed.
  {
    const ctx = makeContext(async () => jsonResp(200, { unlocked: true }));
    const out = await ctx.__serverUnlock("anything");
    check(
      "{ unlocked:true } without nexus_url → fail-closed (bad-nexus-url)",
      out.ok === false && out.reason === "bad-nexus-url",
      JSON.stringify(out),
    );
  }

  // 4. 200 with no success flag → fail closed even if a URL is in the body.
  {
    const ctx = makeContext(async () =>
      jsonResp(200, { nexus_url: "https://nexus.example.com/leak" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "200 with no flag, only nexus_url → fail-closed (bad-body)",
      out.ok === false && out.reason === "bad-body",
      JSON.stringify(out),
    );
  }

  // 5a. 401 → rejected
  {
    const ctx = makeContext(async () =>
      jsonResp(401, { error: "invalid_passkey" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "401 invalid_passkey → fail-closed (rejected)",
      out.ok === false && out.reason === "rejected" && !out.nexus_url,
      JSON.stringify(out),
    );
  }

  // 5b. 403 → rejected
  {
    const ctx = makeContext(async () => jsonResp(403, {}));
    const out = await ctx.__serverUnlock("anything");
    check(
      "403 → fail-closed (rejected)",
      out.ok === false && out.reason === "rejected",
      JSON.stringify(out),
    );
  }

  // 5c. 429 too_many_attempts → http-429
  {
    const ctx = makeContext(async () =>
      jsonResp(429, { error: "too_many_attempts" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "429 too_many_attempts → fail-closed (http-429)",
      out.ok === false && /^http-429/.test(out.reason || ""),
      JSON.stringify(out),
    );
  }

  // 5d. 503 unlock_disabled → http-503
  {
    const ctx = makeContext(async () =>
      jsonResp(503, { error: "unlock_disabled" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "503 unlock_disabled → fail-closed (http-503)",
      out.ok === false && /^http-503/.test(out.reason || ""),
      JSON.stringify(out),
    );
  }

  // 5e. 500 server error → http-500
  {
    const ctx = makeContext(async () => jsonResp(500, {}));
    const out = await ctx.__serverUnlock("anything");
    check(
      "500 → fail-closed (http-5xx)",
      out.ok === false && /^http-5/.test(out.reason || ""),
      JSON.stringify(out),
    );
  }

  // 6. Truthy-but-not-strict-true flags must NOT unlock.
  for (const v of ["true", 1, "1", "yes", {}]) {
    const ctx = makeContext(async () =>
      jsonResp(200, { unlocked: v, nexus_url: "https://nexus.example.com/z" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      `truthy non-boolean unlocked=${JSON.stringify(v)} → fail-closed`,
      out.ok === false && out.reason === "bad-body",
      JSON.stringify(out),
    );
  }
  for (const v of ["true", 1]) {
    const ctx = makeContext(async () =>
      jsonResp(200, { ok: v, nexus_url: "https://nexus.example.com/z" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      `truthy non-boolean ok=${JSON.stringify(v)} → fail-closed`,
      out.ok === false && out.reason === "bad-body",
      JSON.stringify(out),
    );
  }

  // 7. Non-https nexus_url → fail closed.
  {
    const ctx = makeContext(async () =>
      jsonResp(200, { unlocked: true, nexus_url: "javascript:alert(1)" }),
    );
    const out = await ctx.__serverUnlock("anything");
    check(
      "javascript: nexus_url → fail-closed (bad-nexus-url)",
      out.ok === false && out.reason === "bad-nexus-url",
      JSON.stringify(out),
    );
  }

  // 8. Network error → fail closed (network).
  {
    const ctx = makeContext(async () => {
      throw new TypeError("fetch failed");
    });
    const out = await ctx.__serverUnlock("anything");
    check(
      "fetch throws → fail-closed (network)",
      out.ok === false && out.reason === "network",
      JSON.stringify(out),
    );
  }

  if (failures > 0) {
    console.log(`\nFAILED: ${failures} assertion(s) in unlock behavior`);
    process.exit(1);
  }
  console.log("\nOK: army-link unlock behavior matches Hub PR #4 contract");
}

run().catch((e) => {
  console.error("UNCAUGHT", e);
  process.exit(1);
});
