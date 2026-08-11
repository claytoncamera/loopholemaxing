# BTC Brain — data/history (append-only retention)

The snapshot workflow overwrites `../public/*.json` in place every 30
minutes, so on its own the repo retains ~200 candle bars and no
derivatives/sentiment history at all. This directory is the append-only
archive that fixes that — it is the training corpus for Phase 3 ML.

All files are JSONL (one JSON object per line), **sorted, deduped, and
idempotent to rebuild**. They are written by
`../scripts/archive.py`, which runs as a step in
`.github/workflows/btc-data-snapshot.yml` right after each snapshot.
Never edit these files by hand.

## Files

### `candles_1h.jsonl`

One row per **closed** hourly BTC-USD candle, deduped by `open_time_ms`,
sorted ascending. The in-progress bar of a snapshot is never archived
(closed = `close_time_ms <= fetched_at` of the snapshot that carried it).

```json
{"open_time_ms": 1722470400000, "open": 64628.01, "high": 64640.0,
 "low": 64363.39, "close": 64426.34, "volume": 214.44, "source": "coinbase-backfill"}
```

`source` records provenance:

| source              | meaning                                                             |
|---------------------|---------------------------------------------------------------------|
| `coinbase` / `binance` / `kraken` / `coingecko` | archived live from a `public/candles_1h.json` snapshot (the snapshot's own source field) |
| `coinbase-backfill` | one-time deep backfill from Coinbase Exchange REST (`scripts/backfill_exchange.py`, run 2026-08-10) |
| `kraken-backfill`   | Kraken OHLC fallback rows from the same backfill (tail patching only) |

Snapshot-derived rows win over backfill rows on duplicate timestamps
(first writer wins, and bars never change once closed).

Provenance of the initial build (2026-08-10):

1. **Git-log reconstruction** (`scripts/backfill_git_history.py`): every
   historical version of `public/candles_1h.json` committed since
   2026-06-29 was extracted from git and merged → continuous coverage
   2026-06-21 → present.
2. **Deep backfill** (`scripts/backfill_exchange.py`): Coinbase Exchange
   `GET /products/BTC-USD/candles?granularity=3600` paged at 300
   bars/request from 2024-08-01 → continuous coverage from 2024-08-01.

Known gaps (missing at the exchange itself — Coinbase returns no bars
for these hours, i.e. no trades/downtime; re-queried 2026-08-10 to
confirm):

- 2025-10-25 17:00–20:00 UTC (4 bars)
- 2026-05-08 03:00–06:00 UTC (4 bars)

Everything else is continuous hourly coverage (99.94% of slots).

### `derivatives_history.jsonl`

One row per snapshot run, deduped by `snapshot_at` (the snapshot's
`fetched_at`), sorted. Key fields lifted from `public/derivatives.json`:

```json
{"snapshot_at": "2026-08-11T00:33:54Z", "source": "okx", "status": "partial_ok",
 "funding_rate": 9.78e-05, "open_interest_btc": 31892.2, "long_short_ratio": 1.19,
 "mark_price": 63972.3, "next_funding_time_ms": 1786464000000}
```

Fields that a degraded provider did not supply are `null` — `status`
tells you how much to trust the row. History starts 2026-08-10 (when
archiving began); there is no way to reconstruct earlier derivatives
snapshots.

### `sentiment_history.jsonl`

Same shape of contract, from `public/sentiment.json`:

```json
{"snapshot_at": "2026-08-11T00:33:55Z", "source": "alternative.me", "status": "ok",
 "fear_greed_value": 29, "fear_greed_label": "Fear",
 "indicator": "fear_greed_btc_crypto", "sample_timestamp": "1786406400"}
```

`sample_timestamp` is the *indicator's* own sample time (daily
resolution for Fear & Greed) — expect many snapshot rows per sample.
History starts 2026-08-10.

## Guarantees

- **Append-only:** rows are never mutated or removed by automation.
- **Deduped:** by `open_time_ms` (candles) / `snapshot_at` (the rest).
- **Sorted:** ascending by the dedupe key; rewritten atomically
  (tmp + rename) on every merge.
- **Never fails the workflow:** `archive.py` skips corrupt/missing
  snapshots with a warning and exits 0 (see `--strict` for local use).
