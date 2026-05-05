#!/usr/bin/env bash
# tests/secret-scan.sh
# Public-bundle secret scanner for the loopholemaxing repo.
# Prints only file paths and the matched pattern *name* — never the secret value.
# Exit 0 = clean, exit 1 = at least one match.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Patterns: name | regex
# Keep this list defensive — it should over-flag rather than miss real secrets.
PATTERNS=(
  "AWS_ACCESS_KEY|AKIA[0-9A-Z]{16}"
  "STRIPE_LIVE|sk_live_[0-9a-zA-Z]{16,}"
  "STRIPE_TEST|sk_test_[0-9a-zA-Z]{16,}"
  "SLACK_TOKEN|xox[baprs]-[0-9a-zA-Z-]{10,}"
  "GITHUB_PAT_CLASSIC|ghp_[0-9a-zA-Z]{20,}"
  "GITHUB_PAT_FINE|github_pat_[0-9a-zA-Z_]{20,}"
  "GOOGLE_API_KEY|AIza[0-9A-Za-z_-]{30,}"
  "GOOGLE_OAUTH|ya29\\.[0-9A-Za-z_-]{20,}"
  "JWT|eyJ[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,}"
  "PRIVATE_KEY|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

FAIL=0
SCAN_GLOB=( "btc-brain/index.html" "index.html" "mms-hub" "ultron/index.html" "vault/index.html" "nba-brain" "formix" "uae" )

for entry in "${PATTERNS[@]}"; do
  name="${entry%%|*}"
  regex="${entry#*|}"
  # Run grep across the public bundle. -l prints filenames only.
  if hits=$(grep -rlE "$regex" "${SCAN_GLOB[@]}" 2>/dev/null); then
    if [ -n "$hits" ]; then
      echo "FAIL: pattern=$name matched in:"
      while IFS= read -r f; do
        # Print path + line numbers only, not the matching content.
        nums=$(grep -nE "$regex" "$f" 2>/dev/null | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
        echo "  $f (lines: ${nums:-?})"
      done <<<"$hits"
      FAIL=1
    fi
  fi
done

# Also confirm .env files are not tracked.
if git ls-files 2>/dev/null | grep -E '(^|/)\.env($|\.)' | grep -v '\.example$' >/dev/null; then
  echo "FAIL: an .env file is tracked in git"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo "OK: no token-shaped strings found in the public bundle"
fi
exit "$FAIL"
