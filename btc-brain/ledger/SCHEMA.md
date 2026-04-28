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
| `price_source`       | string  | yes      | e.g. `binance:BTCUSDT:1h`. |

## Identity & joining

`forecast_id` is the join key. A forecast is "open" until exactly one
resolution event with status `resolved` or `voided` exists for it. A second
resolution for the same `forecast_id` is a bug and the validator rejects it.
