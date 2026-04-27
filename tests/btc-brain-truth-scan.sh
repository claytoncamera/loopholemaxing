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

if [ "$FAIL" -eq 0 ]; then
  echo "ALL TRUTH-SCAN INVARIANTS HELD"
else
  echo "ONE OR MORE TRUTH-SCAN INVARIANTS FAILED"
fi
exit "$FAIL"
