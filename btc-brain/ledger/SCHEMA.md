# Forecast Ledger Schema (v1)

Two append-only JSONL streams.

## `forecasts.jsonl` — one line per issued forecast

| Field                  | Type    | Required | Description |
|------------------------|---------|----------|-------------|
| `forecast_id`          | string  | yes      | UUIDv4. Primary key. Never reused. |
| `issued_at`            | string  | yes      | ISO-8601 UTC, e.g. `2026-04-27T13:00:00Z`. |
| `asset`                | string  | yes      | `BTCUSD` for now. |
| `horizon`              | string  | yes      | One of `1h`, `4h`, `12h`, `24h`, `1d`, `7d`, `30d`. |
| `target_time`          | string  | yes      | ISO-8601 UTC. Exact resolution moment. |
| `target_rule`          | string  | yes      | How outcome is decided. Enum: `close_above_entry`, `close_below_entry`, `close_above_level:<price>`, `close_below_level:<price>`. |
| `direction`            | string  | yes      | `up` or `down`. Direction the forecast is betting on. |
| `probability`          | number  | yes      | Probability assigned to `direction`, in (0, 1). |
| `entry_price`          | number  | yes      | BTC close at issue time (USD). |
| `model_version`        | string  | yes      | Semver-ish. e.g. `v0.1.0-baseline`. |
| `signal_version`       | string  | yes      | Version of the upstream signal pack. |
| `regime_at_issue`      | string  | yes      | One of `bull`, `bear`, `chop`, `unknown`. |
| `feature_snapshot_uri` | string  | yes      | Path/URL to the frozen feature vector at issue. |
| `source_snapshot_uri`  | string  | yes      | Path/URL to the frozen raw source data. |
| `confidence_reason`    | string  | yes      | Short human-readable rationale. |
| `invalidation`         | string  | yes      | Condition that voids the forecast (e.g. `BTC > 130000 before target`). |
| `created_by`           | string  | yes      | Agent / human ID that wrote the row. |
| `status`               | string  | yes      | `open` at issue. Becomes `resolved`, `voided`, or `superseded` only via a *new* event in `resolutions.jsonl`. The original row is never edited. |

The original row never carries any of the resolution fields. They live only
in `resolutions.jsonl`.

## `resolutions.jsonl` — one line per resolution

| Field                | Type    | Required | Description |
|----------------------|---------|----------|-------------|
| `forecast_id`        | string  | yes      | FK to a row in `forecasts.jsonl`. |
| `resolved_at`        | string  | yes      | ISO-8601 UTC when this resolution was written. |
| `actual_close`       | number  | yes      | Close price used to resolve. |
| `actual_return`      | number  | yes      | `(actual_close - entry_price) / entry_price`. |
| `direction_correct`  | boolean | yes      | True if realized direction matches forecasted `direction`. |
| `brier_component`    | number  | yes      | `(probability - outcome)^2` where `outcome ∈ {0,1}`. |
| `logloss_component`  | number  | yes      | `-[outcome*log(p) + (1-outcome)*log(1-p)]` (clipped p to [1e-6, 1-1e-6]). |
| `status`             | string  | yes      | `resolved` or `voided` (invalidation triggered before target). |
| `resolver_version`   | string  | yes      | Version of `resolve.py` that wrote this row. |
| `candle_open_time`   | string  | yes      | ISO-8601 UTC of the close candle's open. |
| `candle_close_time`  | string  | yes      | ISO-8601 UTC of the close candle's close. |
| `price_source`       | string  | yes      | Provenance of the resolving close. Either the legacy version tag `binance:BTCUSDT:1h`, or one of the short provider tags `binance` / `coingecko` / `kraken` written by the fallback-aware resolver. |

### `price_source` provenance

The resolver tries keyless public sources in order **Binance → CoinGecko →
Kraken** and records which one supplied the close. All three return the *same*
quantity — the close of the 1h candle that ends at `target_time` — so accuracy
math is source-independent. Readers must treat `price_source` as a free-form
string and tolerate both the old version-tag form (`binance:BTCUSDT:1h`, on
rows written before the fallback change) and the short provider tags. Old rows
without any newer value are unaffected; the field has always been present.

Alignment per source (all resolve the hour-boundary close at `target_time`):

- **binance**: 1h klines; the bar whose `closeTime` ≈ `target` (…:59.999).
- **coingecko**: `/coins/bitcoin/ohlc?days=1` 30-min bars (timestamp = open);
  the bar opening at `target − 30m` closes at `target`. Only covers ~last 24h.
- **kraken**: `/0/public/OHLC?interval=60` 1h bars (`time` = open, seconds);
  the bar with `time == target − 3600` closes at `target`. Covers deep history.

## Identity & joining

`forecast_id` is the join key. A forecast is "open" until exactly one
resolution event with status `resolved` or `voided` exists for it. A second
resolution for the same `forecast_id` is a bug and the validator rejects it.

---

# Public artifacts (`ledger/public/`)

All generated by `scripts/metrics.py` and `scripts/emit_signal.py`; never
hand-edited. Regenerating is always safe — they are pure functions of the two
JSONL streams.

## `accuracy.json` — `metrics-v0.3.1`

Every v0.2.0 field is preserved; v0.3.0 is purely additive. v0.3.1
(2026-09-01) changes no field names but fixes two lying values:

- **`vs_majority_pp` is now real percentage points** (`(hit_rate −
  max(always_up_rate, always_down_rate)) × 100`). Before v0.3.1 it held a
  raw fraction despite the `_pp` suffix (−0.0681 meant −6.81pp), so a
  renderer trusting the name understated the gap ~100×. The same fix
  applies to `edge_report.json` (edge-hunter-v0.1.1).
- **`baseline_hit_rate` is now the majority-direction baseline**
  `max(always_up_rate, always_down_rate)` — what "always call the majority
  realized direction" would score. Before v0.3.1 it was `max(base_rate,
  1 − base_rate)` over the model's own hit/miss outcomes, which equals
  `hit_rate` whenever `hit_rate >= 0.5` — an unbeatable "baseline" implying
  a permanent 0.00pp gap. `base_rate` / `baseline_brier` keep their
  outcome-sequence (Brier-skill) semantics.

Per-bucket fields (all bucket maps): the v0.2.0 set (`n`, `hit_rate`,
`brier`, `logloss`, `ece`, baseline fields, `vs_majority_pp`,
`expectancy_bps`, `expectancy_maker_2bps`, `expectancy_taker_10bps`,
`n_up`/`n_down`/`hit_up`/`hit_down`, `always_up_rate`/`always_down_rate`,
`display_ready`) plus:

| Field | Meaning |
|---|---|
| `wilson_lb_95` | 95% Wilson score lower bound on `hit_rate` at that bucket's `n`. The gate-grade "how bad could the true rate plausibly be" number. |

New top-level blocks:

| Block | Meaning |
|---|---|
| `by_model_horizon` | All-time buckets keyed `"model_version\|horizon"` (e.g. `"v0.2.0-shadow-policy24\|24h"`). **This is the bucket the signal gate evaluates** — never a pooled one. |
| `rolling.by_horizon` | `{horizon: {"7d"/"30d"/"90d": compact}}` — windows keyed on **`issued_at`** (resolved rows only). |
| `rolling.by_model_horizon` | Same, keyed `"model\|horizon"`. |
| `rolling.window_basis` | Documents the keying: legacy `rolling.7d/30d/90d` stay **`resolved_at`**-keyed (unchanged since v0.2.0); the new sub-blocks are `issued_at`-keyed. |

Compact rolling buckets carry exactly: `n`, `hit_rate`, `brier`,
`expectancy_bps`, `expectancy_maker_2bps`, `wilson_lb_95`.

**ECE semantics change (fix):** `ece` is now computed over **5 quantile bins**
of predicted probability when a bucket has `n >= 50`, else `null`. Tied
probabilities are never split across bins (so ECE is order-independent). The
old fixed-decile binning was structurally always `null` on our narrow
~[0.50, 0.55] probability range.

## `recent.json` — `recent-v0.1.0`

Small joined tape so the site never downloads the raw multi-MB JSONL to show
a table.

```
{
  "schema_version": "recent-v0.1.0",
  "generated_at": ISO-8601,
  "total_issued": int,          // all forecasts ever
  "total_resolved": int,        // resolutions with status "resolved"
  "rows": [ ... last 50 forecasts, newest issued_at first ... ]
}
```

Each row: `forecast_id`, `issued_at`, `model_version`, `horizon`,
`direction`, `probability`, `entry_price`, `target_time`, `resolved` (bool),
`actual_close`, `actual_return_bps` (raw market return × 10⁴, NOT
direction-signed), `direction_correct`, `resolved_at`. The last four are
`null` while `resolved` is false.

## `trades.json` — `trades-v0.1.0`

The paper trade tape: every resolved forecast is one 1-unit paper trade taken
in the forecasted direction.

- `ret_bps_gross` = signed return in the forecasted direction, in bps
  (`+actual_return×10⁴` for `up`, `−actual_return×10⁴` for `down`).
- `ret_bps_maker` = `ret_bps_gross − 2` (maker round-trip).

```
{
  "schema_version": "trades-v0.1.0",
  "generated_at": ISO-8601,
  "fee_bps": {"maker_rt": 2, "taker_rt": 10},
  "groups": [            // one per model_version × horizon with n >= 5
    {
      "model_version": str, "horizon": str,
      "n": int, "wins": int, "hit_rate": float,
      "sum_bps_maker": float, "avg_bps_maker": float,
      "max_drawdown_bps_maker": float,   // peak-to-trough of the cum curve, ≥ 0
      "curve": [[epoch_seconds_of_issued_at, cum_bps_maker], ...],  // one per trade, issued_at order
      "last_trades": [ ... last 30 trades ... ]
    }
  ]
}
```

Each trade in `last_trades`: `issued_at`, `direction`, `probability`,
`entry_price`, `exit_price` (= `actual_close`), `ret_bps_gross`,
`ret_bps_maker`, `win` (= `direction_correct`).

## `signal.json` — `signal-v0.2.0`

All v0.1.0 fields are kept (`status`, `gates.ok/n/hit_rate/
expectancy_maker_2bps/vs_majority_pp/rolling_30d_hit/reason`, `economics`,
`signal`, disclaimers), so a v0.1.0 reader still parses it. What changed:

- **Gates now evaluate the EMITTING model's own `by_model_horizon` bucket**,
  never the pooled `by_horizon` one (the v0.1.0 bug let a failing model ride
  a strong pooled bucket to `actionable_paper`).
- `status: "actionable_paper"` requires ALL of: all-time `n >= 40`; all-time
  `wilson_lb_95 > 0.50`; rolling-30d (`issued_at`-keyed) `n >= 20` AND
  `hit_rate >= 0.52` AND `expectancy_maker_2bps > 0`; forecast not past
  `expires_at`. Anything else → `"shadow"` (the forecast is still emitted —
  honest state).

New `gates` fields:

| Field | Meaning |
|---|---|
| `model_version`, `horizon`, `bucket` | Which `by_model_horizon` bucket was judged (bucket = `"model\|horizon"`). |
| `wilson_lb_95` | All-time Wilson lower bound for that bucket. |
| `rolling_30d` | `{window_keyed_on: "issued_at", n, hit_rate, expectancy_maker_2bps, wilson_lb_95}` for that bucket. |
| `thresholds` | The exact gate constants used. |
| `reasons` | `[]` when ok; else one human-readable string per failing condition. |

Legacy `gates.n` / `hit_rate` / `expectancy_maker_2bps` / `vs_majority_pp`
now describe the model's own bucket (previously the pooled horizon bucket);
`rolling_30d_hit` remains the global resolved_at-keyed 30d hit rate.
