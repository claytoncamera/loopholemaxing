"""
Phase 3 — Model Baselines tests.

Run:
    cd btc-brain/models && python tests/test_phase3.py

Pure stdlib. No network. Verifies the Phase 3 invariants:

  * No same-bar lookahead in target construction (target uses close[t+H]
    only, never close[t]).
  * Walk-forward purging removes the trailing `purge_bars` of train.
  * Walk-forward embargo removes the leading `embargo_bars` of test.
  * No fold's train index is >= any test index.
  * Scaler params are fit on train only and applied without refit on test.
  * Baseline metrics return sensible numbers on a tiny hand-built sample.
  * ECE returns None below threshold and a value above.
  * Platt + isotonic improve / preserve calibration on a synthetic
    miscalibrated set.
  * Registry rejects entries without `shadow-` prefix and never accepts
    `promoted_at`.
  * Shadow forecast row matches the Phase 1 ledger schema exactly.
  * Closed-candle invariant: feature builder never reads incomplete
    candles (we synthesize a live candle and confirm the Phase 2 helper
    drops it before features are built).
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO_ROOT = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT / "btc-brain" / "data"))
sys.path.insert(0, str(REPO_ROOT / "btc-brain" / "ledger" / "scripts"))

from features.builder import build_features, FeatureFrame, FEATURES_VERSION
from features.targets import build_direction_target, HORIZON_BARS
from validation.walkforward import (
    walk_forward_splits,
    fit_scaler,
    apply_scaler,
    select,
)
from baselines.baselines import (
    RandomBaseline,
    MajorityBaseline,
    LastDirectionBaseline,
    MomentumBaseline,
    MeanReversionBaseline,
    SIIELiteBaseline,
)
from baselines.logistic import LogisticRegression, maybe_load_tree_model
from calibration.metrics import (
    brier,
    log_loss,
    hit_rate,
    expected_calibration_error,
    reliability_diagram,
    evaluate,
)
from calibration.calibrators import PlattScaler, IsotonicRegressor
from registry.registry import (
    REGISTRY_SCHEMA_VERSION,
    add_or_replace_model,
    empty_registry,
    write_registry,
    validate_model_entry,
)
from shadow.forecaster import build_shadow_forecast_row
from fixtures.synthetic import make_synthetic_candles, make_synthetic_aux_series

# Phase 2 helper — verify integration.
from feeds.base import drop_incomplete_candle  # noqa: E402

# Phase 1 ledger schema — verify our shadow rows are append-compatible.
from ledger import validate_forecast, FORECAST_FIELDS  # noqa: E402


# ── Targets / no-lookahead ────────────────────────────────────────────────
class TestTargets(unittest.TestCase):
    def test_no_same_bar_lookahead(self):
        closes = [100.0, 101.0, 102.0, 99.0, 105.0]
        t = build_direction_target(closes, "1h")
        # For h=1: valid_indices stop one before the last close.
        self.assertEqual(t.valid_indices, [0, 1, 2, 3])
        # Each label uses close[t+1] strictly, never close[t] itself.
        for i, idx in enumerate(t.valid_indices):
            future_idx = t.target_close_idx[i]
            self.assertEqual(future_idx, idx + 1)
            expected = 1 if closes[future_idx] > closes[idx] else 0
            self.assertEqual(t.y[i], expected)

    def test_drops_trailing_h_bars(self):
        closes = [float(c) for c in range(1, 41)]  # 1..40, all positive
        for horizon in ("1h", "4h", "12h", "24h"):
            t = build_direction_target(closes, horizon)
            self.assertEqual(t.n(), len(closes) - HORIZON_BARS[horizon])
            # No target index points at a close we don't have.
            for ti in t.target_close_idx:
                self.assertLess(ti, len(closes))


# ── Walk-forward splits ───────────────────────────────────────────────────
class TestWalkForward(unittest.TestCase):
    def test_train_strictly_before_test(self):
        folds = walk_forward_splits(n_rows=200, n_folds=4, purge_bars=2,
                                    embargo_bars=2, min_train=50)
        self.assertGreater(len(folds), 0)
        for f in folds:
            self.assertGreater(min(f.test_idx), max(f.train_idx))

    def test_purging_drops_trailing_train(self):
        folds = walk_forward_splits(n_rows=200, n_folds=4, purge_bars=5,
                                    embargo_bars=0, min_train=50)
        for f in folds:
            # Gap between max(train_idx) and min(test_idx) must be >= purge_bars.
            self.assertGreaterEqual(min(f.test_idx) - max(f.train_idx), 5)

    def test_embargo_drops_leading_test(self):
        folds = walk_forward_splits(n_rows=200, n_folds=4, purge_bars=0,
                                    embargo_bars=3, min_train=50)
        # The leading 3 test rows of each fold are dropped.
        for f in folds:
            # Reconstruct expected fold start, then verify embargo skipped 3.
            expected_start_no_embargo = max(f.train_idx) + 1
            self.assertEqual(min(f.test_idx),
                             expected_start_no_embargo + 3)

    def test_too_small_returns_empty(self):
        self.assertEqual(walk_forward_splits(n_rows=10, n_folds=5,
                                             purge_bars=0, embargo_bars=0,
                                             min_train=50), [])


# ── Scaler ────────────────────────────────────────────────────────────────
class TestScaler(unittest.TestCase):
    def test_fit_train_only(self):
        X_train = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
        X_test = [[100.0, 1000.0]]  # huge values — must NOT influence params
        scaler = fit_scaler(X_train)
        # mean column 0 = 2, mean column 1 = 20.
        self.assertAlmostEqual(scaler.means[0], 2.0)
        self.assertAlmostEqual(scaler.means[1], 20.0)
        # apply_scaler doesn't change scaler.
        before = (list(scaler.means), list(scaler.stds))
        apply_scaler(X_test, scaler)
        after = (list(scaler.means), list(scaler.stds))
        self.assertEqual(before, after)

    def test_zero_std_handled(self):
        X = [[1.0, 5.0], [1.0, 5.0]]  # both columns constant
        scaler = fit_scaler(X)
        out = apply_scaler(X, scaler)
        # Should be all zeros (since (x-mean)/1 = 0), not NaN/inf.
        for row in out:
            for v in row:
                self.assertEqual(v, 0.0)


# ── Baselines + metrics ───────────────────────────────────────────────────
class TestBaselineMetrics(unittest.TestCase):
    def test_perfect_predictor(self):
        probs = [0.99, 0.01, 0.99, 0.01]
        y = [1, 0, 1, 0]
        self.assertEqual(hit_rate(probs, y), 1.0)
        self.assertLess(brier(probs, y), 0.001)

    def test_worst_predictor(self):
        probs = [0.01, 0.99, 0.01, 0.99]
        y = [1, 0, 1, 0]
        self.assertEqual(hit_rate(probs, y), 0.0)
        self.assertGreater(brier(probs, y), 0.95)

    def test_majority_baseline_on_train(self):
        m = MajorityBaseline().fit([[0]] * 6, [1, 1, 1, 0, 0, 0], [{}])
        # 50% base rate clipped to 0.5.
        probs = m.predict_proba([[0]] * 4, [{}, {}, {}, {}])
        for p in probs:
            self.assertAlmostEqual(p, 0.5)

    def test_logistic_separates_easy_data(self):
        # Linearly separable dataset: feature x; label = 1 if x > 0 else 0.
        X = [[x / 10.0] for x in range(-50, 50)]
        y = [1 if row[0] > 0 else 0 for row in X]
        m = LogisticRegression(lr=0.5, n_iters=400, l2=0.0).fit(X, y)
        probs = m.predict_proba(X)
        # Hit rate should be very high (close to 1).
        self.assertGreater(hit_rate(probs, y), 0.95)


class TestECE(unittest.TestCase):
    def test_returns_none_below_threshold(self):
        # Fewer than 20 samples → None.
        self.assertIsNone(expected_calibration_error([0.1, 0.5, 0.9], [0, 1, 1]))

    def test_well_calibrated_low_ece(self):
        probs = [0.1, 0.1, 0.1, 0.1, 0.1] * 4  # 20 rows of 0.1
        y = [0] * 18 + [1, 1]                    # base rate 0.1 — well calibrated
        # All in one bin → too few non-empty bins → ECE returns None.
        self.assertIsNone(expected_calibration_error(probs, y))

    def test_miscalibrated_higher_ece(self):
        # Spread across at least 3 bins.
        probs = ([0.1] * 10 + [0.5] * 10 + [0.9] * 10)
        # Outcomes ignore probability — perfectly miscalibrated.
        y = [1] * 10 + [0] * 10 + [0] * 10
        ece = expected_calibration_error(probs, y)
        self.assertIsNotNone(ece)
        self.assertGreater(ece, 0.4)


# ── Calibrators ───────────────────────────────────────────────────────────
class TestCalibrators(unittest.TestCase):
    def test_platt_improves_miscalibrated(self):
        # Probabilities biased high by +0.2.
        true_p = [0.1, 0.3, 0.5, 0.7, 0.9] * 40
        miscal = [min(0.999, p + 0.2) for p in true_p]
        y = []
        rng_seed = 7
        # Build outcomes consistent with TRUE p (not miscal), deterministically.
        import random
        rng = random.Random(rng_seed)
        for p in true_p:
            y.append(1 if rng.random() < p else 0)
        platt = PlattScaler(n_iters=400, lr=0.2).fit(miscal, y)
        cal = platt.transform(miscal)
        before = brier(miscal, y)
        after = brier(cal, y)
        self.assertLessEqual(after, before + 1e-6)

    def test_isotonic_monotone(self):
        # Deliberately non-monotone raw probabilities.
        raw = [0.1, 0.3, 0.2, 0.4, 0.5, 0.6, 0.45, 0.7, 0.8, 0.9] * 5
        y = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1] * 5
        iso = IsotonicRegressor().fit(raw, y)
        # The fitted ys (sorted by raw) should be non-decreasing.
        if iso.ys:
            for i in range(1, len(iso.ys)):
                self.assertGreaterEqual(iso.ys[i] + 1e-9, iso.ys[i - 1])


# ── Registry ──────────────────────────────────────────────────────────────
class TestRegistry(unittest.TestCase):
    def test_rejects_non_shadow_prefix(self):
        bad = {
            "model_id": "logistic-1h",
            "kind": "logistic",
            "horizon": "1h",
            "features_version": FEATURES_VERSION,
            "trained_at": "2026-04-27T00:00:00Z",
            "shadow_status": "active",
            "fixture_only": True,
        }
        with self.assertRaises(ValueError):
            validate_model_entry(bad)

    def test_rejects_promoted_at_set(self):
        entry = {
            "model_id": "shadow-logistic-1h-v0.1.0",
            "kind": "logistic",
            "horizon": "1h",
            "features_version": FEATURES_VERSION,
            "trained_at": "2026-04-27T00:00:00Z",
            "shadow_status": "active",
            "fixture_only": True,
            "promoted_at": "2026-04-27T00:00:00Z",
        }
        with self.assertRaises(ValueError):
            validate_model_entry(entry)

    def test_write_requires_shadow_only(self):
        reg = empty_registry()
        reg["shadow_only"] = False
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "registry.json"
            with self.assertRaises(ValueError):
                write_registry(p, reg)

    def test_round_trip(self):
        reg = empty_registry()
        entry = {
            "model_id": "shadow-logistic-1h-v0.1.0",
            "kind": "logistic",
            "horizon": "1h",
            "features_version": FEATURES_VERSION,
            "trained_at": "2026-04-27T00:00:00Z",
            "shadow_status": "active",
            "fixture_only": True,
            "promoted_at": None,
        }
        add_or_replace_model(reg, entry)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "registry.json"
            write_registry(p, reg)
            text = p.read_text(encoding="utf-8")
            self.assertIn('"shadow_only": true', text)
            self.assertIn("shadow-logistic-1h-v0.1.0", text)


# ── Shadow forecast emitter ───────────────────────────────────────────────
class TestShadowForecast(unittest.TestCase):
    def test_row_matches_phase1_schema(self):
        row = build_shadow_forecast_row(
            model_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            p_up=0.55,
            entry_price=65000.0,
            regime="bull",
        )
        # Must include every required Phase 1 ledger field.
        for f in FORECAST_FIELDS:
            self.assertIn(f, row, f"missing {f}")
        # And it must pass Phase 1 validation as-is.
        validate_forecast(row)

    def test_low_p_flips_direction(self):
        row = build_shadow_forecast_row(
            model_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            p_up=0.30,
            entry_price=65000.0,
        )
        self.assertEqual(row["direction"], "down")
        self.assertAlmostEqual(row["probability"], 0.70)

    def test_rejects_non_shadow_id(self):
        with self.assertRaises(ValueError):
            build_shadow_forecast_row(
                model_id="logistic-1h-v0.1.0",  # missing 'shadow-' prefix
                horizon="1h",
                p_up=0.55,
                entry_price=65000.0,
            )


# ── Phase 2 closed-candle invariant carries forward ───────────────────────
class TestClosedCandleIntegration(unittest.TestCase):
    def test_drop_incomplete_then_features(self):
        # Build 50 closed + 1 live candle. Confirm features only see closed.
        closed_n = 50
        h = 60 * 60 * 1000
        now_ms = int(datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        for i in range(closed_n):
            ot = now_ms - (closed_n - i) * h
            ct = ot + h
            px = 30000.0 + i
            candles.append({
                "open_time_ms": ot, "close_time_ms": ct,
                "open": px, "high": px + 50, "low": px - 50, "close": px + 5,
                "volume": 10.0,
            })
        # Live candle:
        live_ot = now_ms
        live_ct = live_ot + h
        candles.append({
            "open_time_ms": live_ot, "close_time_ms": live_ct,
            "open": 99999.0, "high": 99999.0, "low": 99999.0, "close": 99999.0,
            "volume": 1.0,
        })
        now = datetime(2026, 4, 27, 12, 30, 0, tzinfo=timezone.utc)
        closed = drop_incomplete_candle(candles, now=now)
        self.assertEqual(len(closed), closed_n)
        frame = build_features(closed_candles=closed)
        self.assertEqual(frame.n_rows(), closed_n)
        # No feature row should reflect the 99999 live close.
        last_close_in_meta = frame.meta["closes"][-1]
        self.assertLess(last_close_in_meta, 99999.0)


# ── End-to-end smoke on synthetic ─────────────────────────────────────────
class TestEndToEndOnFixture(unittest.TestCase):
    def test_fixture_pipeline_runs(self):
        candles = make_synthetic_candles(n=400, seed=11)
        aux = make_synthetic_aux_series(candles)
        frame = build_features(
            closed_candles=candles,
            derivatives_series=aux["derivatives"],
            sentiment_series=aux["sentiment"],
            source_freshness_seconds=aux["freshness"],
            regime_series=aux["regime"],
        )
        target = build_direction_target(frame.meta["closes"], "1h")
        X = [frame.X[t] for t in target.valid_indices]
        y = list(target.y)
        folds = walk_forward_splits(
            n_rows=len(X), n_folds=3, purge_bars=1, embargo_bars=1, min_train=80,
        )
        self.assertGreater(len(folds), 0)
        for fold in folds:
            X_train = select(X, fold.train_idx)
            y_train = select(y, fold.train_idx)
            X_test = select(X, fold.test_idx)
            y_test = select(y, fold.test_idx)
            scaler = fit_scaler(X_train)
            X_train_s = apply_scaler(X_train, scaler)
            X_test_s = apply_scaler(X_test, scaler)
            m = LogisticRegression(lr=0.2, n_iters=200, l2=0.01).fit(X_train_s, y_train)
            probs = m.predict_proba(X_test_s)
            self.assertEqual(len(probs), len(y_test))
            self.assertTrue(all(0.0 <= p <= 1.0 for p in probs))


# ── Tree model graceful skip ──────────────────────────────────────────────
class TestTreeOptional(unittest.TestCase):
    def test_optional_dependency_skip(self):
        name, ctor = maybe_load_tree_model()
        # We don't assume anything about availability — just that the
        # function never raises and returns a (None, None) when missing.
        if name is None:
            self.assertIsNone(ctor)
        else:
            self.assertIn(name, ("xgboost", "lightgbm"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
