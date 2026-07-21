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
