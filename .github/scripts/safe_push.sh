#!/usr/bin/env bash
# Safe push helper for GitHub Actions workflows that commit generated
# artifacts to main.
#
# Why this exists: several workflows (data snapshot, ledger issue, ledger
# resolve, briefing archive) all push to main on overlapping schedules.
# Even though each workflow uses a per-workflow `concurrency:` group, two
# *different* workflows can finish their generation step at the same
# second and race to push, producing a non-fast-forward rejection like:
#
#     ! [rejected]        main -> main (fetch first)
#     hint: Updates were rejected because the remote contains work that
#           you do not have locally.
#
# Pattern used here:
#   1. Stage + commit the generated artifacts on a local branch.
#   2. Try `git push`. If it succeeds, we are done.
#   3. If it is rejected, fetch origin/main and rebase our single commit
#      on top of it. Rebase is *autostash*-safe and preserves our
#      generated artifacts.
#   4. Retry the push with a small backoff. Repeat up to MAX_RETRIES.
#   5. If a rebase conflict touches the same generated files (i.e. two
#      runs both wrote a different version of the same artifact), abort
#      loudly instead of force-pushing. This makes the failure visible
#      so a human can investigate, rather than silently overwriting the
#      other run's work.
#
# Usage (inside a workflow step):
#
#     - name: Commit ledger updates
#       run: |
#         git config user.name  "btc-brain-bot"
#         git config user.email "btc-brain-bot@users.noreply.github.com"
#         git add path/to/artifact1 path/to/artifact2
#         .github/scripts/safe_push.sh "chore(ledger): refresh"
#
# The helper itself decides whether anything is staged; if nothing is
# staged it exits 0 with a "no changes" message.
#
# Environment overrides (all optional):
#   SAFE_PUSH_MAX_RETRIES    default 5
#   SAFE_PUSH_INITIAL_SLEEP  default 2  (seconds, exponential backoff base)
#   SAFE_PUSH_BRANCH         default `main`
#
# The helper never force-pushes and never bypasses hooks.

set -euo pipefail

COMMIT_MSG="${1:-}"
if [ -z "$COMMIT_MSG" ]; then
  echo "safe_push: commit message is required as the first argument" >&2
  exit 2
fi

MAX_RETRIES="${SAFE_PUSH_MAX_RETRIES:-5}"
INITIAL_SLEEP="${SAFE_PUSH_INITIAL_SLEEP:-2}"
BRANCH="${SAFE_PUSH_BRANCH:-main}"

# Emit a `pushed=<true|false>` line to $GITHUB_OUTPUT (when running inside
# a GitHub Actions step) so a downstream job can gate a Pages deploy on
# whether this run actually advanced origin/main. Safe no-op when the
# variable is unset (local runs, tests).
emit_pushed() {
  local value="$1"
  if [ -n "${GITHUB_OUTPUT:-}" ] && [ -w "$GITHUB_OUTPUT" ]; then
    echo "pushed=${value}" >> "$GITHUB_OUTPUT"
  fi
}

# Emit the SHA we just pushed to origin/$BRANCH so the downstream Pages
# deploy can assert that what it is about to publish includes our commit
# (i.e., that the post-push tip of main has not regressed). Safe no-op
# when $GITHUB_OUTPUT is unset.
emit_pushed_sha() {
  local sha="$1"
  if [ -n "${GITHUB_OUTPUT:-}" ] && [ -w "$GITHUB_OUTPUT" ]; then
    echo "pushed_sha=${sha}" >> "$GITHUB_OUTPUT"
  fi
}

if git diff --cached --quiet; then
  echo "safe_push: nothing staged; skipping commit and push."
  emit_pushed false
  exit 0
fi

# Capture the staged paths now, before we commit, so that if a rebase
# later conflicts we can report exactly which artifacts collided.
STAGED_FILES="$(git diff --cached --name-only)"

git commit -m "$COMMIT_MSG"

attempt=0
sleep_s="$INITIAL_SLEEP"
while : ; do
  attempt=$((attempt + 1))
  echo "safe_push: push attempt ${attempt}/${MAX_RETRIES} to origin/${BRANCH}…"

  # Capture push output so we can distinguish non-fast-forward from
  # other failures (auth, network, etc.) — only the former should retry.
  push_out="$(mktemp)"
  if git push origin "HEAD:${BRANCH}" >"$push_out" 2>&1; then
    cat "$push_out"
    rm -f "$push_out"
    pushed_sha="$(git rev-parse HEAD)"
    echo "safe_push: push succeeded on attempt ${attempt} (sha=${pushed_sha})."
    emit_pushed true
    emit_pushed_sha "$pushed_sha"
    exit 0
  fi

  cat "$push_out"
  if ! grep -qE 'rejected|non-fast-forward|fetch first|stale info' "$push_out"; then
    echo "safe_push: push failed for a reason other than non-fast-forward; aborting." >&2
    rm -f "$push_out"
    exit 1
  fi
  rm -f "$push_out"

  if [ "$attempt" -ge "$MAX_RETRIES" ]; then
    echo "safe_push: exhausted ${MAX_RETRIES} retries; aborting without force-push." >&2
    exit 1
  fi

  echo "safe_push: non-fast-forward; fetching and rebasing on origin/${BRANCH}."
  # On shallow clones (`fetch-depth: 1` in workflows) we may not have
  # enough history to compute a merge-base if main has advanced beyond
  # what we cloned. Unshallow on first retry; subsequent fetches are
  # cheap.
  if [ -f "$(git rev-parse --git-dir)/shallow" ]; then
    git fetch --unshallow origin "$BRANCH" || git fetch origin "$BRANCH"
  else
    git fetch origin "$BRANCH"
  fi

  # Rebase our single commit on top of the freshly fetched tip. If the
  # other run touched the same generated files we will get a conflict;
  # in that case we bail out loudly instead of forcing.
  if ! git rebase "origin/${BRANCH}"; then
    echo "safe_push: rebase conflict against origin/${BRANCH}." >&2
    echo "safe_push: conflicting files:" >&2
    git diff --name-only --diff-filter=U >&2 || true
    echo "safe_push: staged generated files were:" >&2
    echo "$STAGED_FILES" >&2
    git rebase --abort || true
    echo "safe_push: refusing to force-push; failing the job so a human can investigate." >&2
    exit 1
  fi

  # Small randomized backoff before retrying so concurrent jobs do not
  # immediately collide again.
  jitter=$(( RANDOM % 3 ))
  total_sleep=$(( sleep_s + jitter ))
  echo "safe_push: rebased; sleeping ${total_sleep}s before next push attempt."
  sleep "$total_sleep"
  sleep_s=$(( sleep_s * 2 ))
done
