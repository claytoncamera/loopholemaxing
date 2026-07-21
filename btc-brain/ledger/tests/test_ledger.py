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


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
        self.assertEqual(m["metrics_version"], "metrics-v0.2.0")
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
