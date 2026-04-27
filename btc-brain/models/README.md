# BTC Brain — Phase 3: Model Baselines (SHADOW MODE ONLY)

**Status:** SHADOW. No model in this directory is promoted, no model output
is rendered into the public BTC Brain UI, and no model claims live accuracy.

This phase introduces the *framework* — features, baselines, walk-forward
validation, calibration, registry, and a shadow-mode forecast writer — so
that Phase 4 can flip the switch only after a model beats:

  1. its own baselines on out-of-sample walk-forward folds, and
  2. ≥ 2 weeks of live shadow-mode resolutions in the Phase 1 ledger.

## Layout

```
btc-brain/models/
  features/          feature builders over Phase 2 candle / derivatives /
                     sentiment artifacts (closed candles only)
  baselines/         random / last / momentum / mean-reversion / SIIE-lite
  validation/        chronological walk-forward + purging + embargo
  calibration/       Platt scaling + isotonic regression (OOF only)
  registry/          shadow registry JSON schema + loader/writer
  shadow/            shadow-mode forecast row emitter (uses ledger schema
                     but tags model_version with `shadow-`)
  scripts/           end-to-end CLI: build features, train, validate, write
                     registry + shadow forecasts + reports
  tests/             pure-stdlib tests covering invariants
  fixtures/          synthetic fixtures used by tests + CLI dry-run
  public/            *example* registry/validation/calibration artifacts
                     marked shadow_only = true
```

## Hard invariants (do not regress)

* No same-bar lookahead. A target for bar `t+H` is built from bar `t` features
  only; targets are computed from the close at `t+H`.
* Drop incomplete candles using the Phase 2 helper before any feature is built.
* Walk-forward only — never random K-fold. Purge ≥ horizon bars between train
  and test; add an embargo buffer.
* Scalers fit on training data only. Apply parameters to test fold without
  refitting.
* No public UI changes. The shadow registry is rendered nowhere on the site.
* Forecast ledger rows written by shadow models are still append-only and
  carry a `model_version` prefixed with `shadow-` so the public accuracy
  metrics filter can exclude them. Public claims are unchanged.
* Tree models (XGBoost / LightGBM) are *optional*. We attempt to import; on
  ImportError we record a `skipped: dependency_missing` registry entry and
  proceed. Logistic regression is mandatory and implemented in pure Python.
* Insufficient data → produce framework + tests + a synthetic fixture run,
  clearly marked `fixture_only: true`. Never claim an evaluation on absent data.

## Running

```
# Build everything from a synthetic fixture (no network):
python btc-brain/models/scripts/run_phase3.py \
    --fixture btc-brain/models/fixtures/synthetic_candles_1h.json \
    --out btc-brain/models/public

# Run unit tests:
cd btc-brain/models && python tests/test_phase3.py
```

`run_phase3.py` only writes inside `btc-brain/models/public/`. It never
touches `btc-brain/data/public/`, `btc-brain/ledger/public/`, or any
non-shadow artifact.

## Promotion gate (informational, not enforced by code yet)

A model can leave shadow only when *all* of the following hold:

1. ≥ 2 weeks of resolved shadow forecasts in the live ledger.
2. Beats every baseline on hit-rate AND brier on the rolling 30-day bucket.
3. ECE ≤ 0.08 on the rolling 30-day bucket.
4. Walk-forward validation report shows positive baseline-delta on the most
   recent 4 folds.
5. Manual sign-off recorded in the registry as `promoted_at`.

Phase 3 does not flip any of these gates automatically.
