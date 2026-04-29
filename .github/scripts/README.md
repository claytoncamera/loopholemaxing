# `.github/scripts/`

Helper scripts for the workflows in `.github/workflows/`.

## `safe_push.sh`

Safe `git push` wrapper for workflows that commit generated artifacts to
`main`. Use it any time multiple scheduled workflows might push at the
same time.

### Why

The repo has four scheduled workflows that all push artifacts to `main`:

| Workflow                    | Cron               | Files it commits                                      |
| --------------------------- | ------------------ | ----------------------------------------------------- |
| `btc-data-snapshot.yml`     | `13,43 * * * *`    | `btc-brain/data/public/*.json`                        |
| `btc-ledger-resolve.yml`    | `7 * * * *`        | `btc-brain/ledger/data/resolutions.jsonl`, `accuracy.json` |
| `btc-ledger-issue.yml`      | `17 * * * *`       | `btc-brain/ledger/data/{forecasts,resolutions}.jsonl`, `accuracy.json` |
| `btc-briefing-archive.yml`  | `17 10 * * *`      | `btc-brain/data/public/briefings/*.json`              |

Per-workflow `concurrency:` groups prevent a workflow from racing
against *itself*, but two **different** workflows can finish their
generation step within the same second and both `git push` to `main`.
The second push hits a non-fast-forward and fails:

```
 ! [rejected]        main -> main (fetch first)
hint: Updates were rejected because the remote contains work that you do not have locally.
```

This is what produced the failures observed after the live-completion
wave merge — the actual generation steps all succeeded, only the final
`git push` step failed.

### What it does

1. Stage the generated artifacts and call the helper with a commit
   message. If nothing is staged the helper exits 0 (no-op).
2. Commit locally.
3. `git push` once. If it succeeds, done.
4. On non-fast-forward rejection: `git fetch origin main` (auto-unshallow
   if needed) → `git rebase origin/main` → push again.
5. Up to `SAFE_PUSH_MAX_RETRIES` times (default 5), with exponential
   backoff plus small randomized jitter to de-stagger retries.
6. **If the rebase conflicts** (another run wrote the same artifact path
   with different content) the helper logs the conflicting files,
   aborts the rebase, and exits non-zero. It **never force-pushes** —
   that would silently overwrite the other run's generated data and
   make the failure invisible.

### Usage

```yaml
- name: Commit ledger updates
  run: |
    git config user.name  "btc-brain-bot"
    git config user.email "btc-brain-bot@users.noreply.github.com"
    git add path/to/artifact1 path/to/artifact2
    .github/scripts/safe_push.sh "chore(ledger): refresh"
```

The job needs `permissions: contents: write` and a checkout step that
authenticates the push (the default `actions/checkout@v4` token works).

### Tunables (env vars)

| Variable                  | Default | Meaning                                      |
| ------------------------- | ------- | -------------------------------------------- |
| `SAFE_PUSH_MAX_RETRIES`   | `5`     | Max push attempts before giving up.          |
| `SAFE_PUSH_INITIAL_SLEEP` | `2`     | Base seconds for exponential backoff.        |
| `SAFE_PUSH_BRANCH`        | `main`  | Target branch.                               |

### `pushed` step output (for the Pages deploy gate)

When `safe_push.sh` runs inside a GitHub Actions step it writes
`pushed=true` (push succeeded) or `pushed=false` (nothing was staged) to
`$GITHUB_OUTPUT`. On loud-failure paths (rebase conflict, retries
exhausted, non-retryable push error) the helper exits non-zero **without**
emitting `pushed=true`, so a downstream `if: needs.<job>.outputs.pushed
== 'true'` gate will not fire.

This is what the artifact-committing workflows
(`btc-data-snapshot.yml`, `btc-ledger-issue.yml`, `btc-ledger-resolve.yml`,
`btc-briefing-archive.yml`) use to invoke the reusable `pages.yml`
deploy via `workflow_call` immediately after a successful push. Without
this in-run deploy, GitHub's rule that **commits made by `GITHUB_TOKEN`
do not trigger downstream workflows** would leave the public Pages
artifacts stale until the next human commit.

To consume the output, give the commit step an `id`, expose a job
output, and gate a deploy job on it:

```yaml
jobs:
  snapshot:
    outputs:
      pushed: ${{ steps.commit.outputs.pushed }}
    steps:
      - name: Commit snapshot updates
        id: commit
        run: |
          git add path/to/artifact.json
          .github/scripts/safe_push.sh "chore(data): refresh"

  deploy-pages:
    needs: snapshot
    if: needs.snapshot.outputs.pushed == 'true'
    uses: ./.github/workflows/pages.yml
    permissions:
      contents: read
      pages: write
      id-token: write
```

### Truth-gate guarantees

The helper does not change any model output, forecast values, or
accuracy thresholds. It only handles the transport layer (commit +
push). Generated artifacts are preserved across the rebase because
`git rebase` replays our single commit verbatim onto the new remote
tip; on conflict it aborts rather than touching the artifact bytes.

### Tests

`test_safe_push.sh` is an offline test harness (no network, no GitHub
required). It builds a local bare repo plus two clones and exercises
four scenarios, asserting both the on-disk remote state *and* the
`pushed=` value written to `$GITHUB_OUTPUT`:

1. happy-path push → `pushed=true`.
2. nothing-staged no-op → `pushed=false`.
3. non-fast-forward race against an unrelated file → rebase + retry
   succeeds → `pushed=true`.
4. conflict on the same artifact path → loud failure, remote tip
   unchanged, `pushed=true` is **not** emitted (so the deploy gate
   won't fire).

Run it:

```
bash .github/scripts/test_safe_push.sh
```

If you change `safe_push.sh`, run the tests before opening a PR.
