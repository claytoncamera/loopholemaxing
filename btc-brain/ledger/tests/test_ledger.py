"""
Tests for the BTC forecast ledger, resolver, and metrics generator.

Run:
    cd btc-brain/ledger && python -m unittest tests.test_ledger -v
or:
    cd btc-brain/ledger && python tests/test_ledger.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add scripts/ to path.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import ledger as ledger_mod  # noqa: E402
from ledger import Ledger, LedgerError, brier, logloss, parse_iso_utc, utc_now_iso  # noqa: E402
import metrics as metrics_mod  # noqa: E402
import price_source as ps  # noqa: E402
import resolve as resolve_mod  # noqa: E402


def _good_forecast(**over):
    base = {
        "forecast_id": "00000000-0000-0000-0000-000000000001",
        "issued_at": "2026-04-01T00:00:00Z",
        "asset": "BTCUSD",
        "horizon": "1h",
        "target_time": "2026-04-01T01:00:00Z",
        "target_rule": "close_above_entry",
        "direction": "up",
        "probability": 0.62,
        "entry_price": 67450.0,
        "model_version": "v0.1.0-baseline",
        "signal_version": "v0.1.0",
        "regime_at_issue": "chop",
        "feature_snapshot_uri": "snapshots/none.json",
        "source_snapshot_uri": "snapshots/none.json",
        "confidence_reason": "test",
        "invalidation": "BTC<60000",
        "created_by": "test",
        "status": "open",
    }
    base.update(over)
    return base


# ── A: append-only behavior ──────────────────────────────────────────────────
class TestAppendOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_does_not_rewrite_existing_lines(self):
        L = Ledger.at(self.root)
        f1 = _good_forecast(forecast_id="11111111-1111-1111-1111-111111111111")
        f2 = _good_forecast(forecast_id="22222222-2222-2222-2222-222222222222",
                            target_time="2026-04-01T02:00:00Z")
        L.append_forecast(f1)
        first_bytes = (self.root / "forecasts.jsonl").read_bytes()
        L.append_forecast(f2)
        after_bytes = (self.root / "forecasts.jsonl").read_bytes()
        # Critical invariant: the prefix is byte-identical.
        self.assertTrue(after_bytes.startswith(first_bytes),
                        "append-only file must not rewrite earlier bytes")
        # And we got two lines, both parse.
        rows = list(L.iter_forecasts())
        self.assertEqual(len(rows), 2)

    def test_duplicate_forecast_id_rejected(self):
        L = Ledger.at(self.root)
        f1 = _good_forecast()
        L.append_forecast(f1)
        with self.assertRaises(LedgerError):
            L.append_forecast(_good_forecast())

    def test_resolution_does_not_mutate_forecast(self):
        L = Ledger.at(self.root)
        f1 = _good_forecast()
        L.append_forecast(f1)
        before = (self.root / "forecasts.jsonl").read_bytes()
        L.append_resolution({
            "forecast_id": f1["forecast_id"],
            "resolved_at": "2026-04-01T01:01:00Z",
            "actual_close": 67500.0,
            "actual_return": (67500.0 - 67450.0) / 67450.0,
            "direction_correct": True,
            "brier_component": brier(0.62, 1),
            "logloss_component": logloss(0.62, 1),
            "status": "resolved",
            "resolver_version": "test",
            "candle_open_time": "2026-04-01T00:00:00Z",
            "candle_close_time": "2026-04-01T01:00:00Z",
            "price_source": "test",
        })
        after = (self.root / "forecasts.jsonl").read_bytes()
        self.assertEqual(before, after, "resolutions must never edit forecasts.jsonl")
        # Resolutions file exists separately.
        self.assertTrue((self.root / "resolutions.jsonl").exists())

    def test_double_resolution_rejected(self):
        L = Ledger.at(self.root)
        f1 = _good_forecast()
        L.append_forecast(f1)
        res = {
            "forecast_id": f1["forecast_id"], "resolved_at": "2026-04-01T01:01:00Z",
            "actual_close": 67500.0, "actual_return": 0.001, "direction_correct": True,
            "brier_component": 0.1, "logloss_component": 0.5, "status": "resolved",
            "resolver_version": "t", "candle_open_time": "2026-04-01T00:00:00Z",
            "candle_close_time": "2026-04-01T01:00:00Z", "price_source": "test",
        }
        L.append_resolution(res)
        with self.assertRaises(LedgerError):
            L.append_resolution(res)

    def test_forecast_row_cannot_carry_resolution_fields(self):
        L = Ledger.at(self.root)
        bad = _good_forecast()
        bad["actual_close"] = 70000.0
        with self.assertRaises(LedgerError):
            L.append_forecast(bad)


# ── B: math ──────────────────────────────────────────────────────────────────
class TestMath(unittest.TestCase):
    def test_brier_known(self):
        self.assertAlmostEqual(brier(1.0, 1), 0.0)
        self.assertAlmostEqual(brier(0.0, 0), 0.0)
        self.assertAlmostEqual(brier(0.5, 1), 0.25)
        self.assertAlmostEqual(brier(0.7, 0), 0.49)

    def test_logloss_known(self):
        self.assertAlmostEqual(logloss(1.0, 1), 0.0, places=4)
        self.assertAlmostEqual(logloss(0.0, 0), 0.0, places=4)
        # log-loss at p=0.5 with either outcome is ln 2.
        self.assertAlmostEqual(logloss(0.5, 1), math.log(2), places=6)
        self.assertAlmostEqual(logloss(0.5, 0), math.log(2), places=6)

    def test_logloss_clipped(self):
        # Should not blow up at p=0/1.
        self.assertGreater(logloss(1.0, 0), 5.0)
        self.assertGreater(logloss(0.0, 1), 5.0)


# ── C: resolver — exact target time, no early resolution, no incomplete ──────
class TestResolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_forecast(self, **over):
        L = Ledger.at(self.root)
        f = _good_forecast(**over)
        L.append_forecast(f)
        return f

    def _make_fetcher(self, target_iso: str, close_price: float):
        target = parse_iso_utc(target_iso)
        # Floor to the hour.
        ot = target.replace(minute=0, second=0, microsecond=0)
        ct = ot + timedelta(hours=1)
        return ps.make_fixture_fetcher([
            (int(ot.timestamp()*1000), int(ct.timestamp()*1000) - 1, close_price),
        ]), ot, ct

    def test_no_early_resolution(self):
        # target_time in the future — resolver should leave it alone.
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed_forecast(forecast_id="aaaa1111-0000-0000-0000-000000000001",
                            issued_at=utc_now_iso(),
                            target_time=future)
        summary = resolve_mod.run(self.root)
        self.assertEqual(summary["resolved"], [])
        self.assertEqual(summary["open_count"], 0,
                         "open_forecasts should exclude future-targeted rows")

    def test_exact_target_time_resolution_correct(self):
        target = "2026-04-01T01:00:00Z"
        self._seed_forecast(forecast_id="aaaa2222-0000-0000-0000-000000000002",
                            target_time=target,
                            entry_price=67450.0,
                            direction="up",
                            probability=0.62)
        # Build a fetcher that has the candle covering 00:00→01:00 with close 67500.
        ot = parse_iso_utc("2026-04-01T00:00:00Z")
        ct = parse_iso_utc("2026-04-01T01:00:00Z")
        # Resolver picks the candle that CLOSES at target. For target = 01:00,
        # that is the 00:00→01:00 candle (closeTime ~= 00:59:59.999). Its close
        # is the horizon price → 67500. The 01:00→02:00 candle is one too late.
        ot2 = ct
        ct2 = ot2 + timedelta(hours=1)
        fetcher = ps.make_fixture_fetcher([
            (int(ot.timestamp()*1000),  int(ct.timestamp()*1000) - 1, 67500.0),
            (int(ot2.timestamp()*1000), int(ct2.timestamp()*1000) - 1, 67460.0),
        ])
        summary = resolve_mod.run(self.root, fetcher=fetcher)
        self.assertEqual(len(summary["resolved"]), 1)
        r = summary["resolved"][0]
        self.assertTrue(r["direction_correct"])
        self.assertAlmostEqual(r["actual_close"], 67500.0)
        # Brier = (0.62-1)^2 = 0.1444
        self.assertAlmostEqual(r["brier_component"], (0.62-1)**2, places=6)

    def test_no_resolution_with_incomplete_candle(self):
        # Under the corrected rule the resolving bar CLOSES at target, so a
        # forecast must not resolve until its closing candle has finalized.
        # Here target is one second beyond the resolver's `now`: the candle
        # that closes at target has not finished, so the resolver refuses
        # (NotYet) rather than resolving on a partial bar.
        wall = parse_iso_utc("2026-04-01T01:00:00Z")
        target = wall  # candle 00:00→01:00 closes here
        ot = target - timedelta(hours=1)
        ct = target
        target_iso = target.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed_forecast(forecast_id="aaaa3333-0000-0000-0000-000000000003",
                            issued_at=ot.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            target_time=target_iso)
        fetcher = ps.make_fixture_fetcher([
            (int(ot.timestamp()*1000), int(ct.timestamp()*1000) - 1, 67500.0),
        ])
        # `now` sits one second before target → horizon boundary not yet passed,
        # so the forecast is not even eligible and nothing resolves on a
        # partial bar.
        now = target - timedelta(seconds=1)
        summary = resolve_mod.run(self.root, fetcher=fetcher, now=now)
        self.assertEqual(summary["resolved"], [])
        self.assertEqual(summary["open_count"], 0,
                         "a forecast whose closing candle has not finalized "
                         "must not be eligible for resolution")


# ── D: metrics generator ─────────────────────────────────────────────────────
class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _add(self, fid: str, p: float, correct: bool, horizon="1h",
             model="v0.1.0-baseline", resolved_at=None):
        L = Ledger.at(self.root)
        f = _good_forecast(forecast_id=fid, probability=p, horizon=horizon,
                           model_version=model)
        L.append_forecast(f)
        outcome = 1 if correct else 0
        L.append_resolution({
            "forecast_id": fid,
            "resolved_at": resolved_at or "2026-04-01T01:01:00Z",
            "actual_close": 67500.0 if correct else 67000.0,
            "actual_return": 0.001 if correct else -0.001,
            "direction_correct": correct,
            "brier_component": brier(p, outcome),
            "logloss_component": logloss(p, outcome),
            "status": "resolved",
            "resolver_version": "test",
            "candle_open_time": "2026-04-01T00:00:00Z",
            "candle_close_time": "2026-04-01T01:00:00Z",
            "price_source": "test",
        })

    def test_sample_size_and_display_ready(self):
        # Add 5 forecasts → below the default 20 threshold → display_ready False.
        for i in range(5):
            self._add(f"00000000-0000-0000-0000-{i:012d}", 0.6, i % 2 == 0)
        m = metrics_mod.build(self.root)
        self.assertEqual(m["total_resolved"], 5)
        self.assertFalse(m["global"]["display_ready"])
        self.assertEqual(m["global"]["n"], 5)

    def test_brier_average_matches_components(self):
        # Two forecasts: p=0.7 hit, p=0.4 miss.
        self._add("00000000-0000-0000-0000-aaaaaaaa0001", 0.7, True)
        self._add("00000000-0000-0000-0000-aaaaaaaa0002", 0.4, False)
        m = metrics_mod.build(self.root)
        expected = (brier(0.7, 1) + brier(0.4, 0)) / 2
        self.assertAlmostEqual(m["global"]["brier"], expected, places=6)
        self.assertAlmostEqual(m["global"]["hit_rate"], 0.5)

    def test_baseline_predict_majority(self):
        # 3 wins, 1 loss → base_rate = 0.75. Baseline hit_rate = 0.75.
        for i, c in enumerate([True, True, True, False]):
            self._add(f"00000000-0000-0000-0000-bbbbbbbb{i:04d}", 0.6, c)
        m = metrics_mod.build(self.root)
        self.assertAlmostEqual(m["global"]["base_rate"], 0.75)
        self.assertAlmostEqual(m["global"]["baseline_hit_rate"], 0.75)
        # Baseline brier: every row gets predicted at base_rate=0.75.
        # Brier = ((0.75-1)^2)*3 + ((0.75-0)^2)*1 / 4 = (3*0.0625 + 0.5625)/4 = 0.1875
        self.assertAlmostEqual(m["global"]["baseline_brier"], 0.1875, places=6)

    def test_missing_data_gives_empty_metrics(self):
        m = metrics_mod.build(self.root)
        self.assertEqual(m["total_forecasts"], 0)
        self.assertEqual(m["total_resolved"], 0)
        self.assertIsNone(m["global"]["hit_rate"])
        self.assertFalse(m["global"]["display_ready"])
        self.assertEqual(m["by_horizon"], {})

    def test_buckets_by_horizon_and_model(self):
        self._add("00000000-0000-0000-0000-cccc00000001", 0.6, True, horizon="1h",
                  model="v0.1.0-baseline")
        self._add("00000000-0000-0000-0000-cccc00000002", 0.6, False, horizon="4h",
                  model="v0.1.0-baseline")
        self._add("00000000-0000-0000-0000-cccc00000003", 0.6, True, horizon="4h",
                  model="v0.2.0-experimental")
        m = metrics_mod.build(self.root)
        self.assertEqual(set(m["by_horizon"].keys()), {"1h", "4h"})
        self.assertEqual(set(m["by_model_version"].keys()),
                         {"v0.1.0-baseline", "v0.2.0-experimental"})


# ── E: end-to-end smoke ─────────────────────────────────────────────────────
class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_issue_resolve_metrics_pipeline(self):
        L = Ledger.at(self.root)
        f = _good_forecast()
        L.append_forecast(f)
        # Target is 01:00 → the resolving candle is the 00:00→01:00 bar,
        # whose close is the horizon price.
        ot = parse_iso_utc("2026-04-01T00:00:00Z")
        ct = ot + timedelta(hours=1)
        fetcher = ps.make_fixture_fetcher([
            (int(ot.timestamp()*1000), int(ct.timestamp()*1000) - 1, 67800.0),
        ])
        summary = resolve_mod.run(self.root, fetcher=fetcher)
        self.assertEqual(len(summary["resolved"]), 1)
        m = metrics_mod.build(self.root)
        self.assertEqual(m["total_resolved"], 1)
        self.assertEqual(m["global"]["n"], 1)
        # Single sample → not display_ready.
        self.assertFalse(m["global"]["display_ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
