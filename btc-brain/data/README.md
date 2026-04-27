# BTC Brain — Phase 2: Data Foundation

This directory implements the **data layer** behind the public BTC
Intelligence Brain. Phase 2 adds:

1. A robust feed abstraction with fallback across multiple public,
   no-secret providers.
2. Candle, derivatives, and sentiment snapshot writers.
3. A dynamic key-level computer that runs only on real, *closed*
   candles.
4. A source-health / freshness emitter the frontend reads.
5. Tests that prove **no synthetic OHLC**, **no incomplete-candle
   indicators**, and that fallback / degradation states are honoured.

## Directory layout

```
btc-brain/data/
├── feeds/                  # provider abstraction
│   ├── base.py             # FeedResult, run_with_fallback, http helper
│   ├── candles.py          # Binance → Coinbase → Kraken → CoinGecko
│   ├── derivatives.py      # Binance → OKX
│   └── sentiment.py        # alternative.me → CoinGecko
├── scripts/
│   ├── snapshot.py         # writes the public artifacts
│   └── key_levels.py       # dynamic level computation
├── public/                 # generated, served by Pages — never edit by hand
│   ├── candles_1h.json
│   ├── candles_4h.json
│   ├── candles_1d.json
│   ├── derivatives.json
│   ├── sentiment.json
│   ├── key_levels.json
│   └── source_health.json
└── tests/
    └── test_phase2.py      # offline tests (no real HTTP)
```

## Provider priority

| Kind          | Order                                                                |
|---------------|----------------------------------------------------------------------|
| Candles 1m/5m/15m/1h | **Binance** → Coinbase → Kraken                              |
| Candles 4h    | **Binance** → Kraken → CoinGecko (CoinGecko OHLC; no Coinbase 4h)    |
| Candles 1d    | **Binance** → Coinbase → Kraken → CoinGecko                          |
| Derivatives   | **Binance USDT-M futures** → OKX (BTC-USDT-SWAP)                      |
| Sentiment     | **alternative.me Fear & Greed** → CoinGecko sentiment proxy           |

If every provider in a chain fails, the artifact is written with
`status: "failed"` and `data: null`. The frontend renders an
"unavailable" state — it never shows fabricated OHLC.

## Snapshot schema

Every `data/public/*.json` artifact carries:

| Field            | Type        | Notes |
|------------------|-------------|-------|
| `schema_version` | string      | `phase2-data-v1` |
| `kind`           | string      | `candles_1h`, `derivatives`, etc. |
| `source`         | string      | provider that supplied the chosen result |
| `status`         | enum        | `ok` / `degraded` / `stale` / `failed` |
| `fetched_at`     | ISO-8601 UTC | when the data was retrieved |
| `data`           | object/null | provider-specific (see below); `null` on failure |
| `attempts`       | array       | one entry per provider tried (for transparency) |
| `notes`          | array       | free-form provenance / degradation notes |

### `candles_<interval>.json`

`data` is:

```jsonc
{
  "interval": "1h",
  "candles": [
    {
      "open_time_ms": 1745740800000,
      "close_time_ms": 1745744400000,   // exclusive end
      "open": 65010.0, "high": 65250.5,
      "low":  64880.0, "close": 65120.7,
      "volume": 12.34
    }
  ]
}
```

The trailing in-progress candle, if returned by Binance, is **not** dropped
in the artifact (we keep the raw history) but every consumer in this repo
(`closed_candles()`, `key_levels.compute_key_levels()`, the JS
`closedCandlesOnly` helper) drops it before computing indicators or
levels. This is the Phase 0 "no incomplete-candle indicators" invariant.

### `derivatives.json`

```jsonc
{
  "funding_rate": 0.00012,
  "next_funding_time_ms": 1745740800000,
  "mark_price": 65250.5,
  "open_interest_btc": 73250.0,
  "long_short_ratio": 1.42,
  "long_account_pct": 0.59,
  "short_account_pct": 0.41
}
```

Sub-fields may be `null`. When at least one is missing, `status` is
`degraded` (still useful) rather than `ok`.

### `sentiment.json`

```jsonc
{
  "fear_greed_value": 63,
  "fear_greed_label": "Greed",
  "sample_timestamp": "1745740800",
  "indicator": "fear_greed_btc_crypto"
}
```

When the CoinGecko fallback is used, `indicator` becomes
`coingecko_sentiment_up_pct` and `fear_greed_value` is the up-vote
percentage rounded to int (different scale, same field name kept for
schema stability).

### `key_levels.json`

```jsonc
{
  "version": "key-levels-v0.1.0",
  "computed_at": "...",
  "inputs": { "closed_1h_count": 24, "closed_1d_count": 30 },
  "recent_high": 70025.0,
  "recent_low":  64900.0,
  "pivot_classic": 67100.5,
  "r1": 67800.0, "r2": 68900.0,
  "s1": 66300.0, "s2": 65100.0,
  "sma_20": null, "sma_50": null, "sma_200": null,
  "vwap_session": 65420.7,
  "degraded": false,
  "notes": []
}
```

Every numeric field is computed **only** from the closed candles fed in.
If there are no candles, every field is `null` and `degraded: true`.

### `source_health.json`

```jsonc
{
  "schema_version": "phase2-data-v1",
  "kind": "source_health",
  "generated_at": "...",
  "overall": "ok | degraded | failed",
  "sources": {
    "candles_1h":   { "source": "binance",    "status": "ok",       "fetched_at": "...", "latency_ms": 412 },
    "candles_4h":   { ... },
    "candles_1d":   { ... },
    "derivatives":  { "source": "binance",    "status": "degraded", "error": null },
    "sentiment":    { "source": "alternative.me", "status": "ok" },
    "key_levels":   { "source": "computed",   "status": "ok" }
  },
  "freshness_budget_seconds": {
    "candles_1h": 5400,
    "candles_4h": 18000,
    "candles_1d": 93600,
    "derivatives": 1800,
    "sentiment":  86400
  }
}
```

The frontend reads this file and renders a small banner near the top of
the page. If it's missing or `failed`, the banner stays hidden — the
existing P0 "stale / OHLC unavailable" copy in the live-market tab is
the canonical fallback.

## Running locally

```bash
# Offline tests (no network).
cd btc-brain/data && python tests/test_phase2.py

# Refresh public artifacts (hits public APIs).
python btc-brain/data/scripts/snapshot.py --out btc-brain/data/public
```

## CI

`.github/workflows/btc-data-snapshot.yml` runs the unit tests, refreshes
the artifacts, and commits. It uses no secrets.
