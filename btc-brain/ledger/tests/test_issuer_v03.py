"""
Tests for the v0.3 issuer upgrade (honest issuance + guard24) and the
venue-matched resolver.

Covers:
  A. No-backdating guard (backfill-skip) behavior
  B. issued_at_actual / entry_source / entry_symbol provenance fields
  C. guard24 direction/abstain matrix (rel bands, sma72 confirm, weekend)
  D. Overlapping 12h/24h hourly accrual + dedupe idempotence
  E. Resolver entry-venue source matching (mocked price sources)
  F. policy24 kill: absent from the default/dual CLI issuance path
  G. CLI dry-run end-to-end (guard24 issues; abstain path never crashes)

Run:
    cd btc-brain && python3 ledger/tests/test_issuer_v03.py
    (or from btc-brain/ledger: python tests/test_issuer_v03.py)
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import schedule_forecasts as sf  # noqa: E402
import resolve as resolve_mod  # noqa: E402
import price_source as ps  # noqa: E402
from ledger import Ledger, validate_forecast, parse_iso_utc  # noqa: E402

# Fixed reference dates (UTC): 2026-04-28 is a Tuesday, 2026-05-02 a Saturday,
# 2026-05-03 a Sunday.
TUE = datetime(2026, 4, 28, 12, 7, 0, tzinfo=timezone.utc)
SAT = datetime(2026, 5, 2, 12, 7, 0, tzinfo=timezone.utc)
SUN = datetime(2026, 5, 3, 12, 7, 0, tzinfo=timezone.utc)

MB15 = timedelta(minutes=15)


def _snapshot_doc(closes, now, source="coinbase"):
    """Snapshot dict shaped like data/public/candles_1h.json.

    Hourly candles whose newest close_time is the top of `now`'s hour.
    `source` mirrors the snapshot's top-level winning-provider key
    (None omits it, like pre-metadata fixtures).
    """
    last_close = now.replace(minute=0, second=0, microsecond=0)
    n = len(closes)
    candles = []
    for i, px in enumerate(closes):
        ct = last_close - timedelta(hours=(n - 1 - i))
        ot = ct - timedelta(hours=1)
        candles.append({
            "open": px, "high": px, "low": px, "close": px, "volume": 1.0,
            "open_time_ms": int(ot.timestamp() * 1000),
            "close_time_ms": int(ct.timestamp() * 1000),
        })
    doc = {"data": {"candles": candles}}
    if source is not None:
        doc["source"] = source
    return doc


def _write_snapshot(path: Path, closes, now, source="coinbase") -> Path:
    path.write_text(json.dumps(_snapshot_doc(closes, now, source=source)),
                    encoding="utf-8")
    return path


def _flat_with_last(last, n=75, base=100.0):
    """n-1 flat closes at `base`, then `last` — sma24 == sma72 == base."""
    return [base] * (n - 1) + [last]


def _candles_from_closes(closes, now):
    return _snapshot_doc(closes, now, source=None)["data"]["candles"]


class _TmpRootCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.snap = self.root / "candles_1h.json"

    def tearDown(self):
        self.tmp.cleanup()


# ── A: no-backdating guard ───────────────────────────────────────────────────
class TestBackfillGuard(_TmpRootCase):
    def test_run_late_in_bucket_skips_all_horizons(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)  # :30 > 15m
        _write_snapshot(self.snap, _flat_with_last(100.0), now)
        s = sf.run(self.root, self.snap, ["1h", "4h", "12h", "24h"],
                   now=now, max_backdate=MB15)
        self.assertEqual(s["issued"], [], s)
        self.assertEqual(len(s["skipped_filter"]), 4)
        for skip in s["skipped_filter"]:
            self.assertIn("backfill-guard", skip["reason"])
        self.assertEqual(list(Ledger.at(self.root).iter_forecasts()), [])

    def test_run_early_in_bucket_issues_all_horizons(self):
        # 12:07 — 7 min past every bucket start (12:00 opens 1h/4h/12h/24h).
        _write_snapshot(self.snap, _flat_with_last(100.0), TUE)
        s = sf.run(self.root, self.snap, ["1h", "4h", "12h", "24h"],
                   now=TUE, max_backdate=MB15)
        self.assertEqual(s["errors"], [], s)
        self.assertEqual(len(s["issued"]), 4)
        for r in s["issued"]:
            self.assertEqual(r["issued_at"], "2026-04-28T12:00:00Z")

    def test_mid_window_4h_bucket_is_skipped_not_backdated(self):
        # 13:07 — 1h bucket 13:00 is fresh; 4h bucket 12:00 is 67m old → skip.
        now = datetime(2026, 4, 28, 13, 7, 0, tzinfo=timezone.utc)
        _write_snapshot(self.snap, _flat_with_last(100.0), now)
        s = sf.run(self.root, self.snap, ["1h", "4h"],
                   now=now, max_backdate=MB15)
        by_h = {r["horizon"]: r for r in s["issued"]}
        self.assertIn("1h", by_h)
        self.assertNotIn("4h", by_h)
        skipped = [x for x in s["skipped_filter"] if x.get("horizon") == "4h"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("backfill-guard", skipped[0]["reason"])

    def test_guard_off_preserves_legacy_backfill_behavior(self):
        # max_backdate=None (library default) keeps pre-v0.3 semantics.
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        _write_snapshot(self.snap, _flat_with_last(100.0), now)
        s = sf.run(self.root, self.snap, ["1h"], now=now)
        self.assertEqual(len(s["issued"]), 1)

    def test_cli_default_is_15_minutes(self):
        self.assertEqual(sf.MAX_BACKDATE_DEFAULT, timedelta(minutes=15))


# ── B: provenance fields ─────────────────────────────────────────────────────
class TestProvenanceFields(_TmpRootCase):
    def test_issued_at_actual_and_entry_source_recorded(self):
        _write_snapshot(self.snap, _flat_with_last(100.0), TUE,
                        source="coinbase")
        s = sf.run(self.root, self.snap, ["1h", "24h"],
                   now=TUE, max_backdate=MB15)
        self.assertEqual(len(s["issued"]), 2)
        for r in s["issued"]:
            validate_forecast(r)  # additive fields must not break schema
            self.assertEqual(r["issued_at_actual"], "2026-04-28T12:07:00Z")
            self.assertEqual(r["issued_at"], "2026-04-28T12:00:00Z")
            self.assertEqual(r["entry_source"], "coinbase")
            self.assertEqual(r["entry_symbol"], "BTC-USD")

    def test_snapshot_without_source_yields_unknown_no_symbol(self):
        _write_snapshot(self.snap, _flat_with_last(100.0), TUE, source=None)
        s = sf.run(self.root, self.snap, ["1h"], now=TUE, max_backdate=MB15)
        r = s["issued"][0]
        self.assertEqual(r["entry_source"], "unknown")
        self.assertNotIn("entry_symbol", r)

    def test_binance_snapshot_symbol(self):
        _write_snapshot(self.snap, _flat_with_last(100.0), TUE,
                        source="binance")
        s = sf.run(self.root, self.snap, ["1h"], now=TUE, max_backdate=MB15)
        self.assertEqual(s["issued"][0]["entry_source"], "binance")
        self.assertEqual(s["issued"][0]["entry_symbol"], "BTCUSDT")


# ── C: guard24 signal matrix ─────────────────────────────────────────────────
class TestGuard24Signal(unittest.TestCase):
    def _sig(self, closes, now=TUE):
        return sf.guard24_direction_and_prob(
            _candles_from_closes(closes, now), now)

    def test_insufficient_history_abstains(self):
        d, p, reason = self._sig(_flat_with_last(100.0, n=50))
        self.assertEqual(d, "abstain")
        self.assertIsNone(p)
        self.assertIn("insufficient-history", reason)

    def test_rel_extreme_up_abstains(self):
        d, _, reason = self._sig(_flat_with_last(101.2))  # rel = +1.2%
        self.assertEqual(d, "abstain")
        self.assertIn("rel-extreme", reason)

    def test_rel_extreme_down_abstains(self):
        d, _, reason = self._sig(_flat_with_last(98.5))  # rel = -1.5%
        self.assertEqual(d, "abstain")
        self.assertIn("rel-extreme", reason)

    def test_up_high_conviction_band(self):
        d, p, reason = self._sig(_flat_with_last(100.3))  # rel = +0.3%
        self.assertEqual(d, "up")
        self.assertEqual(p, 0.55)
        self.assertIn("band=high", reason)
        self.assertTrue(reason.startswith("guard24:rel="), reason)
        self.assertIn("sma24=", reason)
        self.assertIn("sma72=", reason)

    def test_up_low_conviction_band(self):
        d, p, reason = self._sig(_flat_with_last(100.8))  # rel = +0.8%
        self.assertEqual(d, "up")
        self.assertEqual(p, 0.52)
        self.assertIn("band=low", reason)

    def test_rel_exactly_one_percent_issues_low_band(self):
        d, p, _ = self._sig(_flat_with_last(101.0))  # rel = +1.0%, not > 1%
        self.assertEqual(d, "up")
        self.assertEqual(p, 0.52)

    def test_down_confirmed_weekday(self):
        d, p, reason = self._sig(_flat_with_last(99.7))  # rel = -0.3%
        self.assertEqual(d, "down")  # last < sma24 AND last < sma72
        self.assertEqual(p, 0.55)
        self.assertIn("band=high", reason)

    def test_down_low_band(self):
        d, p, _ = self._sig(_flat_with_last(99.2))  # rel = -0.8%
        self.assertEqual(d, "down")
        self.assertEqual(p, 0.52)

    def test_down_without_sma72_confirmation_abstains(self):
        # Older 50 closes at 98, recent 24 at 101, last 100.2:
        # sma24 = 101 (last below it), sma72 = 99.0 (last ABOVE it) → abstain.
        closes = [98.0] * 50 + [101.0] * 24 + [100.2]
        d, p, reason = self._sig(closes)
        self.assertEqual(d, "abstain")
        self.assertIsNone(p)
        self.assertIn("no-sma72-confirm", reason)

    def test_weekend_down_abstains_saturday_and_sunday(self):
        for day in (SAT, SUN):
            d, _, reason = self._sig(_flat_with_last(99.7), now=day)
            self.assertEqual(d, "abstain", day)
            self.assertIn("weekend-down", reason)

    def test_weekend_up_still_issues(self):
        d, p, _ = self._sig(_flat_with_last(100.3), now=SAT)
        self.assertEqual(d, "up")
        self.assertEqual(p, 0.55)


# ── C2: guard24 through the dual issuer ──────────────────────────────────────
class TestGuard24Issuance(_TmpRootCase):
    def test_guard24_issues_12h_and_24h_rows(self):
        _write_snapshot(self.snap, _flat_with_last(100.3), TUE)
        s = sf.run_all(self.root, self.snap, ["1h"],
                       now=TUE, max_backdate=MB15)
        guard = s["models"]["guard24"]
        self.assertEqual(guard["errors"], [], guard)
        self.assertEqual(sorted(r["horizon"] for r in guard["issued"]),
                         ["12h", "24h"])
        for r in guard["issued"]:
            validate_forecast(r)
            self.assertEqual(r["model_version"], sf.GUARD_MODEL_VERSION)
            self.assertEqual(r["signal_version"], sf.GUARD_SIGNAL_VERSION)
            self.assertEqual(r["created_by"], sf.GUARD_CREATED_BY)
            self.assertEqual(r["direction"], "up")
            self.assertEqual(r["probability"], 0.55)
            self.assertTrue(r["confidence_reason"].startswith("guard24:"))
            self.assertEqual(r["entry_source"], "coinbase")
            self.assertEqual(r["issued_at"], "2026-04-28T12:00:00Z")

    def test_abstain_writes_no_row_but_is_logged(self):
        _write_snapshot(self.snap, _flat_with_last(101.2), TUE)  # rel-extreme
        s = sf.run_all(self.root, self.snap, ["1h"],
                       now=TUE, max_backdate=MB15)
        guard = s["models"]["guard24"]
        self.assertEqual(guard["issued"], [])
        self.assertEqual(len(guard["skipped_filter"]), 1)
        self.assertTrue(guard["skipped_filter"][0].get("abstain"))
        self.assertIn("rel-extreme", guard["skipped_filter"][0]["reason"])
        rows = list(Ledger.at(self.root).iter_forecasts())
        models = {r["model_version"] for r in rows}
        self.assertNotIn(sf.GUARD_MODEL_VERSION, models)

    def test_abstain_path_survives_dry_run(self):
        _write_snapshot(self.snap, _flat_with_last(98.0), TUE)  # rel-extreme
        s = sf.run_all(self.root, self.snap, ["1h", "24h"],
                       now=TUE, dry_run=True, max_backdate=MB15)
        self.assertEqual(len(s["models"]["guard24"]["skipped_filter"]), 1)
        self.assertEqual(list(Ledger.at(self.root).iter_forecasts()), [])

    def test_weekend_down_abstains_through_run_all(self):
        _write_snapshot(self.snap, _flat_with_last(99.7), SAT)
        s = sf.run_all(self.root, self.snap, ["1h"],
                       now=SAT, max_backdate=MB15)
        guard = s["models"]["guard24"]
        self.assertEqual(guard["issued"], [])
        self.assertIn("weekend-down", guard["skipped_filter"][0]["reason"])


# ── D: overlapping hourly accrual + dedupe idempotence ───────────────────────
class TestOverlappingAccrual(_TmpRootCase):
    def test_12h_24h_issue_every_hour_and_rerun_adds_zero_rows(self):
        _write_snapshot(self.snap, _flat_with_last(100.0), TUE)
        s1 = sf.run(self.root, self.snap, ["12h", "24h"],
                    now=TUE, max_backdate=MB15)
        self.assertEqual(len(s1["issued"]), 2)
        # Idempotent re-run in the same hour (any minute inside the guard).
        for minute in (7, 10, 14):
            again = sf.run(self.root, self.snap, ["12h", "24h"],
                           now=TUE.replace(minute=minute),
                           max_backdate=MB15)
            self.assertEqual(again["issued"], [], again)
            self.assertEqual(len(again["skipped_duplicate"]), 2)
        self.assertEqual(len(list(Ledger.at(self.root).iter_forecasts())), 2)
        # Next hour: both horizons accrue again (hourly bucket grid).
        nxt = TUE + timedelta(hours=1)
        _write_snapshot(self.snap, _flat_with_last(100.0), nxt)
        s2 = sf.run(self.root, self.snap, ["12h", "24h"],
                    now=nxt, max_backdate=MB15)
        self.assertEqual(len(s2["issued"]), 2)
        for r in s2["issued"]:
            self.assertEqual(r["issued_at"], "2026-04-28T13:00:00Z")
            issued = parse_iso_utc(r["issued_at"])
            target = parse_iso_utc(r["target_time"])
            self.assertEqual(target - issued,
                             sf.HORIZON_SPEC[r["horizon"]]["delta"])
        self.assertEqual(len(list(Ledger.at(self.root).iter_forecasts())), 4)

    def test_1h_and_4h_grids_unchanged(self):
        self.assertEqual(sf.HORIZON_SPEC["1h"]["bucket_hours"], 1)
        self.assertEqual(sf.HORIZON_SPEC["4h"]["bucket_hours"], 4)
        self.assertEqual(sf.HORIZON_SPEC["12h"]["bucket_hours"], 1)
        self.assertEqual(sf.HORIZON_SPEC["24h"]["bucket_hours"], 1)

    def test_guard24_dedupes_hourly_too(self):
        _write_snapshot(self.snap, _flat_with_last(100.3), TUE)
        sf.run_all(self.root, self.snap, ["1h"], now=TUE, max_backdate=MB15)
        s2 = sf.run_all(self.root, self.snap, ["1h"],
                        now=TUE.replace(minute=9), max_backdate=MB15)
        guard = s2["models"]["guard24"]
        self.assertEqual(guard["issued"], [])
        self.assertEqual(len(guard["skipped_duplicate"]), 2)


# ── E: venue-matched resolver ────────────────────────────────────────────────
def _forecast_row(fid, target_iso, issued_iso, direction="up",
                  entry=100.0, entry_source=None):
    row = {
        "forecast_id": fid,
        "issued_at": issued_iso,
        "asset": "BTCUSD",
        "horizon": "1h",
        "target_time": target_iso,
        "target_rule": ("close_above_entry" if direction == "up"
                        else "close_below_entry"),
        "direction": direction,
        "probability": 0.55,
        "entry_price": entry,
        "model_version": "v0.3.0-shadow-guard24",
        "signal_version": "shadow-guard24-v0.1.0",
        "regime_at_issue": "unknown",
        "feature_snapshot_uri": "test",
        "source_snapshot_uri": "test",
        "confidence_reason": "test",
        "invalidation": "none",
        "created_by": "test",
        "status": "open",
    }
    if entry_source is not None:
        row["entry_source"] = entry_source
    return row


def _range_map_for(target: datetime, close_price: float, source_tag: str):
    """Build a range_map fn serving exactly the candle closing at `target`."""
    candle = ps.Candle(
        open_time=target - timedelta(hours=1),
        close_time=target,
        close_price=close_price,
        source=source_tag,
    )
    def _fn(start_ms, end_ms):
        return {round(target.timestamp()): candle}
    return _fn


class TestVenueMatchedResolver(_TmpRootCase):
    def setUp(self):
        super().setUp()
        self.target = datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc)
        self.target_iso = "2026-04-28T13:00:00Z"
        self.issued_iso = "2026-04-28T12:00:00Z"
        self.now = self.target + timedelta(hours=1)
        self.base_fn = _range_map_for(self.target, 95.0, "binance:BTCUSDT:1h")
        self.cb_fn = _range_map_for(self.target, 105.0, "coinbase")

    def _resolve(self, venue_sources=None):
        return resolve_mod.run(
            self.root, now=self.now,
            sources=[("binance", self.base_fn)],
            venue_sources=venue_sources or {"coinbase": self.cb_fn},
        )

    def test_entry_source_coinbase_resolves_against_coinbase(self):
        led = Ledger.at(self.root)
        led.append_forecast(_forecast_row(
            "fc-cb", self.target_iso, self.issued_iso,
            entry_source="coinbase"))
        led.append_forecast(_forecast_row(
            "fc-legacy", self.target_iso, self.issued_iso))
        s = self._resolve()
        by_id = {r["forecast_id"]: r for r in s["resolved"]}
        self.assertEqual(by_id["fc-cb"]["actual_close"], 105.0)
        self.assertEqual(by_id["fc-cb"]["price_source"], "coinbase")
        self.assertEqual(by_id["fc-cb"]["resolution_source"], "coinbase")
        # Row without entry_source resolves exactly as today (base chain).
        self.assertEqual(by_id["fc-legacy"]["actual_close"], 95.0)
        self.assertEqual(by_id["fc-legacy"]["resolution_source"], "binance")

    def test_unknown_entry_source_uses_default_chain(self):
        Ledger.at(self.root).append_forecast(_forecast_row(
            "fc-unk", self.target_iso, self.issued_iso,
            entry_source="unknown"))
        s = self._resolve()
        self.assertEqual(s["resolved"][0]["actual_close"], 95.0)
        self.assertEqual(s["resolved"][0]["resolution_source"], "binance")

    def test_venue_failure_falls_back_to_existing_chain(self):
        Ledger.at(self.root).append_forecast(_forecast_row(
            "fc-cb2", self.target_iso, self.issued_iso,
            entry_source="coinbase"))
        def _broken(start_ms, end_ms):
            raise ps.PriceFetchError("coinbase down")
        s = self._resolve(venue_sources={"coinbase": _broken})
        self.assertEqual(len(s["resolved"]), 1)
        self.assertEqual(s["resolved"][0]["actual_close"], 95.0)
        self.assertEqual(s["resolved"][0]["resolution_source"], "binance")

    def test_entry_source_binance_prefers_existing_binance_source(self):
        Ledger.at(self.root).append_forecast(_forecast_row(
            "fc-bn", self.target_iso, self.issued_iso,
            entry_source="binance"))
        s = self._resolve()
        self.assertEqual(s["resolved"][0]["actual_close"], 95.0)
        self.assertEqual(s["resolved"][0]["resolution_source"], "binance")
        self.assertEqual(s["resolved"][0]["price_source"],
                         "binance:BTCUSDT:1h")

    def test_comparison_rule_unchanged_close_vs_entry(self):
        led = Ledger.at(self.root)
        led.append_forecast(_forecast_row(
            "fc-up", self.target_iso, self.issued_iso,
            direction="up", entry=100.0, entry_source="coinbase"))
        led.append_forecast(_forecast_row(
            "fc-dn", self.target_iso, self.issued_iso,
            direction="down", entry=100.0, entry_source="coinbase"))
        s = self._resolve()
        by_id = {r["forecast_id"]: r for r in s["resolved"]}
        # Coinbase close 105 > entry 100: up correct, down wrong.
        self.assertTrue(by_id["fc-up"]["direction_correct"])
        self.assertFalse(by_id["fc-dn"]["direction_correct"])
        self.assertAlmostEqual(by_id["fc-up"]["actual_return"], 0.05)


# ── F: policy24 kill ─────────────────────────────────────────────────────────
class TestPolicy24Killed(_TmpRootCase):
    def test_run_all_default_does_not_issue_policy24(self):
        _write_snapshot(self.snap, _flat_with_last(100.3), TUE)
        s = sf.run_all(self.root, self.snap, ["1h"],
                       now=TUE, max_backdate=MB15)
        self.assertNotIn("policy24", s["models"])
        models = {r["model_version"]
                  for r in Ledger.at(self.root).iter_forecasts()}
        self.assertNotIn(sf.POLICY_MODEL_VERSION, models)
        self.assertIn(sf.MODEL_VERSION, models)
        self.assertIn(sf.GUARD_MODEL_VERSION, models)

    def test_cli_has_no_policy24_switch(self):
        # The kill is unconditional on the CLI path: no flag re-enables it.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sf.main(["--root", str(self.root),
                         "--candles", str(self.snap),
                         "--no-policy24"])


# ── G: CLI dry-run end-to-end ────────────────────────────────────────────────
class TestCLIDryRun(_TmpRootCase):
    def _run_cli(self, extra):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sf.main([
                "--root", str(self.root),
                "--candles", str(self.snap),
                "--dry-run",
            ] + extra)
        return rc, json.loads(out.getvalue()), err.getvalue()

    def test_dry_run_issues_guard24_and_writes_nothing(self):
        now = datetime.now(timezone.utc)
        _write_snapshot(self.snap, _flat_with_last(100.0), now)
        # Guard disabled (<=0) so the assertion is wall-clock independent.
        rc, summary, _ = self._run_cli(["--max-backdate-minutes", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("guard24", summary["models"])
        guard = summary["models"]["guard24"]
        self.assertEqual(sorted(r["horizon"] for r in guard["issued"]),
                         ["12h", "24h"])
        for r in guard["issued"]:
            self.assertTrue(r.get("dry_run"))
            self.assertEqual(r["model_version"], sf.GUARD_MODEL_VERSION)
            self.assertIn("issued_at_actual", r)
            self.assertIn("entry_source", r)
        self.assertEqual(list(Ledger.at(self.root).iter_forecasts()), [])

    def test_dry_run_abstain_path_exits_zero_and_logs(self):
        now = datetime.now(timezone.utc)
        _write_snapshot(self.snap, _flat_with_last(101.5), now)  # rel-extreme
        rc, summary, err = self._run_cli(["--max-backdate-minutes", "0"])
        self.assertEqual(rc, 0)
        guard = summary["models"]["guard24"]
        self.assertEqual(guard["issued"], [])
        self.assertIn("rel-extreme", guard["skipped_filter"][0]["reason"])
        self.assertIn("rel-extreme", err)  # abstain visible in the run log


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMetricsDedupe(unittest.TestCase):
    """Multi-writer safety: metrics count one row per (model, horizon,
    issued_at) bucket, earliest issued_at_actual wins."""

    def test_duplicate_bucket_counted_once_earliest_wins(self):
        sys.path.insert(0, str(SCRIPTS))
        import metrics as metrics_mod

        def row(fid, actual, prob=0.52):
            return {
                "forecast": {
                    "forecast_id": fid,
                    "model_version": "v0.1.0-baseline-shadow",
                    "horizon": "24h",
                    "issued_at": "2026-08-11T06:00:00Z",
                    "issued_at_actual": actual,
                    "direction": "up",
                    "probability": prob,
                    "entry_price": 100.0,
                    "target_time": "2026-08-12T06:00:00Z",
                },
                "resolution": None,
            }

        joined = [
            row("fid-late", "2026-08-11T06:14:00Z"),
            row("fid-early", "2026-08-11T06:01:00Z"),
            {
                "forecast": {
                    "forecast_id": "fid-other-bucket",
                    "model_version": "v0.1.0-baseline-shadow",
                    "horizon": "24h",
                    "issued_at": "2026-08-11T07:00:00Z",
                    "issued_at_actual": "2026-08-11T07:01:00Z",
                    "direction": "up",
                    "probability": 0.52,
                    "entry_price": 100.0,
                    "target_time": "2026-08-12T07:00:00Z",
                },
                "resolution": None,
            },
        ]
        kept, dropped = metrics_mod.dedupe_joined(joined)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(kept), 2)
        kept_ids = {r["forecast"]["forecast_id"] for r in kept}
        self.assertIn("fid-early", kept_ids)   # earliest wall-clock wins
        self.assertNotIn("fid-late", kept_ids)
        self.assertIn("fid-other-bucket", kept_ids)

    def test_no_actual_field_keeps_first_file_occurrence(self):
        sys.path.insert(0, str(SCRIPTS))
        import metrics as metrics_mod
        base = {
            "model_version": "m", "horizon": "1h",
            "issued_at": "2026-08-11T06:00:00Z",
            "direction": "up", "probability": 0.5,
            "entry_price": 1.0, "target_time": "x",
        }
        joined = [
            {"forecast": dict(base, forecast_id="first"), "resolution": None},
            {"forecast": dict(base, forecast_id="second"), "resolution": None},
        ]
        kept, dropped = metrics_mod.dedupe_joined(joined)
        self.assertEqual(dropped, 1)
        self.assertEqual(kept[0]["forecast"]["forecast_id"], "first")
