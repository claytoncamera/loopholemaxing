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
echo "== Phase 1 ledger tests =="
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  PY="$(command -v python3 || command -v python)"
  ( cd "$ROOT/btc-brain/ledger" && "$PY" tests/test_ledger.py >/tmp/p1.log 2>&1 )
  T4=$?
  if [ $T4 -ne 0 ]; then
    echo "FAILED phase 1 ledger:"; sed 's/^/  /' /tmp/p1.log
  else
    echo "OK: phase 1 ledger"
  fi
else
  echo "SKIP: python not installed"
  T4=0
fi

echo
echo "== Phase 2 data foundation tests =="
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  PY="$(command -v python3 || command -v python)"
  ( cd "$ROOT/btc-brain/data" && "$PY" tests/test_phase2.py >/tmp/p2.log 2>&1 )
  T5=$?
  if [ $T5 -ne 0 ]; then
    echo "FAILED phase 2 data:"; sed 's/^/  /' /tmp/p2.log
  else
    echo "OK: phase 2 data foundation"
  fi
else
  echo "SKIP: python not installed"
  T5=0
fi

echo
echo "== Phase 3 model baselines tests =="
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  PY="$(command -v python3 || command -v python)"
  ( cd "$ROOT/btc-brain/models" && "$PY" tests/test_phase3.py >/tmp/p3.log 2>&1 )
  T6=$?
  if [ $T6 -ne 0 ]; then
    echo "FAILED phase 3 models:"; sed 's/^/  /' /tmp/p3.log
  else
    echo "OK: phase 3 model baselines"
  fi
else
  echo "SKIP: python not installed"
  T6=0
fi

echo
echo "== Phase 4 regime + drift tests =="
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  PY="$(command -v python3 || command -v python)"
  ( cd "$ROOT/btc-brain/models" && "$PY" phase4/tests/test_phase4.py >/tmp/p4.log 2>&1 )
  T7=$?
  if [ $T7 -ne 0 ]; then
    echo "FAILED phase 4 regime/drift:"; sed 's/^/  /' /tmp/p4.log
  else
    echo "OK: phase 4 regime + drift"
  fi
else
  echo "SKIP: python not installed"
  T7=0
fi

echo
echo "== Phase 7 trust scan (btc-brain/index.html) =="
bash tests/phase7-trust-scan.sh
T8=$?

echo
if [ $T1 -eq 0 ] && [ $T2 -eq 0 ] && [ $T3 -eq 0 ] && [ $T4 -eq 0 ] && [ $T5 -eq 0 ] && [ $T6 -eq 0 ] && [ $T7 -eq 0 ] && [ $T8 -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  exit 0
fi
echo "FAILED: truth=$T1 secret=$T2 closed=$T3 ledger=$T4 data=$T5 models=$T6 phase4=$T7 phase7=$T8"
exit 1
