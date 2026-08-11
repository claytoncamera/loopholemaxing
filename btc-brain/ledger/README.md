# BTC Forecast Ledger

Append-only ledger of BTC forecasts, exact-horizon resolver, and public
accuracy metrics generator. This is the measurement substrate for the BTC
Intelligence Brain — every probabilistic forecast must land here before any
public accuracy claim is allowed.

## Layout

```
btc-brain/ledger/
├── data/
│   ├── forecasts.jsonl        # append-only forecast events
│   ├── resolutions.jsonl      # append-only resolution events (no edits to forecasts)
│   └── prices_cache.jsonl     # cache of fetched closing candles (optional)
├── public/
│   ├── accuracy.json          # generated metrics consumed by the public Brain
│   └── ledger_public.json     # generated, redacted ledger snapshot for the UI
├── scripts/
│   ├── ledger.py              # append/load/validate primitives
│   ├── issue_forecast.py      # CLI to append a new forecast
│   ├── resolve.py             # exact-horizon resolver
│   ├── metrics.py             # accuracy.json generator
│   └── price_source.py        # price/candle fetcher (Binance hourly close)
├── tests/
│   └── test_ledger.py         # runnable pytest/unittest suite
├── snapshots/                 # feature_snapshot_uri / source_snapshot_uri targets
└── README.md
```

## Append-only invariants

1. `forecasts.jsonl` is opened with `O_APPEND` only. Existing lines are never
   rewritten.
2. Resolutions live in a **separate** file (`resolutions.jsonl`). Joining a
   forecast and its resolution is done at read time on `forecast_id`.
3. `metrics.py` is pure: it reads both files and writes `public/accuracy.json`.
   Re-running it on the same inputs is deterministic.

## Hard rules (do not violate)

- Do not display global accuracy unless `public/accuracy.json` exists AND
  per-bucket sample size meets the minimum threshold (default n>=20).
- Do not resolve a forecast before its `target_time` is in the past.
- Do not resolve using the live ticker — only the closing candle whose
  `closeTime > target_time` and `openTime <= target_time` (no incomplete
  candles).
- Do not overwrite an existing forecast event. Corrections are new events
  with `status="superseded"` referencing the old `forecast_id`.

## MVP → production migration

JSONL today, Postgres later. Schema is identical: every JSONL field maps to a
column. Migration is `COPY forecasts.jsonl INTO forecasts` table after `\copy`
of the resolutions table — no transformation required.

## Upgrade 2026-07-21 — dual issuer + continuous edge hunt

- **metrics-v0.2.0**: expectancy (raw/maker/taker), vs_majority_pp, by_direction, by_regime, edge_scoreboard
- **Dual issuer** (`schedule_forecasts.py --mode dual`):
  - `v0.1.0-baseline-shadow` — control (1h/4h/12h/24h)
  - `v0.2.0-shadow-policy24` — 12h+24h only, inverted conf, skip hour 20 UTC, live regime labels
- **edge_hunter.py** → `public/edge_report.json` every resolve/issue cycle (ranked slices + next experiments)
- **emit_signal.py** → `public/signal.json` paper contract (24h only; never 1h actionable)
- Research freeze: `btc-brain/research/edge_autopsy_2026-07-21.md`

Continuous improvement target: raise **24h hit_rate** toward 0.65–0.70 with n≥100 and positive maker expectancy — never by promoting 1h noise.

## Upgrade 2026-08-10 — v0.3 honest issuance + guard24 (scheduler-v0.3.0 / resolver-v0.2.0)

Audit findings this fixes: backdated `issued_at` after missed crons (64/128
24h and 112/253 12h rows were stamped ≥1h before their real run time),
cross-venue entry/resolution basis (Coinbase entry vs Binance resolution
decided ~90 near-tie resolutions), anti-predictive unguarded down calls,
1/day 24h accrual, and GHA cron throttling (1h spacing achieved only ~21%
of runs).

### Issuer (`schedule_forecasts.py --mode dual`)

- **No backdating.** The CLI skips any bucket whose start is more than
  `--max-backdate-minutes` (default **15**) before now. A missing bucket is
  honest — never backfill. `<=0` disables the guard (replay only). The
  library functions (`run`/`run_all`) default to no guard for API/test
  compatibility; the CLI always applies it.
- **Additive row fields** (metrics keeps parsing; schema unchanged for
  required keys): `issued_at_actual` (real wall-clock; `issued_at` stays the
  bucket floor), `entry_source` (winning provider from the snapshot's
  top-level `source` key, e.g. `coinbase` when Binance 451s from CI), and
  `entry_symbol` when derivable (binance→BTCUSDT, coinbase→BTC-USD,
  kraken→XBTUSD).
- **Overlapping accrual.** 12h and 24h issue **every hour**
  (`bucket_hours=1`) for both active models; 1h/4h grids unchanged. The
  00 UTC subseries remains the clean non-overlapping control — filter
  `issued_at` hour == 0 for it. Dedupe key is still
  `(model_version, horizon, bucket)`; re-runs add zero rows.
- **`v0.2.0-shadow-policy24` KILLED** (its own 24h record: n=62, hit 43.5%,
  maker −21.8bps — met the master-plan kill criteria). No CLI switch
  re-enables it; code stays importable for replay + frozen tests.
- **`v0.3.0-shadow-guard24`** (12h/24h): `rel = (last − sma24)/sma24`.
  Abstain when `|rel| > 1%`. Up if `last >= sma24`; down requires
  `last < sma24` **and** `last < sma72` (else abstain). Abstain on down
  calls issued Saturday/Sunday UTC. Probability **0.55** when
  `|rel| < 0.5%`, else **0.52**. Abstains appear in the run summary/stderr
  (`skipped_filter`, `guard24:abstain=...`) and write no ledger row.

### Resolver (`resolve.py` / `price_source.py`)

- **Venue unification.** A forecast carrying `entry_source` in
  {binance, coinbase, kraken} resolves against that venue FIRST (Coinbase
  spot via `api.exchange.coinbase.com` 1h candles), falling back to the
  existing Binance→CoinGecko→Kraken chain when the venue can't answer.
  Rows without `entry_source` (all pre-v0.3 rows) resolve exactly as
  before. The comparison rule (close vs `entry_price`) is unchanged.
- Resolutions keep `price_source` and gain additive `resolution_source`
  (plain venue tag) so entry/resolution venue matching is auditable.

### Workflows

- `btc-ledger-issue.yml` cron is now `7,27,47 * * * *` — three fires fight
  GHA throttling; dedupe + the backdate guard make extra fires no-ops.
- Both ledger workflows share `concurrency: group: btc-ledger`
  (`cancel-in-progress: false`) so the two writers serialize instead of
  racing through safe_push rebases.

### Runbook

```
# tests (all suites)
cd btc-brain/ledger
python tests/test_ledger.py && python tests/test_schedule_forecasts.py \
  && python tests/test_edge_upgrade.py && python tests/test_issuer_v03.py

# dry-run the dual issuer against the live snapshot
python scripts/schedule_forecasts.py --root data \
  --candles ../data/public/candles_1h.json --dry-run

# expected honesty behaviors in the dry-run output:
#  - "backfill-guard: ... skipping — a missing bucket is honest" when >15m
#    past the hour (run again inside :00–:15 to see issuance)
#  - "guard24:abstain=..." with rule values whenever guard24 stands aside
```
