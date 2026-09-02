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
import emit_signal as emit_mod  # noqa: E402
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
             model="v0.1.0-baseline", resolved_at=None, direction="up",
             actual_return=None):
        L = Ledger.at(self.root)
        # Unique issued_at per row: since the 2026-08-11 multi-writer dedupe,
        # metrics count one forecast per (model, horizon, issued_at) bucket —
        # which is also the production issuer's own uniqueness invariant, so
        # a fixture reusing one timestamp models a state that cannot occur.
        self._issue_counter = getattr(self, "_issue_counter", 0) + 1
        issued_at = f"2026-04-01T00:{self._issue_counter % 60:02d}:00Z"
        f = _good_forecast(forecast_id=fid, probability=p, horizon=horizon,
                           model_version=model, issued_at=issued_at,
                           direction=direction)
        L.append_forecast(f)
        outcome = 1 if correct else 0
        # Default realized move: correct up-calls went up. A down-direction
        # fixture must pass actual_return itself (correct means it went DOWN).
        if actual_return is None:
            actual_return = 0.001 if correct else -0.001
        L.append_resolution({
            "forecast_id": fid,
            "resolved_at": resolved_at or "2026-04-01T01:01:00Z",
            "actual_close": 67500.0 if actual_return > 0 else 67000.0,
            "actual_return": actual_return,
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
        # 3 wins, 1 loss, all up-calls → outcome base_rate = 0.75, and the
        # realized tape is 3 up / 1 down → majority baseline = 0.75 too.
        for i, c in enumerate([True, True, True, False]):
            self._add(f"00000000-0000-0000-0000-bbbbbbbb{i:04d}", 0.6, c)
        m = metrics_mod.build(self.root)
        self.assertAlmostEqual(m["global"]["base_rate"], 0.75)
        self.assertAlmostEqual(m["global"]["baseline_hit_rate"], 0.75)
        # Baseline brier: every row gets predicted at base_rate=0.75.
        # Brier = ((0.75-1)^2)*3 + ((0.75-0)^2)*1 / 4 = (3*0.0625 + 0.5625)/4 = 0.1875
        self.assertAlmostEqual(m["global"]["baseline_brier"], 0.1875, places=6)

    def test_baseline_is_majority_direction_not_own_hits(self):
        # v0.3.1 regression test for the two lying fields. 2 correct
        # up-calls (+ret) and 2 correct down-calls (−ret): hit_rate = 1.0
        # while the realized tape is 50/50 up/down.
        #   - baseline_hit_rate must be the majority realized-direction rate
        #     (0.5), NOT max(hit_rate, 1−hit_rate) — the old bug made it
        #     equal hit_rate whenever hit_rate >= 0.5.
        #   - vs_majority_pp must be real percentage points (+50.0), not a
        #     fraction (+0.5).
        self._add("00000000-0000-0000-0000-cccccccc0001", 0.6, True)
        self._add("00000000-0000-0000-0000-cccccccc0002", 0.6, True)
        self._add("00000000-0000-0000-0000-cccccccc0003", 0.6, True,
                  direction="down", actual_return=-0.001)
        self._add("00000000-0000-0000-0000-cccccccc0004", 0.6, True,
                  direction="down", actual_return=-0.001)
        g = metrics_mod.build(self.root)["global"]
        self.assertAlmostEqual(g["hit_rate"], 1.0)
        self.assertAlmostEqual(g["always_up_rate"], 0.5)
        self.assertAlmostEqual(g["baseline_hit_rate"], 0.5)
        self.assertNotAlmostEqual(g["baseline_hit_rate"], g["hit_rate"])
        self.assertAlmostEqual(g["vs_majority_pp"], 50.0)

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


# ── F: batched fetch — few requests, paging, close==target lookup ────────────
def _hour_ms(iso: str) -> int:
    return int(parse_iso_utc(iso).timestamp() * 1000)


class TestBatchedFetch(unittest.TestCase):
    def _binance_rows(self, open_mss, prices):
        """Build Binance-shaped kline rows: closeTime = open + 1h - 1ms."""
        rows = []
        for o, px in zip(open_mss, prices):
            rows.append([o, "0", "0", "0", str(px), "0", o + 3600_000 - 1,
                         "0", 0, "0", "0", "0"])
        return rows

    def test_single_range_request_covers_many_targets(self):
        # 5 contiguous hourly targets resolve from ONE range request.
        base = parse_iso_utc("2026-04-01T01:00:00Z")
        targets = [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                   for i in range(5)]
        # Candles open at target-1h, close at target.
        open_mss = [int((base + timedelta(hours=i) - timedelta(hours=1)).timestamp() * 1000)
                    for i in range(5)]
        rows = self._binance_rows(open_mss, [100.0 + i for i in range(5)])

        calls = {"n": 0}

        def fetcher(symbol, interval, start_ms, end_ms):
            calls["n"] += 1
            return [r for r in rows if r[6] >= start_ms and r[0] <= end_ms]

        now = base + timedelta(hours=10)
        sources = [("binance", lambda s, e: ps._binance_range_map(s, e, fetcher))]
        out = ps.fetch_closes_for_targets(targets, now=now, sources=sources)
        self.assertEqual(len(out), 5)
        self.assertEqual(calls["n"], 1, "all targets must come from one request")
        # Each target maps to the candle whose close == target.
        for i, t in enumerate(targets):
            self.assertAlmostEqual(out[t].close_price, 100.0 + i)
            # close_time is the bar's true closeTime (…:59.999), within 1s of target.
            self.assertLessEqual(
                abs((out[t].close_time - parse_iso_utc(t)).total_seconds()), 1.0)

    def test_paging_past_1000_candles(self):
        # 1500 contiguous hourly candles → must page (Binance cap 1000/req).
        base = parse_iso_utc("2026-01-01T01:00:00Z")
        n = 1500
        open_mss = [int((base + timedelta(hours=i) - timedelta(hours=1)).timestamp() * 1000)
                    for i in range(n)]
        all_rows = self._binance_rows(open_mss, [float(i) for i in range(n)])

        calls = {"n": 0}

        def fetcher(symbol, interval, start_ms, end_ms):
            calls["n"] += 1
            page = [r for r in all_rows if r[6] >= start_ms and r[0] <= end_ms]
            return page[:1000]  # enforce the real 1000-candle cap

        s = open_mss[0]
        e = open_mss[-1] + 3600_000
        cmap = ps._binance_range_map(s, e, fetcher)
        self.assertEqual(len(cmap), n, "paging must collect every candle")
        self.assertGreaterEqual(calls["n"], 2, "1500 candles cannot fit one page")
        # First and last targets resolve correctly.
        first_close = parse_iso_utc("2026-01-01T01:00:00Z")
        last_close = base + timedelta(hours=n - 1)
        self.assertIn(round(first_close.timestamp()), cmap)
        self.assertIn(round(last_close.timestamp()), cmap)

    def test_lookup_returns_candle_whose_close_equals_target(self):
        # Off-by-one guard at the batched layer: target 06:00 must select the
        # 05:00→06:00 bar (close 06:00), NOT the 06:00→07:00 bar.
        t = "2026-04-01T06:00:00Z"
        right_open = _hour_ms("2026-04-01T05:00:00Z")
        wrong_open = _hour_ms("2026-04-01T06:00:00Z")
        rows = self._binance_rows([right_open, wrong_open], [500.0, 999.0])

        def fetcher(symbol, interval, start_ms, end_ms):
            return [r for r in rows if r[6] >= start_ms and r[0] <= end_ms]

        now = parse_iso_utc("2026-04-01T12:00:00Z")
        sources = [("binance", lambda s, e: ps._binance_range_map(s, e, fetcher))]
        out = ps.fetch_closes_for_targets([t], now=now, sources=sources)
        self.assertAlmostEqual(out[t].close_price, 500.0,
                               msg="must pick the bar that CLOSES at target")

    def test_future_target_omitted_no_error(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = ps.fetch_closes_for_targets([future], sources=[
            ("binance", lambda s, e: {})])
        self.assertEqual(out, {})


# ── G: fallback chain — binance->coingecko->kraken, provenance recorded ───────
class TestFallbackChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = "2026-04-01T06:00:00Z"
        self.target_dt = parse_iso_utc(self.target)

    def tearDown(self):
        self.tmp.cleanup()

    def _candle(self, source, px):
        ct = self.target_dt
        ot = ct - timedelta(hours=1)
        return ps.Candle(open_time=ot, close_time=ct, close_price=px, source=source)

    def _source(self, tag, px, fail=False):
        def fn(s, e):
            if fail:
                raise ps.PriceFetchError(f"{tag} down")
            return {round(self.target_dt.timestamp()): self._candle(tag, px)}
        return (tag, fn)

    def _now(self):
        return self.target_dt + timedelta(hours=1)

    def test_binance_used_when_up(self):
        sources = [self._source("binance", 100.0),
                   self._source("coingecko", 200.0),
                   self._source("kraken", 300.0)]
        out = ps.fetch_closes_for_targets([self.target], now=self._now(), sources=sources)
        self.assertEqual(out[self.target].source, "binance")
        self.assertAlmostEqual(out[self.target].close_price, 100.0)

    def test_falls_back_to_coingecko_when_binance_fails(self):
        sources = [self._source("binance", 100.0, fail=True),
                   self._source("coingecko", 200.0),
                   self._source("kraken", 300.0)]
        stats = {}
        out = ps.fetch_closes_for_targets([self.target], now=self._now(),
                                          sources=sources, stats=stats)
        self.assertEqual(out[self.target].source, "coingecko")
        self.assertIn("binance", stats["source_errors"])

    def test_falls_back_to_kraken_when_binance_and_coingecko_fail(self):
        sources = [self._source("binance", 100.0, fail=True),
                   self._source("coingecko", 200.0, fail=True),
                   self._source("kraken", 300.0)]
        out = ps.fetch_closes_for_targets([self.target], now=self._now(), sources=sources)
        self.assertEqual(out[self.target].source, "kraken")
        self.assertAlmostEqual(out[self.target].close_price, 300.0)

    def test_all_sources_fail_leaves_target_open(self):
        sources = [self._source("binance", 100.0, fail=True),
                   self._source("coingecko", 200.0, fail=True),
                   self._source("kraken", 300.0, fail=True)]
        out = ps.fetch_closes_for_targets([self.target], now=self._now(), sources=sources)
        self.assertEqual(out, {}, "no source → target stays unresolved, never guessed")

    def test_recorded_price_source_in_resolution(self):
        # End-to-end: a forecast resolved via the kraken fallback records
        # price_source == "kraken" in the resolution row.
        L = Ledger.at(self.root)
        f = _good_forecast(forecast_id="ffff0000-0000-0000-0000-00000000000a",
                           target_time=self.target, issued_at="2026-04-01T05:00:00Z")
        L.append_forecast(f)
        sources = [self._source("binance", 100.0, fail=True),
                   self._source("coingecko", 200.0, fail=True),
                   self._source("kraken", 67500.0)]
        summary = resolve_mod.run(self.root, now=self._now(), sources=sources)
        self.assertEqual(len(summary["resolved"]), 1)
        self.assertEqual(summary["resolved"][0]["price_source"], "kraken")
        # And it persisted to the ledger and validates.
        rows = list(L.iter_resolutions())
        self.assertEqual(rows[0]["price_source"], "kraken")


# ── H: per-source alignment (timestamp semantics) ────────────────────────────
class TestSourceAlignment(unittest.TestCase):
    def test_coingecko_30m_bar_aligns_to_hour_close(self):
        # CoinGecko OHLC ts = bar OPEN. The :30 bar (opens target-30m) closes
        # at the hour boundary; the :00 bar opens at the hour and must NOT be
        # picked for that target.
        target = parse_iso_utc("2026-04-01T18:00:00Z")
        open_30 = int((target - timedelta(minutes=30)).timestamp() * 1000)
        open_00 = int(target.timestamp() * 1000)
        rows = [[open_30, 0, 0, 0, 62233.0], [open_00, 0, 0, 0, 62139.0]]
        cmap = ps._coingecko_range_map(
            int(target.timestamp() * 1000) - 3600_000,
            int(target.timestamp() * 1000),
            fetcher=lambda: rows,
        )
        c = cmap.get(round(target.timestamp()))
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.close_price, 62233.0)

    def test_kraken_open_seconds_aligns_to_hour_close(self):
        # Kraken `time` = bar OPEN in seconds. The bar with time==target-3600
        # closes at target.
        target = parse_iso_utc("2026-04-01T06:00:00Z")
        open_s = int(target.timestamp()) - 3600
        payload = {"error": [], "result": {
            "XXBTZUSD": [[open_s, "0", "0", "0", "61305.5", "0", "0", 0]],
            "last": open_s,
        }}
        cmap = ps._kraken_range_map(
            int(target.timestamp() * 1000) - 3600_000,
            int(target.timestamp() * 1000),
            fetcher=lambda since_s: payload,
        )
        c = cmap.get(round(target.timestamp()))
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.close_price, 61305.5)


# ── I: off-by-one regression lock (single-target path) ───────────────────────
class TestOffByOneRegressionLock(unittest.TestCase):
    """Locks the candle-close-at-target rule so it can't silently regress.

    A forecast targeting 06:00 must resolve to the close of the 05:00→06:00
    candle (closeTime ~05:59:59.999), NOT the 06:00→07:00 candle. The old bug
    selected the latter and returned its 07:00 close — one candle late.
    """

    def test_single_target_picks_candle_closing_at_target(self):
        target = "2026-04-01T06:00:00Z"
        right_open = parse_iso_utc("2026-04-01T05:00:00Z")
        right_close = parse_iso_utc("2026-04-01T06:00:00Z")
        wrong_open = parse_iso_utc("2026-04-01T06:00:00Z")
        wrong_close = parse_iso_utc("2026-04-01T07:00:00Z")
        fetcher = ps.make_fixture_fetcher([
            (int(right_open.timestamp() * 1000), int(right_close.timestamp() * 1000) - 1, 500.0),
            (int(wrong_open.timestamp() * 1000), int(wrong_close.timestamp() * 1000) - 1, 999.0),
        ])
        now = parse_iso_utc("2026-04-01T12:00:00Z")
        c = ps.fetch_close_for_target(target, now=now, fetcher=fetcher)
        self.assertAlmostEqual(c.close_price, 500.0)
        self.assertLessEqual(
            abs((c.close_time - right_close).total_seconds()), 1.0)
        self.assertEqual(c.open_time, right_open)

    def test_batched_and_single_agree_on_target_candle(self):
        target = "2026-04-01T06:00:00Z"
        right_open = parse_iso_utc("2026-04-01T05:00:00Z")
        right_close = parse_iso_utc("2026-04-01T06:00:00Z")
        wrong_open = parse_iso_utc("2026-04-01T06:00:00Z")
        wrong_close = parse_iso_utc("2026-04-01T07:00:00Z")
        candles = [
            (int(right_open.timestamp() * 1000), int(right_close.timestamp() * 1000) - 1, 500.0),
            (int(wrong_open.timestamp() * 1000), int(wrong_close.timestamp() * 1000) - 1, 999.0),
        ]
        fetcher = ps.make_fixture_fetcher(candles)
        now = parse_iso_utc("2026-04-01T12:00:00Z")
        single = ps.fetch_close_for_target(target, now=now, fetcher=fetcher)
        sources = [("binance", lambda s, e: ps._binance_range_map(s, e, fetcher))]
        batched = ps.fetch_closes_for_targets([target], now=now, sources=sources)
        self.assertAlmostEqual(single.close_price, batched[target].close_price)
        self.assertEqual(single.close_time, batched[target].close_time)


# ── Metrics v0.2 edge fields ─────────────────────────────────────────────────
class TestMetricsV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_resolved(self, n_up_correct=6, n_up_wrong=2, n_down_correct=4, n_down_wrong=2):
        L = Ledger.at(self.root)
        fid = 1
        rows = []
        # up correct → actual_return > 0
        for i in range(n_up_correct):
            f = _good_forecast(
                forecast_id=f"{fid:032x}"[:36].replace("x", "0") if False else None,
                horizon="24h",
                direction="up",
                target_rule="close_above_entry",
                probability=0.52,
                entry_price=100.0,
            )
            # unique ids
            import uuid
            f["forecast_id"] = str(uuid.uuid4())
            f["horizon"] = "24h"
            L.append_forecast(f)
            res = {
                "forecast_id": f["forecast_id"],
                "resolved_at": "2026-07-01T00:00:00Z",
                "actual_close": 101.0,
                "actual_return": 0.01,
                "direction_correct": True,
                "brier_component": 0.23,
                "logloss_component": 0.65,
                "status": "resolved",
                "resolver_version": "test",
                "candle_open_time": "2026-06-30T23:00:00Z",
                "candle_close_time": "2026-07-01T00:00:00Z",
                "price_source": "test",
            }
            L.append_resolution(res)
            fid += 1
        for i in range(n_up_wrong):
            import uuid
            f = _good_forecast(horizon="24h", direction="up", target_rule="close_above_entry",
                               probability=0.52, entry_price=100.0)
            f["forecast_id"] = str(uuid.uuid4())
            f["horizon"] = "24h"
            L.append_forecast(f)
            L.append_resolution({
                "forecast_id": f["forecast_id"],
                "resolved_at": "2026-07-01T00:00:00Z",
                "actual_close": 99.0,
                "actual_return": -0.01,
                "direction_correct": False,
                "brier_component": 0.27,
                "logloss_component": 0.73,
                "status": "resolved",
                "resolver_version": "test",
                "candle_open_time": "2026-06-30T23:00:00Z",
                "candle_close_time": "2026-07-01T00:00:00Z",
                "price_source": "test",
            })
        for i in range(n_down_correct):
            import uuid
            f = _good_forecast(horizon="24h", direction="down", target_rule="close_below_entry",
                               probability=0.52, entry_price=100.0)
            f["forecast_id"] = str(uuid.uuid4())
            f["horizon"] = "24h"
            L.append_forecast(f)
            L.append_resolution({
                "forecast_id": f["forecast_id"],
                "resolved_at": "2026-07-01T00:00:00Z",
                "actual_close": 99.0,
                "actual_return": -0.01,
                "direction_correct": True,
                "brier_component": 0.23,
                "logloss_component": 0.65,
                "status": "resolved",
                "resolver_version": "test",
                "candle_open_time": "2026-06-30T23:00:00Z",
                "candle_close_time": "2026-07-01T00:00:00Z",
                "price_source": "test",
            })
        for i in range(n_down_wrong):
            import uuid
            f = _good_forecast(horizon="24h", direction="down", target_rule="close_below_entry",
                               probability=0.52, entry_price=100.0)
            f["forecast_id"] = str(uuid.uuid4())
            f["horizon"] = "24h"
            L.append_forecast(f)
            L.append_resolution({
                "forecast_id": f["forecast_id"],
                "resolved_at": "2026-07-01T00:00:00Z",
                "actual_close": 101.0,
                "actual_return": 0.01,
                "direction_correct": False,
                "brier_component": 0.27,
                "logloss_component": 0.73,
                "status": "resolved",
                "resolver_version": "test",
                "candle_open_time": "2026-06-30T23:00:00Z",
                "candle_close_time": "2026-07-01T00:00:00Z",
                "price_source": "test",
            })

    def test_expectancy_and_direction_fields(self):
        self._seed_resolved()
        m = metrics_mod.build(self.root, min_n_display=5)
        self.assertEqual(m["metrics_version"], "metrics-v0.3.1")
        h = m["by_horizon"]["24h"]
        self.assertIn("expectancy_bps", h)
        self.assertIn("expectancy_maker_2bps", h)
        self.assertIn("hit_up", h)
        self.assertIn("hit_down", h)
        self.assertIn("vs_majority_pp", h)
        self.assertIn("edge_scoreboard", m)
        self.assertIn("by_direction", m)
        # 6+4 correct of 14 = ~0.714 hit
        self.assertGreater(h["hit_rate"], 0.6)
        # positive expectancy expected
        self.assertGreater(h["expectancy_bps"], 0)


# ── Shared seeding helper for the v0.3 suites ────────────────────────────────
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_pair(root: Path, *, issued_at: str, target_time: str,
               horizon: str = "24h", model: str = "v9.9.9-test",
               direction: str = "up", probability: float = 0.52,
               correct: bool = True, ret: float = 0.01,
               entry: float = 100.0, resolved_at: str | None = None,
               resolve_row: bool = True) -> dict:
    """Append one forecast (and optionally its resolution) with full control.

    `ret` is the RAW market return (positive = price went up), independent of
    `direction`; `correct` is written verbatim as direction_correct.
    """
    import uuid as _uuid
    L = Ledger.at(root)
    f = _good_forecast(
        forecast_id=str(_uuid.uuid4()),
        issued_at=issued_at,
        target_time=target_time,
        horizon=horizon,
        model_version=model,
        direction=direction,
        probability=probability,
        entry_price=entry,
        target_rule=("close_above_entry" if direction == "up"
                     else "close_below_entry"),
    )
    L.append_forecast(f)
    if resolve_row:
        o = 1 if correct else 0
        L.append_resolution({
            "forecast_id": f["forecast_id"],
            "resolved_at": resolved_at or target_time,
            "actual_close": entry * (1 + ret),
            "actual_return": ret,
            "direction_correct": correct,
            "brier_component": brier(probability, o),
            "logloss_component": logloss(probability, o),
            "status": "resolved",
            "resolver_version": "test",
            "candle_open_time": issued_at,
            "candle_close_time": target_time,
            "price_source": "test",
        })
    return f


# ── J: Wilson lower bound ────────────────────────────────────────────────────
class TestWilsonLB(unittest.TestCase):
    def test_zero_n(self):
        self.assertEqual(metrics_mod.wilson_lb(0.6, 0), 0.0)

    def test_known_value(self):
        # Hand-checked: p=0.6, n=105, z=1.96 → ≈ 0.5044.
        self.assertAlmostEqual(metrics_mod.wilson_lb(0.6, 105), 0.5044, places=3)

    def test_matches_edge_hunter_formula(self):
        import edge_hunter as eh
        for p, n in [(0.5, 10), (0.52, 62), (0.7, 45), (0.435, 62)]:
            self.assertAlmostEqual(metrics_mod.wilson_lb(p, n),
                                   eh._wilson_lower(p, n), places=12)

    def test_monotone_in_n(self):
        # More evidence at the same rate → tighter (higher) lower bound.
        self.assertLess(metrics_mod.wilson_lb(0.6, 20),
                        metrics_mod.wilson_lb(0.6, 200))

    def test_always_below_p_and_nonnegative(self):
        for p, n in [(0.05, 8), (0.5, 30), (0.95, 30)]:
            lb = metrics_mod.wilson_lb(p, n)
            self.assertGreaterEqual(lb, 0.0)
            self.assertLess(lb, p)

    def test_in_buckets(self):
        # by_horizon / by_model_horizon buckets carry wilson_lb_95.
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            now = datetime.now(timezone.utc)
            for i in range(10):
                t0 = now - timedelta(days=2, hours=i + 1)
                _seed_pair(root, issued_at=_iso(t0),
                           target_time=_iso(t0 + timedelta(hours=24)),
                           model="vA", correct=(i % 2 == 0),
                           ret=(0.01 if i % 2 == 0 else -0.01))
            m = metrics_mod.build(root)
            h = m["by_horizon"]["24h"]
            self.assertAlmostEqual(h["wilson_lb_95"],
                                   metrics_mod.wilson_lb(h["hit_rate"], h["n"]),
                                   places=12)
            mh = m["by_model_horizon"]["vA|24h"]
            self.assertEqual(mh["n"], 10)
            self.assertIn("wilson_lb_95", mh)
        finally:
            tmp.cleanup()


# ── K: per-horizon rolling windows keyed on issued_at ────────────────────────
class TestRollingIssuedAt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_issued_at_keying_excludes_old_issue_recent_resolve(self):
        # Row A: issued 40d ago, resolved yesterday. resolved_at-keyed legacy
        # window counts it; the new issued_at-keyed window must NOT.
        a_issue = self.now - timedelta(days=40)
        _seed_pair(self.root, issued_at=_iso(a_issue),
                   target_time=_iso(a_issue + timedelta(hours=24)),
                   model="vM", correct=True, ret=0.01,
                   resolved_at=_iso(self.now - timedelta(days=1)))
        # Row B: issued 5d ago, resolved 4d ago — inside both windows.
        b_issue = self.now - timedelta(days=5)
        _seed_pair(self.root, issued_at=_iso(b_issue),
                   target_time=_iso(b_issue + timedelta(hours=24)),
                   model="vM", correct=False, ret=-0.01)
        m = metrics_mod.build(self.root)
        self.assertEqual(m["rolling"]["30d"]["n"], 2,
                         "legacy global window stays resolved_at-keyed")
        r_h = m["rolling"]["by_horizon"]["24h"]["30d"]
        self.assertEqual(r_h["n"], 1,
                         "issued_at-keyed window must drop the 40d-old issue")
        self.assertAlmostEqual(r_h["hit_rate"], 0.0)
        r_mh = m["rolling"]["by_model_horizon"]["vM|24h"]["30d"]
        self.assertEqual(r_mh["n"], 1)
        # 90d window catches both.
        self.assertEqual(m["rolling"]["by_horizon"]["24h"]["90d"]["n"], 2)

    def test_windows_do_not_mix_horizons(self):
        t0 = self.now - timedelta(days=3)
        _seed_pair(self.root, issued_at=_iso(t0),
                   target_time=_iso(t0 + timedelta(hours=24)),
                   horizon="24h", model="vM", correct=True, ret=0.01)
        _seed_pair(self.root, issued_at=_iso(t0 + timedelta(hours=1)),
                   target_time=_iso(t0 + timedelta(hours=13)),
                   horizon="12h", model="vM", correct=False, ret=-0.01)
        m = metrics_mod.build(self.root)
        self.assertEqual(m["rolling"]["by_horizon"]["24h"]["30d"]["n"], 1)
        self.assertEqual(m["rolling"]["by_horizon"]["12h"]["30d"]["n"], 1)
        self.assertEqual(m["rolling"]["by_model_horizon"]["vM|24h"]["30d"]["n"], 1)
        self.assertAlmostEqual(
            m["rolling"]["by_model_horizon"]["vM|24h"]["30d"]["hit_rate"], 1.0)

    def test_compact_bucket_fields_and_maker_fee(self):
        t0 = self.now - timedelta(days=2)
        for i, (c, ret) in enumerate([(True, 0.01), (True, 0.02), (False, -0.01)]):
            _seed_pair(self.root, issued_at=_iso(t0 + timedelta(hours=i)),
                       target_time=_iso(t0 + timedelta(hours=24 + i)),
                       model="vM", correct=c, ret=ret)
        m = metrics_mod.build(self.root)
        b = m["rolling"]["by_model_horizon"]["vM|24h"]["7d"]
        for k in ("n", "hit_rate", "brier", "expectancy_bps",
                  "expectancy_maker_2bps", "wilson_lb_95"):
            self.assertIn(k, b)
        # expectancy: mean(0.01, 0.02, -0.01) = 0.006667 → 66.67 bps gross
        self.assertAlmostEqual(b["expectancy_bps"], 200.0 / 3.0, places=6)
        self.assertAlmostEqual(b["expectancy_maker_2bps"],
                               200.0 / 3.0 - 2.0, places=6)
        self.assertEqual(
            m["rolling"]["window_basis"]["by_model_horizon"], "issued_at")


# ── L: ECE with quantile bins ────────────────────────────────────────────────
class TestECEQuantile(unittest.TestCase):
    def test_below_min_n_is_null(self):
        pairs = [(0.52, 1)] * 49
        self.assertIsNone(metrics_mod._ece(pairs))

    def test_uniform_prob_all_hits(self):
        # All p=0.52, all outcome 1 → every quantile bin |0.52-1| → ECE 0.48.
        pairs = [(0.52, 1)] * 50
        self.assertAlmostEqual(metrics_mod._ece(pairs), 0.48, places=9)

    def test_perfectly_calibrated_narrow_band(self):
        # 100 pairs at p=0.50 (half hit) + 100 at p=0.55 (55 hit) → tiny ECE.
        pairs = ([(0.50, 1)] * 50 + [(0.50, 0)] * 50
                 + [(0.55, 1)] * 55 + [(0.55, 0)] * 45)
        e = metrics_mod._ece(pairs)
        self.assertIsNotNone(e)
        self.assertLess(e, 0.03)

    def test_computable_on_narrow_prob_range(self):
        # The old fixed-decile ECE was ALWAYS null on [0.50, 0.55]. Quantile
        # bins must produce a number once n >= 50.
        import random
        rng = random.Random(7)
        pairs = [(0.50 + 0.05 * rng.random(), rng.randint(0, 1))
                 for _ in range(60)]
        self.assertIsNotNone(metrics_mod._ece(pairs))

    def test_emitted_per_horizon_and_global(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            now = datetime.now(timezone.utc)
            for i in range(50):
                t0 = now - timedelta(days=10) + timedelta(hours=i)
                _seed_pair(root, issued_at=_iso(t0),
                           target_time=_iso(t0 + timedelta(hours=24)),
                           model="vE", probability=0.50 + 0.001 * (i % 50),
                           correct=(i % 2 == 0),
                           ret=(0.01 if i % 2 == 0 else -0.01))
            m = metrics_mod.build(root)
            self.assertIsNotNone(m["global"]["ece"])
            self.assertIsNotNone(m["by_horizon"]["24h"]["ece"])
            # n < 50 buckets stay null (honesty on thin slices).
            self.assertEqual(m["by_horizon"]["24h"]["n"], 50)
        finally:
            tmp.cleanup()


# ── M: trades.json — paper tape fee math + curve ─────────────────────────────
class TestTradesJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_up_seq(self, model, rets, start_days_ago=20):
        t0 = self.now - timedelta(days=start_days_ago)
        for i, ret in enumerate(rets):
            _seed_pair(self.root, issued_at=_iso(t0 + timedelta(hours=i)),
                       target_time=_iso(t0 + timedelta(hours=24 + i)),
                       model=model, direction="up", correct=(ret > 0), ret=ret)

    def test_fee_math_curve_and_drawdown(self):
        rets = [0.01, -0.02, 0.005, 0.01, -0.01, 0.02]
        self._seed_up_seq("vT", rets)
        doc = metrics_mod.build_trades(self.root)
        self.assertEqual(doc["schema_version"], "trades-v0.1.0")
        self.assertEqual(doc["fee_bps"], {"maker_rt": 2, "taker_rt": 10})
        self.assertEqual(len(doc["groups"]), 1)
        g = doc["groups"][0]
        self.assertEqual((g["model_version"], g["horizon"]), ("vT", "24h"))
        self.assertEqual(g["n"], 6)
        self.assertEqual(g["wins"], 4)
        self.assertAlmostEqual(g["hit_rate"], 4 / 6)
        # makers: 98, -202, 48, 98, -102, 198 → cum 98,-104,-56,42,-60,138
        makers = [r * 10000.0 - 2.0 for r in rets]
        self.assertAlmostEqual(g["sum_bps_maker"], sum(makers), places=3)
        self.assertAlmostEqual(g["avg_bps_maker"], sum(makers) / 6, places=3)
        self.assertAlmostEqual(g["max_drawdown_bps_maker"], 202.0, places=3)
        cums = []
        c = 0.0
        for mk in makers:
            c += mk
            cums.append(c)
        self.assertEqual(len(g["curve"]), 6)
        for (ts, cum), want in zip(g["curve"], cums):
            self.assertIsInstance(ts, int)
            self.assertAlmostEqual(cum, want, places=3)
        # curve timestamps are issued_at epoch-seconds, ascending
        self.assertEqual([p[0] for p in g["curve"]],
                         sorted(p[0] for p in g["curve"]))
        t = g["last_trades"][0]
        for k in ("issued_at", "direction", "probability", "entry_price",
                  "exit_price", "ret_bps_gross", "ret_bps_maker", "win"):
            self.assertIn(k, t)
        self.assertAlmostEqual(t["ret_bps_gross"], 100.0, places=3)
        self.assertAlmostEqual(t["ret_bps_maker"], 98.0, places=3)
        self.assertTrue(t["win"])

    def test_down_direction_sign(self):
        # 5 correct "down" calls on -1% moves → gross +100 each, maker +98.
        t0 = self.now - timedelta(days=6)
        for i in range(5):
            _seed_pair(self.root, issued_at=_iso(t0 + timedelta(hours=i)),
                       target_time=_iso(t0 + timedelta(hours=24 + i)),
                       model="vD", direction="down", correct=True, ret=-0.01)
        g = metrics_mod.build_trades(self.root)["groups"][0]
        self.assertAlmostEqual(g["sum_bps_maker"], 5 * 98.0, places=3)
        self.assertEqual(g["wins"], 5)

    def test_min_n_group_filter(self):
        self._seed_up_seq("vBig", [0.01] * 5)
        self._seed_up_seq("vTiny", [0.01] * 4, start_days_ago=10)
        doc = metrics_mod.build_trades(self.root)
        models = {g["model_version"] for g in doc["groups"]}
        self.assertEqual(models, {"vBig"}, "groups need n >= 5")

    def test_last_trades_capped_at_30(self):
        self._seed_up_seq("vMany", [0.01] * 35)
        g = metrics_mod.build_trades(self.root)["groups"][0]
        self.assertEqual(g["n"], 35)
        self.assertEqual(len(g["last_trades"]), 30)
        self.assertEqual(len(g["curve"]), 35)


# ── N: recent.json shape ─────────────────────────────────────────────────────
class TestRecentJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shape_ordering_and_nulls(self):
        t0 = self.now - timedelta(days=3)
        _seed_pair(self.root, issued_at=_iso(t0),
                   target_time=_iso(t0 + timedelta(hours=24)),
                   model="vR", correct=True, ret=0.0123)
        _seed_pair(self.root, issued_at=_iso(t0 + timedelta(hours=1)),
                   target_time=_iso(t0 + timedelta(hours=25)),
                   model="vR", correct=False, ret=-0.004)
        # open forecast, newest
        _seed_pair(self.root, issued_at=_iso(self.now - timedelta(hours=1)),
                   target_time=_iso(self.now + timedelta(hours=23)),
                   model="vR", resolve_row=False)
        doc = metrics_mod.build_recent(self.root)
        self.assertEqual(doc["schema_version"], "recent-v0.1.0")
        self.assertIn("generated_at", doc)
        self.assertEqual(doc["total_issued"], 3)
        self.assertEqual(doc["total_resolved"], 2)
        rows = doc["rows"]
        self.assertEqual(len(rows), 3)
        # newest-first
        issued = [r["issued_at"] for r in rows]
        self.assertEqual(issued, sorted(issued, reverse=True))
        top = rows[0]
        for k in ("forecast_id", "issued_at", "model_version", "horizon",
                  "direction", "probability", "entry_price", "target_time",
                  "resolved", "actual_close", "actual_return_bps",
                  "direction_correct", "resolved_at"):
            self.assertIn(k, top)
        self.assertFalse(top["resolved"])
        self.assertIsNone(top["actual_close"])
        self.assertIsNone(top["actual_return_bps"])
        self.assertIsNone(top["direction_correct"])
        self.assertIsNone(top["resolved_at"])
        resolved_row = rows[2]
        self.assertTrue(resolved_row["resolved"])
        self.assertAlmostEqual(resolved_row["actual_return_bps"], 123.0)
        self.assertTrue(resolved_row["direction_correct"])

    def test_limit_50(self):
        t0 = self.now - timedelta(days=5)
        for i in range(55):
            _seed_pair(self.root,
                       issued_at=_iso(t0 + timedelta(minutes=i)),
                       target_time=_iso(t0 + timedelta(hours=24, minutes=i)),
                       model="vR", correct=True, ret=0.01)
        doc = metrics_mod.build_recent(self.root)
        self.assertEqual(doc["total_issued"], 55)
        self.assertEqual(len(doc["rows"]), 50)
        # the 5 oldest fell off
        oldest_kept = min(r["issued_at"] for r in doc["rows"])
        self.assertGreater(oldest_kept, _iso(t0 + timedelta(minutes=4)))


# ── O: signal gates — per-model bucket, pass and fail paths ──────────────────
class TestSignalGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_record(self, model, n, hits, days_back=10, horizon="24h"):
        """n resolved rows, `hits` correct, all issued inside `days_back`."""
        t0 = self.now - timedelta(days=days_back)
        step = (days_back * 24 - 30) / max(n, 1)  # keep targets in the past
        for i in range(n):
            correct = i < hits
            _seed_pair(self.root,
                       issued_at=_iso(t0 + timedelta(hours=i * step)),
                       target_time=_iso(t0 + timedelta(hours=i * step + 0.5)),
                       horizon=horizon, model=model,
                       correct=correct, ret=(0.01 if correct else -0.01))

    def _seed_open(self, model, horizon="24h"):
        _seed_pair(self.root, issued_at=_iso(self.now - timedelta(hours=1)),
                   target_time=_iso(self.now + timedelta(hours=23)),
                   horizon=horizon, model=model, resolve_row=False)

    def test_pass_path_actionable_paper(self):
        # 45 resolved, 32 hits (0.711): n>=40 ✓, wilson_lb≈0.566>0.50 ✓,
        # rolling-30d n=45>=20 hit 0.711>=0.52 maker>0 ✓, forecast alive ✓.
        self._seed_record("vGood", 45, 32)
        self._seed_open("vGood")
        doc = emit_mod.build_signal(self.root)
        self.assertEqual(doc["schema_version"], "signal-v0.2.0")
        self.assertEqual(doc["status"], "actionable_paper")
        g = doc["gates"]
        self.assertTrue(g["ok"])
        self.assertEqual(g["reasons"], [])
        self.assertEqual(g["model_version"], "vGood")
        self.assertEqual(g["n"], 45)
        self.assertGreater(g["wilson_lb_95"], 0.50)
        self.assertGreaterEqual(g["rolling_30d"]["n"], 20)
        self.assertGreater(g["rolling_30d"]["expectancy_maker_2bps"], 0)
        self.assertEqual(doc["signal"]["model_version"], "vGood")

    def test_policy24_like_failure_emits_shadow_with_reasons(self):
        # The live bug's shape: model's own 24h record n=21, hit 10/21≈0.476,
        # negative maker expectancy — while a pooled bucket could look great.
        # Gate must judge the model's own bucket → shadow.
        self._seed_record("vPolicy", 21, 10, days_back=20)
        # A pooled-flattering sibling model with a strong record — the gate
        # must NOT be fooled by it (this is the old failure mode).
        self._seed_record("vStrongSibling", 60, 40, days_back=25)
        self._seed_open("vPolicy")
        # vPolicy's open forecast is newest, but _pick_forecast tiers by
        # PREFERRED_MODELS membership; both are unlisted (tier 99) so the
        # earliest-issued model wins the tier. Make vPolicy the pick
        # explicitly by checking what was emitted, then assert its gates.
        doc = emit_mod.build_signal(self.root)
        self.assertEqual(doc["status"], "shadow")
        g = doc["gates"]
        self.assertFalse(g["ok"])
        emitted_model = doc["signal"]["model_version"]
        self.assertEqual(g["model_version"], emitted_model,
                         "gates must describe the EMITTING model's bucket")
        self.assertEqual(g["bucket"], f"{emitted_model}|24h")
        # The forecast is still published (honest state), just not actionable.
        self.assertIsNotNone(doc["signal"])
        reasons = " | ".join(g["reasons"])
        if emitted_model == "vPolicy":
            self.assertIn("n_resolved 21 < 40", reasons)
            self.assertIn("wilson_lb_95", reasons)
            self.assertIn("hit_rate", reasons)
            self.assertIn("not > 0", reasons)

    def test_policy24_bucket_directly(self):
        # Deterministic version of the above: gate the vPolicy bucket itself.
        self._seed_record("vPolicy", 21, 10, days_back=20)
        acc = metrics_mod.build(self.root)
        fake_forecast = {"model_version": "vPolicy", "horizon": "24h",
                         "target_time": _iso(self.now + timedelta(hours=5))}
        g = emit_mod._gates(acc, fake_forecast, now=self.now)
        self.assertFalse(g["ok"])
        reasons = " | ".join(g["reasons"])
        self.assertIn("n_resolved 21 < 40", reasons)
        self.assertIn("wilson_lb_95", reasons)          # 0.283 ≤ 0.50
        self.assertIn("rolling-30d hit_rate", reasons)  # 0.476 < 0.52
        self.assertIn("expectancy_maker_2bps", reasons)  # negative
        # rolling n=21 >= 20 → that gate alone passes; not in reasons.
        self.assertNotIn("rolling-30d n", reasons)

    def test_expired_forecast_is_shadow_even_with_good_record(self):
        # Metrics all pass, but the newest forecast's target is in the past.
        self._seed_record("vGood", 45, 32)
        doc = emit_mod.build_signal(self.root)
        self.assertEqual(doc["status"], "shadow")
        g = doc["gates"]
        self.assertEqual(len(g["reasons"]), 1)
        self.assertIn("expired", g["reasons"][0])

    def test_legacy_fields_still_present(self):
        # The site parses signal-v0.1.0 fields — v0.2.0 must keep them all.
        self._seed_record("vGood", 45, 32)
        self._seed_open("vGood")
        doc = emit_mod.build_signal(self.root)
        for k in ("schema_version", "generated_at", "status", "gates",
                  "not_financial_advice", "disclaimer", "economics", "signal"):
            self.assertIn(k, doc)
        g = doc["gates"]
        for k in ("ok", "n", "hit_rate", "expectancy_maker_2bps",
                  "vs_majority_pp", "rolling_30d_hit", "reason"):
            self.assertIn(k, g)
        for k in ("fee_assumption", "horizon_primary", "expectancy_maker_2bps",
                  "hit_rate", "vs_majority_pp", "n"):
            self.assertIn(k, doc["economics"])
        for k in ("signal_id", "forecast_id", "issued_at", "expires_at",
                  "asset", "horizon", "direction", "probability", "entry_ref",
                  "model_version"):
            self.assertIn(k, doc["signal"])

    def test_stale_accuracy_without_model_buckets_fails_closed(self):
        # An old (pre-v0.3.0) accuracy.json has no by_model_horizon — the
        # gate must fail closed (shadow), never crash or pass.
        self._seed_record("vGood", 45, 32)
        self._seed_open("vGood")
        acc = metrics_mod.build(self.root)
        acc.pop("by_model_horizon", None)
        acc["rolling"].pop("by_model_horizon", None)
        fake_forecast = {"model_version": "vGood", "horizon": "24h",
                         "target_time": _iso(self.now + timedelta(hours=5))}
        g = emit_mod._gates(acc, fake_forecast, now=self.now)
        self.assertFalse(g["ok"])
        self.assertIn("metrics-v0.3.0", " | ".join(g["reasons"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
