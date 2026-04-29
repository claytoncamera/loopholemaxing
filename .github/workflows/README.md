# `.github/workflows/`

| Workflow                     | Cron               | What it does                                               |
| ---------------------------- | ------------------ | ---------------------------------------------------------- |
| `pages.yml`                  | on push to `main`, `workflow_dispatch`, `workflow_call` | Builds + deploys GitHub Pages site. |
| `btc-data-snapshot.yml`      | `13,43 * * * *`    | Refreshes `btc-brain/data/public/*.json`, commits, deploys Pages. |
| `btc-ledger-resolve.yml`     | `7 * * * *`        | Resolves due forecasts, refreshes `accuracy.json`, commits, deploys Pages. |
| `btc-ledger-issue.yml`       | `17 * * * *`       | Issues new shadow forecasts + resolves due, commits, deploys Pages. |
| `btc-briefing-archive.yml`   | `17 10 * * *`      | Builds daily briefing JSON, commits, deploys Pages. |
| `btc-brain-daily.yml`        | `0 10 * * *`       | Sends daily intelligence email. Does **not** commit. |

## Why each scheduled workflow deploys Pages directly

GitHub deliberately does **not** trigger another workflow run from a
`push` event whose commit was made by the default `GITHUB_TOKEN`
([docs][gh-token-trigger]). That rule prevents recursive workflow
loops, but it also means our hourly bot commits to `main` do **not**
fire `pages.yml`'s `on: push` trigger.

Symptom (the live ops gap that motivated this design):

> Scheduled workflows succeed for hours and `main` advances on schedule,
> but the public Pages site keeps serving artifacts from the last
> *human* push — sometimes 12–24h stale.

Fix: each artifact-committing workflow invokes the reusable Pages
deploy *in the same run* via `workflow_call`, gated on whether the
commit step actually pushed. The flow is:

```
schedule  ─►  job: <generate>          (writes artifacts)
              │
              └─► step: commit (id: commit)
                    └─ runs .github/scripts/safe_push.sh
                       └─ emits pushed=true|false to $GITHUB_OUTPUT

         if pushed == 'true':
              job: deploy-pages
                    └─ uses: ./.github/workflows/pages.yml
                       (calls the reusable Pages workflow in-run)
```

Properties this gives us:

- **No new secrets.** The reusable workflow runs under the same
  `GITHUB_TOKEN`. Pages permissions (`pages: write`, `id-token: write`)
  are scoped at the called-workflow boundary.
- **No infinite loop.** A bot push from one of these workflows would
  not have triggered `pages.yml`'s `on: push` anyway (token rule above)
  — and `workflow_call` runs are tied to the parent run, not the push,
  so they cannot recurse into themselves.
- **No force-push, no `safe_push` regressions.** The deploy gate is
  driven by `safe_push`'s existing exit semantics: it only emits
  `pushed=true` on a successful push, and emits nothing on the loud
  conflict failure path.
- **No deploys on no-op runs.** When nothing was staged
  (`pushed=false`) the deploy job is skipped; concurrent runs that
  rebase to a no-op don't waste a Pages deploy slot.
- **Concurrency safety.** `pages.yml` keeps its
  `concurrency: group: pages, cancel-in-progress: false` so multiple
  scheduled workflows finishing close together serialize their deploys
  rather than canceling each other — we always end on the most recent
  artifact set.
- **Human pushes still work.** `pages.yml` keeps `on: push` and
  `workflow_dispatch`, so merges to `main` and manual redeploys behave
  exactly as before.

See `../scripts/README.md` for the `safe_push.sh` contract and tests.

[gh-token-trigger]: https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow
