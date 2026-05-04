#!/usr/bin/env bash
# Offline test for safe_push.sh.
#
# Sets up a local "remote" bare repo and a working clone, then exercises:
#   1. happy path: push with no contention succeeds.
#   2. nothing staged: helper exits 0 with no commit.
#   3. non-fast-forward race: a competing commit lands on the remote
#      before our push; helper rebases (no conflict) and retries.
#   4. conflict on the same artifact path: helper aborts loudly without
#      force-pushing.
#
# Run: bash .github/scripts/test_safe_push.sh
# Designed to run anywhere bash + git are available; no network needed.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SAFE_PUSH="${HERE}/safe_push.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REMOTE="${TMP}/remote.git"
LOCAL="${TMP}/local"
OTHER="${TMP}/other"

git init --bare -b main "$REMOTE" >/dev/null

# Seed the remote with an initial commit via OTHER.
git clone "$REMOTE" "$OTHER" >/dev/null 2>&1
cd "$OTHER"
git config user.email "seed@example.com"
git config user.name  "seed"
echo "seed" > README.md
git add README.md
git commit -m "seed" >/dev/null
git push origin main >/dev/null 2>&1
cd - >/dev/null

git clone "$REMOTE" "$LOCAL" >/dev/null 2>&1
cd "$LOCAL"
git config user.email "bot@example.com"
git config user.name  "bot"

# We want safe_push to retry quickly and few times during tests.
export SAFE_PUSH_MAX_RETRIES=4
export SAFE_PUSH_INITIAL_SLEEP=0

echo "── case 1: happy path ──"
mkdir -p artifacts
echo '{"v":1}' > artifacts/a.json
git add artifacts/a.json
export GITHUB_OUTPUT="$TMP/case1.outputs"
: > "$GITHUB_OUTPUT"
"$SAFE_PUSH" "case1: add a.json"
git fetch origin main >/dev/null 2>&1
git diff --quiet origin/main -- artifacts/a.json || { echo "case1 FAIL: a.json not on remote"; exit 1; }
grep -q '^pushed=true$' "$GITHUB_OUTPUT" || { echo "case1 FAIL: expected pushed=true in GITHUB_OUTPUT"; cat "$GITHUB_OUTPUT"; exit 1; }
# pushed_sha must be present on success and must equal the SHA we just pushed.
case1_pushed_sha="$(grep '^pushed_sha=' "$GITHUB_OUTPUT" | cut -d= -f2 || true)"
[ -n "$case1_pushed_sha" ] || { echo "case1 FAIL: pushed_sha missing in GITHUB_OUTPUT"; cat "$GITHUB_OUTPUT"; exit 1; }
[ "$case1_pushed_sha" = "$(git rev-parse origin/main)" ] || {
  echo "case1 FAIL: pushed_sha (${case1_pushed_sha}) != origin/main tip ($(git rev-parse origin/main))"
  exit 1
}
echo "case1 PASS"

echo "── case 2: nothing staged ──"
export GITHUB_OUTPUT="$TMP/case2.outputs"
: > "$GITHUB_OUTPUT"
"$SAFE_PUSH" "case2: should be no-op"
grep -q '^pushed=false$' "$GITHUB_OUTPUT" || { echo "case2 FAIL: expected pushed=false in GITHUB_OUTPUT"; cat "$GITHUB_OUTPUT"; exit 1; }
# Nothing was pushed, so pushed_sha must NOT be emitted — otherwise the
# downstream deploy could be tricked into asserting a stale SHA.
if grep -q '^pushed_sha=' "$GITHUB_OUTPUT"; then
  echo "case2 FAIL: pushed_sha must not be emitted when nothing was pushed"
  cat "$GITHUB_OUTPUT"
  exit 1
fi
echo "case2 PASS"

echo "── case 3: non-fast-forward, no conflict ──"
# Land a competing commit on the remote that touches a *different* file.
cd "$OTHER"; git pull origin main >/dev/null 2>&1
echo "competing" > competing.txt
git add competing.txt
git commit -m "competing change" >/dev/null
git push origin main >/dev/null 2>&1
cd "$LOCAL"
echo '{"v":2}' > artifacts/b.json
git add artifacts/b.json
export GITHUB_OUTPUT="$TMP/case3.outputs"
: > "$GITHUB_OUTPUT"
"$SAFE_PUSH" "case3: add b.json with race"
git fetch origin main >/dev/null 2>&1
git diff --quiet origin/main -- artifacts/b.json || { echo "case3 FAIL: b.json not on remote"; exit 1; }
git diff --quiet origin/main -- competing.txt   || { echo "case3 FAIL: competing.txt missing locally"; exit 1; }
grep -q '^pushed=true$' "$GITHUB_OUTPUT" || { echo "case3 FAIL: expected pushed=true after rebase+retry"; cat "$GITHUB_OUTPUT"; exit 1; }
# pushed_sha must reflect the post-rebase commit that landed on origin.
case3_pushed_sha="$(grep '^pushed_sha=' "$GITHUB_OUTPUT" | cut -d= -f2 || true)"
[ -n "$case3_pushed_sha" ] || { echo "case3 FAIL: pushed_sha missing after rebase+retry"; cat "$GITHUB_OUTPUT"; exit 1; }
[ "$case3_pushed_sha" = "$(git rev-parse origin/main)" ] || {
  echo "case3 FAIL: pushed_sha (${case3_pushed_sha}) != origin/main tip ($(git rev-parse origin/main))"
  exit 1
}
echo "case3 PASS"

echo "── case 4: conflict on same artifact path → loud failure, no force-push ──"
# Our local commit will rewrite artifacts/a.json. Meanwhile OTHER also
# rewrites artifacts/a.json on the remote. The rebase will conflict and
# safe_push must abort.
cd "$OTHER"; git pull origin main >/dev/null 2>&1
echo '{"v":"from-other"}' > artifacts/a.json
git add artifacts/a.json
git commit -m "other rewrites a.json" >/dev/null
git push origin main >/dev/null 2>&1
cd "$LOCAL"
echo '{"v":"from-local"}' > artifacts/a.json
git add artifacts/a.json
export GITHUB_OUTPUT="$TMP/case4.outputs"
: > "$GITHUB_OUTPUT"
set +e
"$SAFE_PUSH" "case4: should fail loudly" >"$TMP/case4.log" 2>&1
rc=$?
set -e
cat "$TMP/case4.log"
if [ "$rc" -eq 0 ]; then
  echo "case4 FAIL: safe_push should have failed but returned 0"
  exit 1
fi
grep -q "refusing to force-push" "$TMP/case4.log" || {
  echo "case4 FAIL: missing 'refusing to force-push' message"
  exit 1
}
# Confirm remote tip still matches OTHER's version, NOT our local rewrite.
git fetch origin main >/dev/null 2>&1
remote_a="$(git show origin/main:artifacts/a.json)"
[ "$remote_a" = '{"v":"from-other"}' ] || {
  echo "case4 FAIL: remote was modified despite conflict"
  exit 1
}
# On loud conflict failure we never wrote pushed=true; the deploy gate
# in the calling workflow must therefore not fire. pushed_sha must
# likewise be absent so a misconfigured caller cannot deploy a stale tip.
if grep -q '^pushed=true$' "$GITHUB_OUTPUT"; then
  echo "case4 FAIL: pushed=true was emitted on loud-failure path"
  cat "$GITHUB_OUTPUT"
  exit 1
fi
if grep -q '^pushed_sha=' "$GITHUB_OUTPUT"; then
  echo "case4 FAIL: pushed_sha was emitted on loud-failure path"
  cat "$GITHUB_OUTPUT"
  exit 1
fi
echo "case4 PASS"

echo
echo "All safe_push test cases passed."
