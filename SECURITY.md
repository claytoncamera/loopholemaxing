# Security Checklist — loopholemaxing

This file documents the security posture for the public BTC Intelligence Brain
and adjacent assets in this repository.

## Public surface

The repository is published as a static site (GitHub Pages). Anything committed
here is reachable by anyone on the open internet, including:

- `btc-brain/index.html`
- `index.html`, `mms-hub/`, `nba-brain/`, `vault/`, `ultron/`, `formix/`, `uae/`
- compiled JS bundles inside `nba-brain/assets/`

Never commit a value you would not paste into a public chatroom.

`mms-hub/` is only a public gateway page. The real MMS HUB must stay on an
authenticated server-side service such as `https://hub.loopholemaxing.com`;
do not copy control-center HTML, runtime data, API responses, or credentials
into this static repository.

## Secret handling

1. **Never hardcode secrets** in any file under version control.
2. Real secrets live only in:
   - GitHub Actions repository secrets (`Settings → Secrets and variables → Actions`).
     The active workflow references `${{ secrets.RESEND_API_KEY }}`.
   - Local `.env` files (gitignored).
3. `.env`, `.env.*`, `*.pem`, `*.key`, and `secrets/` are gitignored.
   Confirm before each commit:
   ```
   git ls-files | grep -E '(^|/)\.env($|\.)' && echo "FAIL: .env tracked"
   ```
4. If a secret has touched any commit, treat it as compromised and rotate it
   immediately — even if the commit was force-removed. The rotation, not the
   delete, is what restores safety.

## Pre-commit secret scan

Run before every push (no secret values are ever printed; only file paths and
match types):

```bash
# Block obvious token shapes from entering the repo
git diff --cached | grep -E \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'sk_live_[0-9a-zA-Z]{16,}' \
  -e 'sk_test_[0-9a-zA-Z]{16,}' \
  -e 'xox[baprs]-[0-9a-zA-Z-]{10,}' \
  -e 'ghp_[0-9a-zA-Z]{20,}' \
  -e 'github_pat_[0-9a-zA-Z_]{20,}' \
  -e 'AIza[0-9A-Za-z_-]{30,}' \
  -e 'ya29\.[0-9A-Za-z_-]{20,}' \
  -e 'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' \
  && { echo "ABORT: token-shape match in staged diff"; exit 1; }
```

The `tests/secret-scan.sh` script wraps this for CI / one-shot use; it returns
exit code 1 on hit and prints only file paths and the matched pattern *name*,
never the value.

## Rotation procedure

If you suspect any secret has leaked:

1. **Rotate the credential at the provider first** (Resend, GitHub, etc.).
2. Replace the GitHub Actions secret with the new value.
3. Audit access logs at the provider for the leak window.
4. Document the incident in `logs/` (timestamp, provider, what rotated; never
   include the old or new secret value).

## What about ledger-backed metrics?

The public BTC Brain currently displays **no** ledger-backed accuracy figures.
Until a tamper-evident, externally-verifiable prediction record is published
(signed timestamps, public hashes, immutable storage), the page must label
all confidence/accuracy/IQ/analog-match values as experimental. See the P0
truth pass in `btc-brain/index.html` for the disclaimer banner and the per-
panel relabeling.
