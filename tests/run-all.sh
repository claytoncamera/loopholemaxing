#!/usr/bin/env bash
# tests/run-all.sh — runs every static + behavioural check in this directory.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Truth scan (btc-brain/index.html) =="
bash tests/btc-brain-truth-scan.sh
T1=$?

echo
echo "== Secret scan (public bundle) =="
bash tests/secret-scan.sh
T2=$?

echo
echo "== Closed-candle behaviour =="
if command -v node >/dev/null 2>&1; then
  node tests/closed-candles.spec.mjs
  T3=$?
else
  echo "SKIP: node not installed"
  T3=0
fi

echo
if [ $T1 -eq 0 ] && [ $T2 -eq 0 ] && [ $T3 -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  exit 0
fi
echo "FAILED: truth=$T1 secret=$T2 closed=$T3"
exit 1
