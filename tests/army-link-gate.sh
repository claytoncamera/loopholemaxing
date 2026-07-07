#!/usr/bin/env bash
# tests/army-link-gate.sh
#
# Validates the Army Link / Overseer Command Nexus passkey gate:
#
#   1. /army-link/index.html exists and contains the expected gate UI markers.
#   2. The homepage links to /army-link/ (nav + creation card).
#   3. The plaintext passkey is NOT present anywhere in the public bundle.
#      We never embed the plaintext in this script. Instead we ship the
#      SHA-256 of the passkey and a sliding-window hash scan across the
#      public bundle. If any window hashes to the expected digest, fail.
#
# Exit 0 = clean, exit 1 = at least one check failed.

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0

GATE_FILE="army-link/index.html"
HOME_FILE="index.html"
EXPECTED_DIGEST="c93bb622e9a68df1e5c5540a25231246f31dfa8e911d7983adda1ed6dab35d8d"
# Length of the agreed passkey (string length, not byte length — the passkey is ASCII).
PASSKEY_LEN=17

# ── 1. Page exists ────────────────────────────────────────────────────────────
if [ ! -f "$GATE_FILE" ]; then
  echo "FAIL: $GATE_FILE missing"
  FAIL=1
fi

# ── 2. Gate UI markers present ────────────────────────────────────────────────
if [ -f "$GATE_FILE" ]; then
  REQUIRED_MARKERS=(
    'data-army-link-root'
    'data-gate-card'
    'data-nexus-panel'
    'id="passkey-input"'
    'crypto.subtle.digest'
    'SHA-256'
    'sessionStorage'
    'Overseer Command Nexus'
    'Soft'  # part of "Soft Gate" / soft-gate disclaimer
    'no trading'
    # Phase B: server-mode + soft-gate fallback markers
    'data-api-origin'
    'data-api-path'
    'hubapi.loopholemaxing.com'
    '/api/v1/army-link/unlock'
    'data-auth-mode'
    'server auth not active yet'
    'no order routing'
    'no broker'
  )
  for marker in "${REQUIRED_MARKERS[@]}"; do
    if ! grep -q -F -- "$marker" "$GATE_FILE"; then
      echo "FAIL: $GATE_FILE missing required marker: $marker"
      FAIL=1
    fi
  done

  # Must contain the expected digest (the gate compares against it).
  if ! grep -q -F -- "$EXPECTED_DIGEST" "$GATE_FILE"; then
    echo "FAIL: $GATE_FILE does not contain the expected SHA-256 digest"
    FAIL=1
  fi

  # Must NOT log the input. Block obvious leakage patterns.
  LEAK_PATTERNS=(
    'console.log(value'
    'console.log(input'
    'console.log(passkey'
    'console.log(pass'
    'console.log(document.getElementById("passkey-input")'
    'localStorage.setItem("passkey'
    'localStorage.setItem("army_link_passkey'
  )
  for lp in "${LEAK_PATTERNS[@]}"; do
    if grep -q -F -- "$lp" "$GATE_FILE"; then
      echo "FAIL: $GATE_FILE contains a passkey-leak pattern: $lp"
      FAIL=1
    fi
  done
fi

# ── 3. Homepage must NOT surface /army-link/ ─────────────────────────────────
# Deliberate access-control decision (2026-06-29 gating pass): internal/ops
# tools stay OFF the public portfolio. /army-link/ is noindex + robots-
# disallowed and must not be linked or named on the public homepage.
if [ -f "$HOME_FILE" ]; then
  if grep -q -F -- '/army-link/' "$HOME_FILE"; then
    echo "FAIL: $HOME_FILE links to /army-link/ (must stay unlinked from the public homepage)"
    FAIL=1
  fi
  if grep -q -F -- 'Army Link' "$HOME_FILE"; then
    echo "FAIL: $HOME_FILE mentions 'Army Link' (must stay unnamed on the public homepage)"
    FAIL=1
  fi
fi

# ── 3b. Gating hardening: robots disallow + noindex meta ─────────────────────
if [ -f "robots.txt" ] && ! grep -q -F -- 'Disallow: /army-link/' robots.txt; then
  echo "FAIL: robots.txt does not disallow /army-link/"
  FAIL=1
fi
if [ -f "$GATE_FILE" ] && ! grep -q -F -- 'noindex' "$GATE_FILE"; then
  echo "FAIL: $GATE_FILE missing noindex meta"
  FAIL=1
fi

# ── 4. Plaintext-passkey absence scan ─────────────────────────────────────────
# Sliding-window SHA-256 over each file in the public bundle.
# We never write the plaintext here — only the digest.

PUBLIC_FILES=()
while IFS= read -r f; do
  PUBLIC_FILES+=("$f")
done < <(git ls-files \
  'index.html' '404.html' 'styles.css' \
  'army-link/**' \
  'btc-brain/index.html' \
  'nba-brain/**' \
  'vault/**' 'ultron/**' 'formix/**' 'uae/**' \
  2>/dev/null)

if [ "${#PUBLIC_FILES[@]}" -eq 0 ]; then
  # Fallback if git ls-files glob support is limited.
  while IFS= read -r f; do
    PUBLIC_FILES+=("$f")
  done < <(find index.html 404.html styles.css army-link btc-brain/index.html nba-brain vault ultron formix uae \
    -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.mjs' -o -name '*.md' -o -name '*.json' -o -name '*.txt' \) \
    2>/dev/null)
fi

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "SKIP: python not available — sliding-window passkey scan skipped"
else
  PY="$(command -v python3 || command -v python)"
  # Pass file list via stdin, expected digest + length via env. Plaintext never appears.
  EXPECTED_DIGEST="$EXPECTED_DIGEST" PASSKEY_LEN="$PASSKEY_LEN" "$PY" - "${PUBLIC_FILES[@]}" <<'PYEOF'
import hashlib
import os
import sys

expected = os.environ["EXPECTED_DIGEST"].lower()
n = int(os.environ["PASSKEY_LEN"])
files = sys.argv[1:]

bad = []
for path in files:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except (OSError, IOError):
        continue
    if len(data) < n:
        continue
    # Sliding window over raw bytes. The passkey is ASCII so byte-length == char-length.
    # Use a rolling slice — fine for this repo's size.
    L = len(data)
    for i in range(0, L - n + 1):
        window = data[i:i + n]
        # Quick filter: skip windows that are obviously not the passkey
        # (e.g., contain a NUL or newline) before hashing.
        if b"\x00" in window or b"\n" in window or b"\r" in window:
            continue
        if hashlib.sha256(window).hexdigest() == expected:
            bad.append(path)
            break

if bad:
    print("FAIL: plaintext passkey detected in public bundle (paths only):")
    for p in bad:
        print("  " + p)
    sys.exit(1)
print("OK: no plaintext passkey in public bundle")
sys.exit(0)
PYEOF
  PY_RC=$?
  if [ "$PY_RC" -ne 0 ]; then
    FAIL=1
  fi
fi

if [ "$FAIL" -eq 0 ]; then
  echo "OK: army-link gate checks passed"
fi
exit "$FAIL"
