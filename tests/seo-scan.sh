#!/usr/bin/env bash
# tests/seo-scan.sh — guards the name-query / entity SEO wiring.
#
# WHY THIS EXISTS
# ---------------
# The exact string "Clayton Camera" collides with traffic/weather cams in
# three towns named Clayton. Beating that needs an *entity*, not keywords:
# one stable Person @id, referenced identically from every property, with
# a dedicated person page that search engines can resolve the name to.
# That wiring is invisible in the rendered page, so it silently rots.
# These assertions make rot a CI failure.
#
# Static-only: no network, no browser. Safe to run anywhere.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAILED=0
fail() { echo "  ❌ $1"; FAILED=1; }
ok()   { echo "  ✅ $1"; }

PERSON_ID="https://loopholemaxing.com/clayton-camera/#person"
HUB="clayton-camera/index.html"

# ── 1. robots.txt advertises a sitemap that actually exists ──────────────
# This was a live bug: robots.txt pointed at /sitemap.xml → 404.
echo "-- robots.txt / sitemap.xml agreement --"
if [ ! -f robots.txt ]; then
  fail "robots.txt missing"
elif ! grep -q "^Sitemap: https://loopholemaxing.com/sitemap.xml" robots.txt; then
  fail "robots.txt does not advertise https://loopholemaxing.com/sitemap.xml"
else
  ok "robots.txt advertises the sitemap"
fi

if [ ! -f sitemap.xml ]; then
  fail "sitemap.xml missing — robots.txt points at a 404"
else
  ok "sitemap.xml exists"
fi

# ── 2. every indexable top-level page is in the sitemap ──────────────────
# A public page absent from the sitemap is a page Google may never crawl.
echo "-- sitemap coverage --"
for p in "/" "/clayton-camera/" "/btc-brain/" "/uae/" "/vault/" "/ultron/" "/nba-brain/" "/agora/" "/formix/"; do
  if grep -q "<loc>https://loopholemaxing.com${p}</loc>" sitemap.xml 2>/dev/null; then
    ok "sitemap lists ${p}"
  else
    fail "sitemap is MISSING ${p}"
  fi
done

# ── 3. private tooling must never leak into the sitemap ──────────────────
# These are robots-disallowed + noindex. Listing them in a sitemap
# contradicts that and invites crawling of internal ops surfaces.
echo "-- sitemap excludes private surfaces --"
for p in "analytics-hub" "army-link" "mms-hub" "studio" "window" "work-with-clayton"; do
  if grep -q "loopholemaxing.com/${p}/" sitemap.xml 2>/dev/null; then
    fail "sitemap leaks private/noindex path /${p}/"
  else
    ok "sitemap excludes /${p}/"
  fi
done

# ── 4. the person hub exists and is shaped for a name query ─────────────
# Title, H1 and canonical must all carry the literal name — that is the
# whole reason this page exists.
echo "-- person entity hub --"
if [ ! -f "$HUB" ]; then
  fail "$HUB missing — nothing on the network targets the name query"
else
  ok "$HUB exists"
  grep -q "<title>Clayton Camera" "$HUB" \
    && ok "title starts with the name" \
    || fail "title must START with 'Clayton Camera' (name-query pages lead with the name)"
  grep -q "<h1>Clayton Camera</h1>" "$HUB" \
    && ok "h1 is exactly the name" \
    || fail "h1 must be exactly 'Clayton Camera'"
  grep -q 'rel="canonical" href="https://loopholemaxing.com/clayton-camera/"' "$HUB" \
    && ok "canonical is self-referential" \
    || fail "hub missing self-referential canonical"
  grep -q 'disambiguatingDescription' "$HUB" \
    && ok "disambiguatingDescription present (separates person from the webcams)" \
    || fail "disambiguatingDescription missing — this is the anti-webcam signal"
  grep -q '"@type": "FAQPage"' "$HUB" \
    && ok "FAQPage present ('Who is Clayton Camera?')" \
    || fail "FAQPage missing — answers the literal name query"
fi

# ── 5. ONE entity id, referenced everywhere ─────────────────────────────
# Minting a second Person @id splits the entity and wastes every signal.
echo "-- shared Person @id --"
for f in index.html "$HUB"; do
  if grep -q "$PERSON_ID" "$f" 2>/dev/null; then
    ok "$f references the canonical Person @id"
  else
    fail "$f does NOT reference $PERSON_ID"
  fi
done

# No stray second Person id anywhere in the public tree.
if grep -rhoE '"@id": "https://[^"]*#person"' --include="*.html" . 2>/dev/null \
     | sort -u | grep -v "^\"@id\": \"$PERSON_ID\"$" | grep -q .; then
  fail "a second Person @id exists — entity is split"
  grep -rhoE '"@id": "https://[^"]*#person"' --include="*.html" . 2>/dev/null | sort -u | sed 's/^/     /'
else
  ok "exactly one Person @id across the tree"
fi

# ── 6. every JSON-LD block parses ───────────────────────────────────────
# Invalid JSON-LD is silently ignored by crawlers — it fails open, which
# is the worst kind of failure: looks wired, does nothing.
echo "-- JSON-LD validity --"
if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
import json, re, sys, glob, os
bad = 0
for path in glob.glob("*.html") + glob.glob("*/index.html"):
    html = open(path, encoding="utf-8", errors="replace").read()
    for i, block in enumerate(re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.S), 1):
        try:
            json.loads(block)
        except Exception as e:
            print(f"  ❌ {path} JSON-LD block {i} does not parse: {e}")
            bad = 1
if not bad:
    print("  ✅ all JSON-LD blocks parse")
sys.exit(bad)
PY
  [ $? -ne 0 ] && FAILED=1
else
  echo "  SKIP: python3 not installed"
fi

# ── 7. the hub is internally linked ─────────────────────────────────────
# An orphan page accrues no authority no matter how good its schema is.
echo "-- internal linking --"
if grep -q 'href="/clayton-camera/"' index.html; then
  ok "homepage links to the person hub"
else
  fail "homepage does not link to /clayton-camera/ — hub would be an orphan"
fi

echo
if [ $FAILED -eq 0 ]; then
  echo "SEO SCAN: PASS"
  exit 0
fi
echo "SEO SCAN: FAIL"
exit 1
