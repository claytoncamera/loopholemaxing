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
#   6. Live figures agree with themselves. The page states the same number in
#      up to four places (hero stat band, work-band feature list, card body,
#      card meta chip). On 2026-08-09 a refresh updated the card and missed the
#      hero and the feature list, so the page served 1,935 and 1,856 forecasts
#      simultaneously. The Ship Log is EXCLUDED from this check on purpose: it
#      is a dated historical record, and "the surface is now 255 cities" was
#      true on the day it was written. Rewriting a dated entry to match today
#      would be falsifying the log, which is worse than the drift.
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

# 6. Live-figure self-consistency (Ship Log excluded — dated record, see header)
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
awk '/<section class="shiplog"/ { skip=1 }
     skip && /<\/section>/      { skip=0; next }
     !skip                      { print }' "$F" > "$BODY"

consistent() {
  # consistent <label> <pattern>...  — each pattern must match text whose first
  # number is the figure. All occurrences across all patterns must agree.
  local label="$1"; shift
  local all=""
  for pat in "$@"; do
    all="$all$(grep -oE "$pat" "$BODY" | grep -oE '[0-9][0-9,]*' || true)
"
  done
  local uniq count
  uniq=$(printf '%s\n' "$all" | sed '/^$/d' | sort -u)
  count=$(printf '%s\n' "$uniq" | sed '/^$/d' | wc -l | tr -d ' ')
  if [ "$count" -le 1 ]; then
    say "OK [6] $label consistent ($(printf '%s' "$uniq" | tr '\n' ' '))"
  else
    echo "FAIL [6] $label is stated inconsistently across the page: $(printf '%s\n' "$uniq" | tr '\n' ' ')"
    echo "  (update every occurrence outside the Ship Log — hero band, feature list, card body, card meta)"
    FAIL=1
  fi
}

consistent "BTC forecasts scored" \
  '[0-9,]+ publicly scored forecasts' \
  '[0-9,]+ resolved forecasts' \
  'card-meta-item">[0-9,]+ resolved<' \
  'hero-stat-val">[0-9,]+</div><div class="hero-stat-lbl">Forecasts Scored'

consistent "KnockFiber city count" \
  '[0-9,]+ city pages' \
  '[0-9,]+ cities'

consistent "PeptiDex entry count" \
  '[0-9,]+ structured entries' \
  'card-meta-item">[0-9,]+ entries<' \
  '[0-9,]+ peptides'

if [ $FAIL -ne 0 ]; then
  echo "homepage-truth-scan: FAIL"
  exit 1
fi
echo "homepage-truth-scan: PASS"
