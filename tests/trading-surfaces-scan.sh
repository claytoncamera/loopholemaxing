#!/usr/bin/env bash
# Guard the public MMS preview and owner-only Trading Cockpit.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC="$ROOT/mms-hub/index.html"
OWNER="$ROOT/window/trading/index.html"
FAIL=0
ok(){ echo "  ✅ $1"; }
fail(){ echo "  ❌ $1"; FAIL=1; }

for f in "$PUBLIC" "$OWNER"; do
  [ -f "$f" ] && ok "$(basename "$(dirname "$f")") surface exists" || fail "$f missing"
done

grep -q 'name="robots" content="index,follow"' "$PUBLIC" && ok "public preview is indexable" || fail "public preview must be index,follow"
grep -q 'rel="canonical" href="https://loopholemaxing.com/mms-hub/"' "$PUBLIC" && ok "public preview self-canonical" || fail "public preview canonical missing"
grep -q 'https://claytoncamera.com/#person' "$PUBLIC" && ok "public preview references canonical Person" || fail "public preview entity link missing"
grep -q '/btc-brain/ledger/public/accuracy.json' "$PUBLIC" && grep -q '/btc-brain/ledger/public/signal.json' "$PUBLIC" \
  && ok "public preview reads the live ledger and gate" || fail "public preview live evidence wiring missing"
grep -q 'No strategy is represented as profitable' "$PUBLIC" && grep -q 'Not financial advice' "$PUBLIC" \
  && ok "public preview keeps evidence disclaimer" || fail "public preview honesty copy missing"

grep -q 'name="robots" content="noindex,nofollow"' "$OWNER" && ok "owner cockpit is noindex" || fail "owner cockpit must be noindex,nofollow"
grep -q "const SESSION_KEY='window_unlocked_v1'" "$OWNER" && ok "owner cockpit shares Window session gate" || fail "owner cockpit gate session mismatch"
grep -q "EXPECTED_DIGEST='ec07c9c3e1fc3114ab35cdacc62bab0cc9b99da9f1c96aa6b25aa0c175c77c1f'" "$OWNER" \
  && ok "owner cockpit shares Window digest" || fail "owner cockpit digest drift"
grep -q 'Source-of-truth hierarchy' "$OWNER" && grep -q 'Fail-closed promotion gate' "$OWNER" \
  && ok "owner cockpit carries truth and risk layers" || fail "owner cockpit system map incomplete"

if grep -q '^Disallow: /mms-hub/' "$ROOT/robots.txt"; then fail "robots still blocks public MMS preview"; else ok "robots allows public MMS preview"; fi
grep -q '<loc>https://loopholemaxing.com/mms-hub/</loc>' "$ROOT/sitemap.xml" && ok "sitemap lists public MMS preview" || fail "sitemap missing public MMS preview"
grep -q '^Disallow: /window/' "$ROOT/robots.txt" && ok "robots still blocks owner Window" || fail "robots must block owner Window"

# Public copy may discuss observed profitability, but must never promise it.
if grep -niE 'guaranteed (profit|return)|profit guaranteed|risk[- ]free returns?|always profitable' "$PUBLIC" >/dev/null; then
  fail "public preview contains a prohibited performance promise"
else
  ok "public preview contains no performance guarantee"
fi

if [ "$FAIL" -eq 0 ]; then echo "trading-surfaces-scan: PASS"; exit 0; fi
echo "trading-surfaces-scan: FAIL"; exit 1
