#!/usr/bin/env bash
# tests/btc-brain-truth-scan.sh
# Static checks for the four P0 truth-and-safety invariants on
# btc-brain/index.html. Each check is grep-based and self-contained so it
# runs without a JS test harness.
#
# Invariants enforced:
#   1. No synthetic OHLC (`p[1]*1.001` / `p[1]*0.999` / volume "100" stub) in
#      the CoinGecko fallback.
#   2. CoinGecko fallback never sets a fabricated bullish/bearish high/low
#      (no `btc.usd * 1.02` / `btc.usd * 0.98`).
#   3. Indicator paths drop the live (in-progress) candle — closedCandlesOnly
#      / dropLive / _closedOnly helpers must exist.
#   4. The public disclaimer banner (#public-disclaimer) is present.
#   5. The legacy unsupported claims have been relabeled (no naked
#      "Signal Accuracy ... 64%" / "Analog Match ... 78%" / "+8.3 pts /
#      upgrade" without the experimental marker).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F="$ROOT/btc-brain/index.html"
FAIL=0
say() { echo "  $1"; }

if [ ! -f "$F" ]; then
  echo "FAIL: $F not found"; exit 1
fi

# 1. No synthetic OHLC fabrication
if grep -nE 'p\[1\]\s*\*\s*1\.001|p\[1\]\s*\*\s*0\.999' "$F" >/dev/null; then
  echo "FAIL [1] synthetic OHLC fabrication still present"
  grep -nE 'p\[1\]\s*\*\s*1\.001|p\[1\]\s*\*\s*0\.999' "$F" | sed 's/^/  /'
  FAIL=1
else
  say "OK [1] no synthetic OHLC fabrication"
fi

# 2. No fabricated CoinGecko high/low
if grep -nE 'btc\.usd\s*\*\s*1\.02|btc\.usd\s*\*\s*0\.98' "$F" >/dev/null; then
  echo "FAIL [2] CoinGecko fallback fabricates high/low"
  grep -nE 'btc\.usd\s*\*\s*1\.02|btc\.usd\s*\*\s*0\.98' "$F" | sed 's/^/  /'
  FAIL=1
else
  say "OK [2] no fabricated CoinGecko high/low"
fi

# 2b. CoinGecko fallback must never imply open=0 / fake-bullish
# (the old toKline produced open == close trivially; we now pass null).
if grep -nE 'toKline\s*=\s*\(p\)' "$F" >/dev/null; then
  echo "FAIL [2b] toKline OHLC synthesizer still present"
  FAIL=1
else
  say "OK [2b] toKline synthesizer removed"
fi

# 3. Closed-candle helper present in at least one form
if grep -nE 'closedCandlesOnly|dropLive\s*=\s*function|_closedOnly\s*=\s*function|_closedOnly\s*\(' "$F" >/dev/null; then
  say "OK [3] closed-candle helper present"
else
  echo "FAIL [3] no closed-candle helper found"
  FAIL=1
fi

# 4. Public disclaimer banner
if grep -nE 'id="public-disclaimer"' "$F" >/dev/null \
   && grep -nE 'Educational research' "$F" >/dev/null \
   && grep -nE 'not financial advice' "$F" >/dev/null; then
  say "OK [4] public disclaimer banner present"
else
  echo "FAIL [4] public disclaimer banner missing or incomplete"
  FAIL=1
fi

# 5. Unsupported numeric claims must be either gone or marked experimental.
# We forbid the *old* hardcoded 26px Signal Accuracy "64%" and Analog Match
# "78%" pair with a green color that suggested ledger-backed confidence.
if grep -nE 'Signal Accuracy[^<]*</div>\s*<div[^>]*color:#3fb950[^>]*>\s*64%' "$F" >/dev/null; then
  echo "FAIL [5a] unrelabeled Signal Accuracy 64% block still present"
  FAIL=1
else
  say "OK [5a] no unrelabeled Signal Accuracy claim"
fi
if grep -nE 'Analog Match[^<]*</div>\s*<div[^>]*color:#d2a8ff[^>]*>\s*78%' "$F" >/dev/null; then
  echo "FAIL [5b] unrelabeled Analog Match 78% block still present"
  FAIL=1
else
  say "OK [5b] no unrelabeled Analog Match claim"
fi
if grep -nE '\+8\.3 pts / upgrade cycle' "$F" >/dev/null; then
  echo "FAIL [5c] '+8.3 pts / upgrade cycle' growth claim still present"
  FAIL=1
else
  say "OK [5c] '+8.3 pts / upgrade cycle' claim removed"
fi
if grep -nE "Self-improving research loop" "$F" >/dev/null; then
  echo "FAIL [5d] 'Self-improving research loop' claim still present"
  FAIL=1
else
  say "OK [5d] 'Self-improving' claim relabeled"
fi

# 6. Stale-state copy is in place for feed failure
if grep -nE 'Feed unavailable|OHLC unavailable|Indicators unavailable' "$F" >/dev/null; then
  say "OK [6] stale/unavailable state copy present"
else
  echo "FAIL [6] no stale/unavailable feed copy"
  FAIL=1
fi

# 7. Legacy stale narrative panels have been demoted/removed.
# These are specific phrases that previously appeared as fake "live"
# claims with hardcoded numbers (Goldman accumulation signal, "+0.024%"
# funding, "$69.6M ETF inflows", MVRV Z-Score 0.41, etc.). They must
# not return.
LEGACY_STALE=(
  'Goldman accumulation signal'
  'Goldman Sachs institutional accumulation'
  'Goldman accumulation signals'
  'ETF inflow April week 1'
  'Clarity Act regulatory catalyst'
  'April 2026 ETF flow reversal'
  'MVRV Z-Score: 0.41'
  '$69.6M inflows first week April'
  '+0.024% — elevated but not extreme'
  'Lightning Network: capacity 5,637 BTC'
  '780 EH/s — record high'
  'Cycle day 730 post-halving'
  'F&G 38 — Fear. Retail exited positions'
  '$70K psychological resistance'
  '200 MA distance: 28%'
)
LEGACY_FAIL=0
for needle in "${LEGACY_STALE[@]}"; do
  if grep -F -- "$needle" "$F" >/dev/null; then
    echo "FAIL [7] legacy stale phrase still present: $needle"
    LEGACY_FAIL=1
  fi
done
if [ "$LEGACY_FAIL" -eq 0 ]; then
  say "OK [7] legacy stale-narrative phrases are gone"
else
  FAIL=1
fi

# 8. The fake "Live Brain Activity Feed" header that claimed "Processing
# Live" has been relabeled. It must explicitly say "Scripted demo" or
# "Demo Loop" rather than implying live processing.
if grep -nE '<span[^>]*color:#3fb950[^>]*>Processing Live</span>' "$F" >/dev/null; then
  echo "FAIL [8] feed still claims 'Processing Live' (green)"
  FAIL=1
else
  say "OK [8] no 'Processing Live' green badge on the feed"
fi
if grep -F "Scripted demo · not live event stream" "$F" >/dev/null \
   && grep -F "Demo Loop" "$F" >/dev/null; then
  say "OK [8b] feed is labeled as scripted demo"
else
  echo "FAIL [8b] feed missing 'Scripted demo' / 'Demo Loop' labels"
  FAIL=1
fi

# 9. SIIE "Prediction Accuracy 65%" card is gone. Browser-side counters
# must NEVER claim a public prediction-accuracy benchmark.
if grep -nE "siieCard\('siie-accuracy', *'65%'" "$F" >/dev/null; then
  echo "FAIL [9] 'siie-accuracy 65%' card is back"
  FAIL=1
else
  say "OK [9] 'siie-accuracy 65%' card not present"
fi
if grep -F "SELF-IMPROVING INTELLIGENCE ENGINE · ACTIVE" "$F" >/dev/null; then
  echo "FAIL [9b] 'SELF-IMPROVING INTELLIGENCE ENGINE · ACTIVE' label is back"
  FAIL=1
else
  say "OK [9b] no 'self-improving · active' label"
fi
if grep -F "BTC BRAIN v5.0 — LIVING INTELLIGENCE SYSTEMS" "$F" >/dev/null; then
  echo "FAIL [9c] 'LIVING INTELLIGENCE SYSTEMS' banner is back"
  FAIL=1
else
  say "OK [9c] no 'living intelligence' banner"
fi
if grep -F "NEURAL EXPANSION ENGINE · v2.0" "$F" >/dev/null; then
  echo "FAIL [9d] 'Neural Expansion Engine v2.0 · LIVE' label is back"
  FAIL=1
else
  say "OK [9d] no 'neural expansion engine v2.0' label"
fi

# 10. Awareness score must NOT mix in a Math.sin oscillation to
# "feel alive" — that's synthetic data dressed up as a measurement.
if grep -nE 'Math\.sin\(Date\.now\(\)\s*/\s*45000\)\s*\*\s*3' "$F" >/dev/null \
 || grep -nE '72\s*\+\s*Math\.round\(Math\.sin\(Date\.now\(\)\s*/\s*30000\)' "$F" >/dev/null \
 || grep -F 'time-based oscillation to make it feel alive' "$F" >/dev/null; then
  echo "FAIL [10] awareness score still has synthetic time-based oscillation"
  FAIL=1
else
  say "OK [10] awareness score has no synthetic oscillation"
fi

# 11. Hardcoded "Goldman accumulation" / "$70,000 psychological" /
# "$68,500" / "$66,600" tactical narrative is gone from the JS panels.
if grep -nE '\\\$70,000 psychological|\\\$68,500|\\\$66,600' "$F" >/dev/null; then
  echo "FAIL [11] hardcoded tactical price narrative still present"
  FAIL=1
else
  say "OK [11] no hardcoded tactical price narrative"
fi

# 12. Hardcoded ATH / 200-DMA values in the levels-map JS are gone.
# The levels map must read from data/public/key_levels.json.
if grep -nE 'price:\s*126296|price:\s*89365' "$F" >/dev/null; then
  echo "FAIL [12] levels-map still has hardcoded 126296 ATH or 89365 200DMA"
  FAIL=1
else
  say "OK [12] no hardcoded 126296 / 89365 levels"
fi
if grep -F "data/public/key_levels.json" "$F" >/dev/null; then
  say "OK [12b] levels-map references key_levels.json"
else
  echo "FAIL [12b] no key_levels.json reference"
  FAIL=1
fi

# 13. Derivatives panel must have a documented public-artifact fallback
# so that fapi.binance.com 451-blocked browsers still show real numbers
# from data/public/derivatives.json.
if grep -F "data/public/derivatives.json" "$F" >/dev/null; then
  say "OK [13] derivatives panel references data/public/derivatives.json"
else
  echo "FAIL [13] no derivatives.json fallback wired"
  FAIL=1
fi

# 14. The "Brain Last Updated: April 5, 2026" stale date footer is gone.
if grep -F "Brain Last Updated" "$F" >/dev/null \
 || grep -F "v4.0 — Full Derivatives Edition" "$F" >/dev/null \
 || grep -F "Next Upgrade:" "$F" >/dev/null; then
  echo "FAIL [14] stale 'Brain Last Updated / Next Upgrade' footer is back"
  FAIL=1
else
  say "OK [14] no stale 'Brain Last Updated' footer"
fi

# 15. The "Autonomous research expansion engine fully operational"
# aspirational milestone is gone; coverage-score growth must not promote
# unbuilt features as guaranteed milestones.
if grep -F "Autonomous research expansion engine fully operational" "$F" >/dev/null \
 || grep -F "Self-correcting prediction model + outcome tracking engine" "$F" >/dev/null; then
  echo "FAIL [15] aspirational unbuilt-feature milestones are back"
  FAIL=1
else
  say "OK [15] no aspirational unbuilt-feature milestones"
fi

# 16. The Live Market chapter description must NOT promise
# "Real-time BTC conditions ... Powered by live market data." in
# unconditional terms — it must clarify the Binance fetch model and
# the unavailable-state behavior.
if grep -F "Real-time BTC conditions across all active timeframes. Auto-refreshes every 30 seconds. Powered by live market data." "$F" >/dev/null; then
  echo "FAIL [16] legacy unconditional 'Powered by live market data' chapter desc is back"
  FAIL=1
else
  say "OK [16] live-market chapter desc is the cleaned-up version"
fi

if [ "$FAIL" -eq 0 ]; then
  echo "ALL TRUTH-SCAN INVARIANTS HELD"
else
  echo "ONE OR MORE TRUTH-SCAN INVARIANTS FAILED"
fi
exit "$FAIL"
