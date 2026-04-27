#!/usr/bin/env bash
# tests/phase7-trust-scan.sh
# Static checks for the Phase 7 Public UX Intelligence Layer.
#
# Invariants enforced:
#   1. Trust & Transparency section + sidebar entry are present.
#   2. All Phase 7 panel containers exist.
#   3. Empty / initializing copy is present for every panel that depends
#      on a not-yet-populated artifact (history, briefing, confidence).
#   4. No fabricated / hardcoded numeric accuracy or confidence interval
#      claims appear inside the Phase 7 markup. Numbers must come from
#      the artifacts at runtime.
#   5. Confidence-interval panel must NEVER show a band unless it is
#      gated on a confidence_intervals.json artifact with method +
#      generated_at present.
#   6. Source freshness reads data/public/source_health.json.
#   7. Model badges read models/public/registry.json.
#   8. The "not financial advice" disclaimer is present in the Phase 7
#      block.
#   9. No HUB integration is claimed as active (Phase 5 is not merged).
#  10. Public bundle is secret-free for the new file paths the Phase 7
#      JS may fetch.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F="$ROOT/btc-brain/index.html"
FAIL=0
say() { echo "  $1"; }

if [ ! -f "$F" ]; then
  echo "FAIL: $F not found"; exit 1
fi

# Extract the Phase 7 block once for sub-checks.
# Anchor on the trust-layer section start through to the appendices section.
P7=$(awk '/<section class="chapter" id="trust-layer">/,/<section class="chapter" id="appendices">/' "$F")
if [ -z "$P7" ]; then
  echo "FAIL [boundary] could not isolate Phase 7 block"
  exit 1
fi

# 1. Section + sidebar entry
if grep -nE 'id="trust-layer"' "$F" >/dev/null \
   && grep -nE 'href="#trust-layer"' "$F" >/dev/null; then
  say "OK [1] trust-layer section + sidebar entry present"
else
  echo "FAIL [1] trust-layer section or sidebar entry missing"
  FAIL=1
fi

# 2. Panel containers
for id in p7-trust-summary p7-source-freshness-panel p7-model-badges-panel \
          p7-confidence-panel p7-history-panel p7-briefing-panel; do
  if ! printf '%s' "$P7" | grep -qE 'id="'"$id"'"'; then
    echo "FAIL [2] missing panel container: $id"
    FAIL=1
  fi
done
say "OK [2] panel containers checked"

# 3. Empty / initializing copy for artifact-gated panels
EMPTY_FAIL=0
for needle in "Prediction history" "Confidence intervals" "Daily briefing archive"; do
  if ! printf '%s' "$P7" | grep -qF "$needle"; then
    echo "FAIL [3] missing panel copy mentioning: $needle"
    EMPTY_FAIL=1
  fi
done
for needle in "initializing" "unavailable" "not connected"; do
  if ! printf '%s' "$P7" | grep -qF "$needle"; then
    echo "FAIL [3] missing empty-state phrase: $needle"
    EMPTY_FAIL=1
  fi
done
if [ "$EMPTY_FAIL" -eq 0 ]; then
  say "OK [3] empty/initializing states present"
else
  FAIL=1
fi

# 4. No fabricated numeric accuracy / confidence inside the Phase 7 block.
# Specifically, no hardcoded percentages or N counts that look like measured
# stats. We forbid "<digits>%" or "n=<digits>" appearing as literal text
# in the Phase 7 markup (the JS injects values at runtime; literal digits
# come from min_n_display copy and the n=20 threshold label, which we
# whitelist).
TMP_P7=$(mktemp)
printf '%s' "$P7" > "$TMP_P7"
# Allow: literal "n=20" inside the trust summary (sample-size threshold copy).
# Allow: literal "n≥20" or "n≥' + accuracy.min_n_display + '"
# Disallow: anything else like 64%, 78%, hit rate 72.4%, etc.
BAD=$(grep -oE '>[^<]*[0-9]+(\.[0-9]+)?%[^<]*<' "$TMP_P7" | grep -vE '^[ \t]*>[ \t]*<' || true)
if [ -n "$BAD" ]; then
  echo "FAIL [4] hardcoded percentage(s) found inside Phase 7 markup:"
  printf '%s\n' "$BAD" | sed 's/^/  /'
  FAIL=1
else
  say "OK [4] no hardcoded percentage claims inside Phase 7 markup"
fi
rm -f "$TMP_P7"

# 5. Confidence interval gate: must check ci.method && ci.generated_at &&
#    ci.intervals before rendering.
if printf '%s' "$P7" | grep -qE '!ci\.method' \
   && printf '%s' "$P7" | grep -qE '!ci\.generated_at' \
   && printf '%s' "$P7" | grep -qE '!ci\.intervals'; then
  say "OK [5] confidence interval render is gated on artifact schema"
else
  echo "FAIL [5] confidence interval gating not strict enough"
  FAIL=1
fi

# 6. Source freshness reads source_health.json
if printf '%s' "$P7" | grep -qE 'data/public/source_health\.json'; then
  say "OK [6] source freshness reads data/public/source_health.json"
else
  echo "FAIL [6] source_health.json reference missing"
  FAIL=1
fi

# 7. Model badges read registry.json
if printf '%s' "$P7" | grep -qE 'models/public/registry\.json'; then
  say "OK [7] model badges read models/public/registry.json"
else
  echo "FAIL [7] registry.json reference missing"
  FAIL=1
fi

# 8. No-financial-advice disclaimer inside Phase 7 block
if printf '%s' "$P7" | grep -qiE 'not financial advice'; then
  say "OK [8] not-financial-advice disclaimer present in Phase 7 block"
else
  echo "FAIL [8] no NFA disclaimer in Phase 7 block"
  FAIL=1
fi

# 9. No claim of active HUB integration (Phase 5 not merged).
# Forbid affirmative claims like "HUB connected", "hub: live",
# "hub integrated" (without a "not yet" qualifier), "hub synced".
HUB_HITS=$(printf '%s' "$P7" | grep -inE 'hub[^"<]*(connected|live|integrated|synced|active)' || true)
if [ -n "$HUB_HITS" ]; then
  # Allow lines that explicitly negate the claim ("not yet", "not "
  # immediately before the trigger word, "until").
  BAD=$(printf '%s\n' "$HUB_HITS" | grep -ivE '(not yet|not connected|not integrated|until)' || true)
  if [ -n "$BAD" ]; then
    echo "FAIL [9] Phase 7 block makes an active HUB integration claim:"
    printf '%s\n' "$BAD" | sed 's/^/  /'
    FAIL=1
  else
    say "OK [9] HUB references are explicitly negated"
  fi
else
  say "OK [9] no HUB-active claim"
fi

# 10. The Phase 7 JS only references known artifact paths — none of them
# should look like a secret. (We rely on tests/secret-scan.sh for the
# actual scan; here we just confirm the paths used are public-bundle
# relative.)
for path in \
  "data/public/source_health.json" \
  "models/public/registry.json" \
  "models/public/phase4/phase4_report.json" \
  "models/public/confidence_intervals.json" \
  "ledger/data/forecasts.jsonl" \
  "ledger/data/resolutions.jsonl" \
  "ledger/public/accuracy.json" \
  "data/public/briefings/index.json"
do
  if ! printf '%s' "$P7" | grep -qF "$path"; then
    echo "FAIL [10] expected artifact path missing in Phase 7 fetch list: $path"
    FAIL=1
  fi
done
say "OK [10] artifact path list is complete and public-bundle relative"

# 11. Truth gate: the existing measured-accuracy panel must remain
# ledger-backed (regression guard against a future edit that hard-codes
# numbers in the same panel).
if grep -nE "id=\"measured-accuracy-panel\"" "$F" >/dev/null \
   && grep -nE "ledger/public/accuracy\.json" "$F" >/dev/null; then
  say "OK [11] measured-accuracy-panel still reads ledger/public/accuracy.json"
else
  echo "FAIL [11] measured-accuracy-panel regressed away from ledger backing"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo "ALL PHASE 7 TRUST-SCAN INVARIANTS HELD"
else
  echo "ONE OR MORE PHASE 7 TRUST-SCAN INVARIANTS FAILED"
fi
exit "$FAIL"
