# BTC Brain — Phase 4: Regime + Drift (SHADOW MODE ONLY)

**Status:** SHADOW. No model is auto-promoted by Phase 4. No live UI claim
is added. All artifacts in `btc-brain/models/public/phase4/` are example
output from the synthetic fixture and are tagged `fixture_only=true`.

Phase 4 adds three observability and governance primitives on top of the
Phase 3 model framework:

1. A **lightweight regime detector** that labels every closed candle with
   a coarse (`bull`/`bear`/`chop`/`unknown`) and a fine
   (`trend_*_(high|low)_vol`) regime. Strictly causal — `bar t`'s label
   depends only on `closes[0..t]`. No future-smoothing.
2. **Drift detectors** for the live error / feature streams:
   Page-Hinkley, EWMA-on-error, and a two-window KS-style distribution
   detector. They emit alerts only — they never promote.
3. **Promotion gates** with explicit, auditable thresholds. A model can
   leave shadow only when *every* gate passes, including manual approval.
4. A **retrain-candidate pipeline** that runs the drift detectors against
   recent error/feature streams and emits a JSON candidate report. Live
   models, registry entries, and the Phase 1 ledger are never modified.

## Why a lightweight detector instead of a full HMM

The Phase 4 mission allows "HMM/regime detector or equivalent lightweight
regime detector". A full HMM (Baum-Welch / Viterbi) needs `numpy` and an
EM loop, neither of which is currently in the BTC Brain runtime. We
chose a deterministic, pure-stdlib path so:

* the implementation is auditable line-by-line (no opaque library state),
* it cannot accidentally future-smooth — Viterbi can; this cannot,
* it imports the same regime vocabulary the rest of the pipeline (Phase
  1 ledger schema, Phase 3 features, Phase 0 truth labels) already uses.

If we later adopt `numpy` and want a true HMM, this module is a drop-in
target — only `regime.py` would change, and the test suite locks the
causality / closed-candle invariants the replacement must preserve.

## Layout

```
btc-brain/models/phase4/
  regime.py             lightweight causal regime detector
  drift.py              Page-Hinkley, EWMA, KS-window drift detectors
  promotion_gates.py    auditable promotion gate evaluator
  retrain.py            retrain candidate report builder
  report.py             Phase 3 → Phase 4 report enrichment
  run_phase4.py         CLI runner: produces example artifacts
  tests/test_phase4.py  causality, drift, gates, report tests
```

Public artifacts live in `btc-brain/models/public/phase4/`. Every file
written there is `fixture_only=true` while we don't have ledger-backed
sample.

## Running

```
# Produce example artifacts (regime distribution, phase4 report,
# retrain candidate). All are fixture_only=true.
python btc-brain/models/phase4/run_phase4.py

# Run the Phase 4 tests:
cd btc-brain/models && python phase4/tests/test_phase4.py
```

`run_phase4.py` only writes inside `btc-brain/models/public/phase4/`. It
never touches the live ledger, the Phase 3 validation report, or any
non-shadow artifact.

## Hard invariants (do not regress)

* **No future regime smoothing.** Truncating the close series MUST leave
  the prefix of regime labels unchanged. Locked by
  `TestRegimeCausal.test_no_future_smoothing`.
* **Closed candles only.** The detector reads close prices already
  filtered through the Phase 0/2 closed-candle helper. Appending an
  in-progress candle MUST NOT change earlier labels. Locked by
  `TestRegimeClosedCandleOnly`.
* **Drift detectors emit alerts only.** They never write to the registry,
  never modify model state, never touch the ledger.
* **Promotion gates are advisory in code; required in process.** No
  function in this directory mutates `promoted_at`. The gate evaluator
  returns a `PromotionDecision` whose `ready_for_promotion` is consumed
  by humans.
* **Phase 1 ledger immutability** is preserved — Phase 4 reads the ledger
  if present but never edits it.
* **Phase 0 truth labels** are unchanged. Regime labels are *features*
  for the model layer, not "truth" claims.
* **No global accuracy claim is rendered** by Phase 4. The public UI
  remains unchanged. Until ledger-backed metrics exist, Phase 4 reports
  decline to emit a live-accuracy figure.
* **No same-bar lookahead.** Targets/forecasts are never computed from
  the same-bar regime label paired with a same-bar outcome. Regime is a
  feature at bar `t`; outcomes come from later bars.

## Promotion gates

Defined in `promotion_gates.py`. Defaults (auditable, see `DEFAULT_GATES`):

| Gate                       | Default              | Reason                                        |
| -------------------------- | -------------------- | --------------------------------------------- |
| `min_resolved_total`       | 30                   | Need a real out-of-sample sample.             |
| `min_resolved_per_horizon` | 30                   | Each horizon must clear sample on its own.    |
| `min_shadow_days`          | 14                   | ≥ 2 weeks of live shadow outcomes.            |
| `max_brier`                | 0.245                | Beat unbiased coin (0.25) with margin.        |
| `max_log_loss`             | 0.68                 | Strict but achievable for calibrated models.  |
| `max_ece`                  | 0.08                 | Calibration must be honest.                   |
| `must_beat_baseline_brier` | True                 | Must beat ALL baselines on Brier.             |
| `min_baseline_brier_margin`| 0.005                | Margin to avoid noise-driven flips.           |
| `no_severe_drift`          | True                 | Zero drift alarms in lookback window.         |
| `no_drift_lookback`        | 100                  | Recent observations checked.                  |
| `must_have_out_of_sample`  | True                 | Walk-forward fold count > 0.                  |
| `min_oof_folds`            | 3                    | Multi-fold OOS evidence.                      |
| `regime_coverage_min`      | 2                    | Metrics in ≥2 coarse regimes.                 |
| `require_manual_approval`  | True                 | Two-keys: model-author + reviewer.            |

A loosening of any threshold is a documented, reviewed change.

## Retrain candidate workflow (manual)

1. Observe an alarm in the live shadow forecast resolution loop (Phase 1
   ledger metrics + Phase 4 drift detectors over the recent error stream).
2. Run `python btc-brain/models/phase4/run_phase4.py` (or call
   `build_retrain_candidate(...)` from a notebook) to emit a candidate
   report into `btc-brain/models/public/phase4/retrain_candidate.json`.
3. Review the triggers and the regime-sliced metrics. If they look like a
   real regime shift (not a feed glitch), schedule a Phase 3 walk-forward
   retrain run on a refreshed window.
4. Once the candidate has accumulated ≥ 2 weeks of resolved shadow
   forecasts, evaluate `evaluate_promotion(...)`.
5. Promotion remains a manual two-keys step. No code in this directory
   sets `promoted_at`.

## Phase 4 promotion recommendation

**NOT READY.** Phase 4 ships the framework only. There is no
ledger-backed sample and no shadow-resolution history yet. Every
`PromotionDecision` produced by the fixture runner reports
`ready_for_promotion=false` and lists the failing gates.
