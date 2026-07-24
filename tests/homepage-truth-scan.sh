#!/usr/bin/env bash
# tests/homepage-truth-scan.sh
# Static guard on index.html (the public portfolio home page). Grep-based and
# self-contained, same style as btc-brain-truth-scan.sh.
#
# Why this exists: the home page describes systems that live in OTHER repos,
# so their honesty fixes do not propagate here automatically. Twice now the
# portfolio kept a claim the source system had already retired. These checks
# fail the build instead of waiting for someone to notice.
#
# Invariants enforced:
#   1. No earnings-claim language for KnockFiber ("uncapped" / "no cap" /
#      "no ceiling") — scrubbed sitewide on knockfiber.com 2026-07-17, so the
#      portfolio must not reintroduce it.
#   2. No wrong-signed OrbitRoute cost claim. OrbitRoute's own live
#      /cost-compare returns an orbital PREMIUM vs terrestrial; any "savings
#      vs AWS/GCP/Azure" wording here contradicts the product.
#   3. No value-ranking language in public copy (removed 2026-06-29 by
#      Clayton's call — viewers are not told the ordering rationale).
#   4. Structural wiring intact: WORK_WITH_URL constant, capture.js include,
#      analytics tracker, canonical URL.
#   5. Ship Log present with dated entries (>= 5), so the page can't silently
#      rot into a stale snapshot.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F="$ROOT/index.html"
FAIL=0
say() { echo "  $1"; }

if [ ! -f "$F" ]; then
  echo "FAIL: $F not found"; exit 1
fi

# 1. Earnings-claim language
if grep -niE 'uncapped|no cap\b|no ceiling|sin tope' "$F" >/dev/null; then
  echo "FAIL [1] earnings-claim language present (uncapped / no cap / no ceiling)"
  grep -niE 'uncapped|no cap\b|no ceiling|sin tope' "$F" | sed 's/^/  /'
  FAIL=1
else
  say "OK [1] no earnings-claim language"
fi

# 2. Wrong-signed OrbitRoute economics
if grep -niE 'savings vs\.? *(aws|gcp|azure)|% (projected )?savings vs|fraction of hyperscaler' "$F" >/dev/null; then
  echo "FAIL [2] OrbitRoute savings claim contradicts the live cost-compare (orbital is a premium today)"
  grep -niE 'savings vs\.? *(aws|gcp|azure)|% (projected )?savings vs|fraction of hyperscaler' "$F" | sed 's/^/  /'
  FAIL=1
else
  say "OK [2] no wrong-signed orbital savings claim"
fi

# 3. Value-ranking language
if grep -niE 'ordered by value|ranked by value|value-ranked' "$F" >/dev/null; then
  echo "FAIL [3] value-ranking language present in public copy"
  grep -niE 'ordered by value|ranked by value|value-ranked' "$F" | sed 's/^/  /'
  FAIL=1
else
  say "OK [3] no value-ranking language in public copy"
fi

# 4. Structural wiring
WIRE_OK=1
for needle in "WORK_WITH_URL" "/capture.js" "data-site=\"loopholemaxing\"" "rel=\"canonical\""; do
  if ! grep -qF -- "$needle" "$F"; then
    echo "FAIL [4] missing required wiring: $needle"
    WIRE_OK=0; FAIL=1
  fi
done
[ $WIRE_OK -eq 1 ] && say "OK [4] work-with link, capture.js, analytics tag, canonical all present"

# 5. Ship Log present and populated
SHIPS=$(grep -c 'class="ship-date"' "$F" || true)
if grep -qF 'id="shiplog"' "$F" && [ "$SHIPS" -ge 5 ]; then
  say "OK [5] ship log present with $SHIPS dated entries"
else
  echo "FAIL [5] ship log missing or under-populated (found $SHIPS dated entries, need >= 5)"
  FAIL=1
fi

if [ $FAIL -ne 0 ]; then
  echo "homepage-truth-scan: FAIL"
  exit 1
fi
echo "homepage-truth-scan: PASS"
