# BTC Brain Automation Engine — Setup Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    OPTION A: GitHub Actions                  │
│           (Recommended — free, zero infrastructure)          │
│                                                              │
│  GitHub Scheduler (cron 6AM EDT)                            │
│    → Spins up Ubuntu VM (30 sec)                            │
│    → Runs engine.py                                         │
│    → Fetches: CoinGecko (price) + Kraken (klines)           │
│    → Detects events → Generates PDF                         │
│    → Sends email with PDF via Mailgun API                   │
│    → Logs saved as workflow artifacts (30 days)             │
│    → VM shuts down                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    OPTION B: Railway                         │
│           (Always-on — run on demand anytime)                │
│                                                              │
│  Railway cron job (or manual trigger via dashboard)         │
│    → Persistent Python service                              │
│    → Same engine.py logic                                   │
│    → $5/month Hobby plan                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Option A: GitHub Actions (Recommended)

### Why GitHub Actions?
- ✅ FREE — well within the 2,000 min/month free tier (each run = ~30 sec)
- ✅ No server to manage
- ✅ Already have the repo
- ✅ Logs visible in GitHub UI (Actions tab)
- ✅ Manual trigger via "Run workflow" button
- ✅ Reliable — GitHub's infrastructure, 99.9% uptime

### Setup Steps

**Step 1 — Add Mailgun API Key as GitHub Secret**
1. Go to: github.com/claytoncamera/loopholemaxing → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `MAILGUN_API_KEY`
4. Value: your Mailgun private API key (from mailgun.com → API Keys)
5. Click "Add secret"

**Step 2 — (Optional) Set repository variables**
In the same Settings → Secrets → Actions → Variables tab:
- `MAILGUN_DOMAIN` = `loopholemaxing.com`
- `ALERT_EMAIL_TO` = `clayton.camera@icloud.com`
- `ALERT_EMAIL_FROM` = `alerts@loopholemaxing.com`
- `MOVE_THRESHOLD_PCT` = `3.0` (alert trigger threshold %)

These are pre-set to sensible defaults in the workflow file.

**Step 3 — That's it**
The workflow is already in the repo at `.github/workflows/btc-brain-daily.yml`.
It runs automatically at 6:00 AM EDT every day.

**Step 4 — Manual trigger**
GitHub → Actions tab → "BTC Brain Daily Intelligence" → "Run workflow"
Check "Force send alert" to test email delivery.

**View logs:**
GitHub → Actions tab → click any run → click "Run BTC Brain Engine" step.
Full stdout logs are visible. PDF is saved as a workflow artifact.

---

## Option B: Railway

**Step 1 — Create new project**
- Go to railway.app (you already have an account from OrbitRoute)
- New Project → Deploy from GitHub repo → claytoncamera/loopholemaxing
- Root directory: `btc-brain-engine`

**Step 2 — Set environment variables**
In Railway dashboard → Variables:
```
MAILGUN_API_KEY    = (your key)
MAILGUN_DOMAIN     = loopholemaxing.com
ALERT_EMAIL_TO     = clayton.camera@icloud.com
ALERT_EMAIL_FROM   = alerts@loopholemaxing.com
ALWAYS_SEND        = false
```

**Step 3 — Add cron trigger**
Railway → Settings → Cron Schedule → `0 10 * * *` (6 AM EDT)

---

## Getting Your Mailgun API Key

1. Log into mailgun.com (you have an account — it's configured for loopholemaxing.com)
2. Top right menu → API Keys
3. Copy the "Private API key" (starts with `key-`)
4. Paste it as the GitHub Secret in Step 1 above

---

## What the Engine Does

| Step | Action |
|------|--------|
| 1 | Fetches BTC price/volume from CoinGecko (with 3 retries, exponential backoff) |
| 2 | Fetches 1h OHLCV from Kraken (Kraken fallback → CoinGecko chart) |
| 3 | Detects: 3%+ moves, key level breaks, sustained 7h trend |
| 4 | Generates PDF alert (light theme, print-ready) |
| 5 | Sends email via Mailgun API with PDF attached |
| 6 | Saves JSONL run history for tracking |
| 7 | Uploads logs as GitHub artifact |

Quiet day = runs and exits silently. No email. No cost.

---

## Run Locally (Test)

```bash
cd btc-brain-engine
pip install -r requirements.txt

# Test run (no email)
python engine.py

# Test with forced alert
ALWAYS_SEND=true python engine.py

# Test with email
MAILGUN_API_KEY=key-xxxx ALWAYS_SEND=true python engine.py
```
