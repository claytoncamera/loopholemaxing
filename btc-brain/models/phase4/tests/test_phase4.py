"""
Phase 4 — Regime + Drift tests.

Run:
    cd btc-brain/models && python phase4/tests/test_phase4.py

Verifies the Phase 4 invariants:

  * Regime detector is causal — bar t's label depends only on closes[0..t].
  * Regime detector never future-smooths (truncating the series doesn't
    change earlier labels).
  * Regime assignment is deterministic on closed candles only.
  * Page-Hinkley fires on a step shift, stays quiet on a stationary series.
  * EWMA drift detector fires on a step shift, stays quiet on stationary.
  * KSWindow fires on a distribution shift, stays quiet on stationary.
  * Promotion gates report NOT READY until every prerequisite is met.
  * Promotion gates approve only with manual approval AND every other gate.
  * Retrain candidate report is valid JSON and includes triggers when
    drift fires.
  * Phase 4 report integrates with Phase 3 validation_report shape.
"""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE4_ROOT = HERE.parent
MODELS_ROOT = PHASE4_ROOT.parent
REPO_ROOT = MODELS_ROOT.parent.parent
sys.path.insert(0, str(MODELS_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from phase4.regime import (
    detect_regimes,
    regime_at,
    summarize_distribution,
    COARSE_LABELS,
    FINE_LABELS,
)
from phase4.drift import (
    PageHinkley,
    EWMADriftDetector,
    KSWindow,
    run_detectors,
)
from phase4.promotion_gates import (
    evaluate_promotion,
    DEFAULT_GATES,
)
from phase4.retrain import build_retrain_candidate, write_candidate
from phase4.report import build_phase4_report
from fixtures.synthetic import make_synthetic_candles


# ── Regime detector: causality and no-future-smoothing ───────────────────
class TestRegimeCausal(unittest.TestCase):
    def test_no_future_smoothing(self):
        closes = [float(c["close"]) for c in make_synthetic_candles(n=600, seed=1)]
        full = detect_regimes(closes)
        # Truncate the series — the prefix of labels MUST be identical.
        for cut in (300, 450, 599):
            partial = detect_regimes(closes[:cut])
            self.assertEqual(
                partial.coarse,
                full.coarse[:cut],
                msg=f"future-smoothing detected at cut={cut}",
            )
            self.assertEqual(partial.fine, full.fine[:cut])

    def test_warmup_is_unknown(self):
        closes = [100.0 + i * 0.01 for i in range(50)]
        a = detect_regimes(closes, warmup_bars=30)
        for i in range(30):
            self.assertEqual(a.coarse[i], "unknown")
            self.assertEqual(a.fine[i], "unknown")
        # Post-warmup not labelled unknown for monotonic data.
        self.assertNotEqual(a.coarse[-1], "unknown")

    def test_labels_are_in_known_set(self):
        closes = [float(c["close"]) for c in make_synthetic_candles(n=400, seed=3)]
        a = detect_regimes(closes)
        for c in a.coarse:
            self.assertIn(c, COARSE_LABELS)
        for f in a.fine:
            self.assertIn(f, FINE_LABELS)
        self.assertEqual(len(a.coarse), len(closes))
        self.assertEqual(len(a.fine), len(closes))

    def test_deterministic(self):
        closes = [float(c["close"]) for c in make_synthetic_candles(n=300, seed=5)]
        a1 = detect_regimes(closes)
        a2 = detect_regimes(closes)
        self.assertEqual(a1.coarse, a2.coarse)
        self.assertEqual(a1.fine, a2.fine)

    def test_uptrend_labelled_bull(self):
        closes = [100.0 * (1.001 ** i) for i in range(200)]
        a = detect_regimes(closes, warmup_bars=24)
        # Tail should clearly be bull (positive trend).
        self.assertEqual(a.coarse[-1], "bull")

    def test_downtrend_labelled_bear(self):
        closes = [100.0 * (0.999 ** i) for i in range(200)]
        a = detect_regimes(closes, warmup_bars=24)
        self.assertEqual(a.coarse[-1], "bear")

    def test_regime_at_single_bar(self):
        closes = [100.0 * (1.001 ** i) for i in range(100)]
        coarse, fine = regime_at(closes)
        self.assertEqual(coarse, "bull")
        self.assertIn(fine, FINE_LABELS)
        self.assertNotEqual(fine, "unknown")

    def test_summarize_distribution_sums_to_n(self):
        closes = [float(c["close"]) for c in make_synthetic_candles(n=200, seed=9)]
        a = detect_regimes(closes)
        d = summarize_distribution(a)
        self.assertEqual(d["n"], len(closes))
        self.assertAlmostEqual(sum(d["fine_proportions"].values()), 1.0, places=6)
        self.assertAlmostEqual(sum(d["coarse_proportions"].values()), 1.0, places=6)


# ── Drift detectors: trigger on shift, stable on stationary ──────────────
class TestPageHinkley(unittest.TestCase):
    def test_quiet_on_stationary(self):
        rng = random.Random(0)
        ph = PageHinkley(threshold=50.0, alpha=1e-4, min_n=30)
        any_alarm = False
        for _ in range(500):
            if ph.update(rng.gauss(0.25, 0.05)):
                any_alarm = True
                break
        self.assertFalse(any_alarm)

    def test_fires_on_step(self):
        rng = random.Random(1)
        ph = PageHinkley(threshold=20.0, alpha=1e-4, min_n=30)
        for _ in range(200):
            ph.update(rng.gauss(0.2, 0.02))
        fired = False
        for _ in range(500):
            # Big upward shift.
            if ph.update(rng.gauss(0.6, 0.02)):
                fired = True
                break
        self.assertTrue(fired)

    def test_min_n_blocks_early_alarm(self):
        ph = PageHinkley(threshold=0.001, alpha=0.0, min_n=50)
        # First 49 updates should never alarm regardless of value.
        for i in range(49):
            self.assertFalse(ph.update(100.0 if i % 2 else -100.0))


class TestEWMADrift(unittest.TestCase):
    def test_quiet_on_stationary(self):
        rng = random.Random(0)
        ew = EWMADriftDetector(min_n=30)
        any_alarm = False
        for _ in range(1000):
            if ew.update(rng.gauss(0.25, 0.05)):
                any_alarm = True
                break
        self.assertFalse(any_alarm)

    def test_fires_on_step(self):
        rng = random.Random(2)
        ew = EWMADriftDetector(fast_alpha=0.2, slow_alpha=0.005, k_sigma=2.0, min_n=20)
        for _ in range(200):
            ew.update(rng.gauss(0.2, 0.02))
        fired = False
        for _ in range(500):
            if ew.update(rng.gauss(0.7, 0.02)):
                fired = True
                break
        self.assertTrue(fired)


class TestKSWindow(unittest.TestCase):
    def test_quiet_on_stationary(self):
        rng = random.Random(3)
        ks = KSWindow(reference_size=100, recent_size=50, alpha=0.01, min_recent=30)
        any_alarm = False
        for _ in range(1000):
            if ks.update(rng.gauss(0.0, 1.0)):
                any_alarm = True
                break
        self.assertFalse(any_alarm)

    def test_fires_on_distribution_shift(self):
        rng = random.Random(4)
        ks = KSWindow(reference_size=200, recent_size=80, alpha=0.01, min_recent=50)
        for _ in range(400):
            ks.update(rng.gauss(0.0, 1.0))
        fired = False
        for _ in range(400):
            if ks.update(rng.gauss(2.0, 1.0)):
                fired = True
                break
        self.assertTrue(fired)


class TestRunDetectors(unittest.TestCase):
    def test_returns_summary(self):
        rng = random.Random(0)
        errs = [rng.gauss(0.3, 0.05) for _ in range(200)] + \
               [rng.gauss(0.7, 0.05) for _ in range(200)]
        feats = [rng.gauss(0.0, 1.0) for _ in range(200)] + \
                [rng.gauss(2.0, 1.0) for _ in range(200)]
        out = run_detectors(errs, feats)
        self.assertIn("page_hinkley", out)
        self.assertIn("ewma", out)
        self.assertIn("kswin", out)


# ── Promotion gates: NOT READY until every prerequisite met ──────────────
class TestPromotionGates(unittest.TestCase):
    def test_default_not_ready(self):
        d = evaluate_promotion(
            candidate_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            resolved_total=0,
            resolved_per_horizon={"1h": 0},
            shadow_days=0.0,
            metrics={"brier": 0.249, "log_loss": 0.69, "ece": None},
            baseline_briers={},
            drift_alarm_count=0,
            walkforward_folds=0,
        )
        self.assertFalse(d.ready_for_promotion)
        self.assertIn("NOT READY", d.summary)

    def test_brier_failure(self):
        d = evaluate_promotion(
            candidate_id="x", horizon="1h",
            resolved_total=100, resolved_per_horizon={"1h": 100},
            shadow_days=20.0,
            metrics={"brier": 0.30, "log_loss": 0.5, "ece": 0.05},
            baseline_briers={"random": 0.25},
            drift_alarm_count=0, walkforward_folds=5,
            approved_by="alice", approved_at="2026-04-27T00:00:00Z",
        )
        # Brier above threshold should fail.
        self.assertFalse(d.ready_for_promotion)
        names = {g.name: g.passed for g in d.gates}
        self.assertFalse(names["brier"])

    def test_drift_failure_blocks(self):
        d = evaluate_promotion(
            candidate_id="x", horizon="1h",
            resolved_total=100, resolved_per_horizon={"1h": 100},
            shadow_days=30.0,
            metrics={"brier": 0.20, "log_loss": 0.5, "ece": 0.05},
            baseline_briers={"random": 0.25},
            drift_alarm_count=5,  # severe drift in lookback window
            walkforward_folds=5,
            approved_by="alice", approved_at="2026-04-27T00:00:00Z",
        )
        self.assertFalse(d.ready_for_promotion)
        names = {g.name: g.passed for g in d.gates}
        self.assertFalse(names["no_severe_drift"])

    def test_manual_approval_required(self):
        d = evaluate_promotion(
            candidate_id="x", horizon="1h",
            resolved_total=100, resolved_per_horizon={"1h": 100},
            shadow_days=30.0,
            metrics={"brier": 0.20, "log_loss": 0.5, "ece": 0.05},
            baseline_briers={"random": 0.25},
            drift_alarm_count=0, walkforward_folds=5,
            regime_metrics={
                "bull": {"n": 50}, "bear": {"n": 50}, "chop": {"n": 50},
            },
            approved_by=None, approved_at=None,
        )
        self.assertFalse(d.ready_for_promotion)
        names = {g.name: g.passed for g in d.gates}
        self.assertFalse(names["manual_approval"])

    def test_passes_with_full_prerequisites(self):
        d = evaluate_promotion(
            candidate_id="x", horizon="1h",
            resolved_total=100, resolved_per_horizon={"1h": 100},
            shadow_days=30.0,
            metrics={"brier": 0.20, "log_loss": 0.5, "ece": 0.05},
            baseline_briers={"random": 0.25, "majority": 0.25},
            drift_alarm_count=0, walkforward_folds=5,
            regime_metrics={
                "bull": {"n": 30}, "bear": {"n": 30}, "chop": {"n": 30},
            },
            approved_by="alice", approved_at="2026-04-27T00:00:00Z",
        )
        for g in d.gates:
            self.assertTrue(g.passed, msg=f"gate {g.name} failed: {g.detail}")
        self.assertTrue(d.ready_for_promotion)
        self.assertEqual(d.summary, "all gates passed")

    def test_no_baseline_fails_beats_baseline(self):
        d = evaluate_promotion(
            candidate_id="x", horizon="1h",
            resolved_total=100, resolved_per_horizon={"1h": 100},
            shadow_days=30.0,
            metrics={"brier": 0.20, "log_loss": 0.5, "ece": 0.05},
            baseline_briers={},   # no baselines
            drift_alarm_count=0, walkforward_folds=5,
            approved_by="alice", approved_at="2026-04-27T00:00:00Z",
        )
        names = {g.name: g.passed for g in d.gates}
        self.assertFalse(names["beats_baseline_brier"])

    def test_default_gates_dict_present(self):
        # Sanity — every required gate name exists in defaults.
        for k in (
            "min_resolved_total", "min_resolved_per_horizon",
            "min_shadow_days", "max_brier", "max_log_loss", "max_ece",
            "must_beat_baseline_brier", "no_severe_drift",
            "require_manual_approval",
        ):
            self.assertIn(k, DEFAULT_GATES)


# ── Retrain candidate pipeline ───────────────────────────────────────────
class TestRetrainCandidate(unittest.TestCase):
    def test_drifting_streams_produce_triggers(self):
        candles = make_synthetic_candles(n=600, seed=11)
        closes = [c["close"] for c in candles]
        # Synthesize a drifting error stream.
        rng = random.Random(0)
        err = [rng.gauss(0.2, 0.02) for _ in range(300)] + \
              [rng.gauss(0.7, 0.02) for _ in range(300)]
        feat = [rng.gauss(0.0, 1.0) for _ in range(300)] + \
               [rng.gauss(2.0, 1.0) for _ in range(300)]
        c = build_retrain_candidate(
            candidate_id="cand-1",
            model_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            closes=closes,
            error_stream=err,
            feature_stream=feat,
            probs=[0.5] * len(err),
            y=[0] * len(err),
            fixture_only=True,
        )
        self.assertEqual(c.fixture_only, True)
        self.assertGreater(len(c.triggers), 0)
        self.assertEqual(c.sample_size, len(err))

    def test_stationary_streams_no_triggers_but_artifact_valid(self):
        candles = make_synthetic_candles(n=400, seed=17)
        closes = [c["close"] for c in candles]
        rng = random.Random(0)
        err = [rng.gauss(0.25, 0.05) for _ in range(400)]
        feat = [rng.gauss(0.0, 1.0) for _ in range(400)]
        c = build_retrain_candidate(
            candidate_id="cand-2",
            model_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            closes=closes,
            error_stream=err,
            feature_stream=feat,
            fixture_only=True,
        )
        self.assertEqual(len(c.triggers), 0)
        d = c.to_dict()
        self.assertEqual(d["schema_version"], "phase4-retrain-candidate-v1")
        # Round-trip JSON.
        s = json.dumps(d)
        json.loads(s)

    def test_writes_artifact(self):
        candles = make_synthetic_candles(n=200, seed=7)
        closes = [c["close"] for c in candles]
        c = build_retrain_candidate(
            candidate_id="cand-w",
            model_id="shadow-logistic-1h-v0.1.0",
            horizon="1h",
            closes=closes,
            error_stream=[0.3] * 100,
            fixture_only=True,
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "candidate.json"
            write_candidate(p, c)
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["fixture_only"], True)
            self.assertEqual(data["model_id"], "shadow-logistic-1h-v0.1.0")


# ── Phase 4 report integration ───────────────────────────────────────────
class TestPhase4Report(unittest.TestCase):
    def test_passthrough_when_phase3_empty(self):
        candles = make_synthetic_candles(n=400, seed=42)
        closes = [c["close"] for c in candles]
        report = build_phase4_report(
            phase3_validation_report={"horizons": {}},
            closes=closes,
            fixture_only=True,
        )
        self.assertTrue(report["fixture_only"])
        self.assertIn("regime_distribution", report)

    def test_decision_is_not_ready_in_fixture_mode(self):
        candles = make_synthetic_candles(n=400, seed=42)
        closes = [c["close"] for c in candles]
        # Fake Phase 3 report with one horizon and one model entry.
        p3 = {
            "horizons": {
                "1h": {
                    "n_folds": 5,
                    "n_labeled": 350,
                    "models": {
                        "logistic": {
                            "aggregate_metrics": {
                                "brier": 0.249,
                                "log_loss": 0.69,
                                "ece": None,
                                "regime_sliced": {
                                    "bull": {"n": 100, "brier": 0.24},
                                    "bear": {"n": 80, "brier": 0.26},
                                    "chop": {"n": 60, "brier": 0.25},
                                },
                            },
                        },
                    },
                },
            },
        }
        report = build_phase4_report(
            phase3_validation_report=p3, closes=closes, fixture_only=True,
        )
        models = report["horizons"]["1h"]["models"]
        decision = models["logistic"]["promotion_gate_evaluation"]
        # Fixture mode → no live ledger sample → NOT READY.
        self.assertFalse(decision["ready_for_promotion"])
        self.assertIn("NOT READY", decision["summary"])


# ── Closed-candle invariant: regime detector never sees live candle ──────
class TestRegimeClosedCandleOnly(unittest.TestCase):
    def test_appending_a_live_candle_doesnt_change_prior_labels(self):
        closes = [float(c["close"]) for c in make_synthetic_candles(n=300, seed=2)]
        before = detect_regimes(closes)
        # Simulate an in-progress candle being incorrectly appended; the
        # detector still produces causal labels for the original prefix
        # (i.e. earlier labels are unchanged).
        closes_with_live = list(closes) + [closes[-1] * 1.05]
        after = detect_regimes(closes_with_live)
        self.assertEqual(after.coarse[: len(closes)], before.coarse)
        self.assertEqual(after.fine[: len(closes)], before.fine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
