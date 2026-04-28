"""
Tests for the scheduled forecast issuer.

Run:
    cd btc-brain/ledger && python tests/test_schedule_forecasts.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import schedule_forecasts as sf  # noqa: E402
from ledger import Ledger, validate_forecast, parse_iso_utc  # noqa: E402


def _make_candles(now: datetime, n: int = 30, base: float = 70000.0,
                  step: float = 50.0):
    """Build n hourly closed candles whose last close_time is just before `now`.

    Returns a dict mirroring the shape of btc-brain/data/public/candles_1h.json.
    """
    # Latest closed candle's close_time = top of the current hour.
    last_close = now.replace(minute=0, second=0, microsecond=0)
    candles = []
    for i in range(n, 0, -1):
        ot = last_close - timedelta(hours=i)
        ct = ot + timedelta(hours=1)
        close = base + (n - i) * step
        candles.append({
            "open": close - step / 2,
            "high": close + step,
            "low": close - step,
            "close": close,
            "volume": 100.0,
            "open_time_ms": int(ot.timestamp() * 1000),
            "close_time_ms": int(ct.timestamp() * 1000),
        })
    return {"data": {"candles": candles}}


def _write_candles(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ── A: schema validity of issued rows ────────────────────────────────────────
class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        self.candles_path = _write_candles(
            self.root / "candles_1h.json", _make_candles(self.now)
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_issued_row_passes_schema_validation(self):
        summary = sf.run(
            ledger_root=self.root,
            candles_path=self.candles_path,
            horizons=["1h", "4h", "12h", "24h"],
            now=self.now,
        )
        self.assertEqual(summary["errors"], [], summary)
        self.assertEqual(len(summary["issued"]), 4)
        for row in summary["issued"]:
            # Should not blow up.
            validate_forecast(row)
            # Shadow labelling.
            self.assertIn("shadow", row["model_version"])
            self.assertIn("shadow", row["signal_version"])
            self.assertEqual(row["asset"], "BTCUSD")
            self.assertEqual(row["status"], "open")
            self.assertEqual(row["created_by"], sf.CREATED_BY)


# ── B: append-only behavior — ledger file grows by exactly N lines ───────────
class TestAppendOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        self.candles_path = _write_candles(
            self.root / "candles_1h.json", _make_candles(self.now)
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_issuer_appends_exactly_one_row_per_horizon(self):
        sf.run(
            ledger_root=self.root, candles_path=self.candles_path,
            horizons=["1h", "4h", "12h", "24h"], now=self.now,
        )
        rows = list(Ledger.at(self.root).iter_forecasts())
        self.assertEqual(len(rows), 4)

    def test_issuer_does_not_rewrite_existing_lines(self):
        # First run.
        sf.run(
            ledger_root=self.root, candles_path=self.candles_path,
            horizons=["1h"], now=self.now,
        )
        path = self.root / "forecasts.jsonl"
        first = path.read_bytes()
        # Same hour, different horizon — the 1h bucket is occupied so 1h is
        # skipped, but 4h is fresh and gets appended.
        sf.run(
            ledger_root=self.root, candles_path=self.candles_path,
            horizons=["1h", "4h"], now=self.now,
        )
        after = path.read_bytes()
        self.assertTrue(after.startswith(first),
                        "append-only file must not rewrite earlier bytes")
        rows = list(Ledger.at(self.root).iter_forecasts())
        self.assertEqual(len(rows), 2)


# ── C: duplicate prevention by (model_version, horizon, issued_bucket) ───────
class TestDuplicatePrevention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candles_path = self.root / "candles_1h.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rerun_in_same_hour_is_noop_for_1h(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        _write_candles(self.candles_path, _make_candles(now))
        s1 = sf.run(self.root, self.candles_path, ["1h"], now=now)
        self.assertEqual(len(s1["issued"]), 1)
        # Same bucket, slightly later: should skip duplicate.
        s2 = sf.run(self.root, self.candles_path, ["1h"],
                    now=now + timedelta(minutes=20))
        self.assertEqual(s2["issued"], [])
        self.assertEqual(len(s2["skipped_duplicate"]), 1)

    def test_next_hour_issues_new_1h_forecast(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        _write_candles(self.candles_path, _make_candles(now))
        sf.run(self.root, self.candles_path, ["1h"], now=now)
        # Move to next hour and refresh candles.
        later = now + timedelta(hours=1)
        _write_candles(self.candles_path, _make_candles(later))
        s2 = sf.run(self.root, self.candles_path, ["1h"], now=later)
        self.assertEqual(len(s2["issued"]), 1, s2)

    def test_4h_bucket_is_4h_wide(self):
        # Two runs separated by 1 hour both fall in the same 4h bucket → no dup.
        t0 = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
        _write_candles(self.candles_path, _make_candles(t0))
        sf.run(self.root, self.candles_path, ["4h"], now=t0)
        _write_candles(self.candles_path, _make_candles(t0 + timedelta(hours=1)))
        s2 = sf.run(self.root, self.candles_path, ["4h"],
                    now=t0 + timedelta(hours=1))
        self.assertEqual(s2["issued"], [])
        self.assertEqual(len(s2["skipped_duplicate"]), 1)
        # 4h later, new 4h bucket — issues again.
        _write_candles(self.candles_path, _make_candles(t0 + timedelta(hours=4)))
        s3 = sf.run(self.root, self.candles_path, ["4h"],
                    now=t0 + timedelta(hours=4))
        self.assertEqual(len(s3["issued"]), 1, s3)


# ── D: horizon target_time math ──────────────────────────────────────────────
class TestHorizonTargets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        self.candles_path = _write_candles(
            self.root / "candles_1h.json", _make_candles(self.now)
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_target_time_is_issued_plus_horizon(self):
        summary = sf.run(self.root, self.candles_path,
                         ["1h", "4h", "12h", "24h"], now=self.now)
        by_h = {r["horizon"]: r for r in summary["issued"]}
        for h, expected_delta in [
            ("1h", timedelta(hours=1)),
            ("4h", timedelta(hours=4)),
            ("12h", timedelta(hours=12)),
            ("24h", timedelta(hours=24)),
        ]:
            r = by_h[h]
            issued = parse_iso_utc(r["issued_at"])
            target = parse_iso_utc(r["target_time"])
            self.assertEqual(target - issued, expected_delta,
                             f"horizon {h} target/issued mismatch")
            # target strictly after issued.
            self.assertGreater(target, issued)

    def test_issued_at_is_floored_to_bucket(self):
        # Bucket for 4h at 12:30 UTC is 12:00 UTC.
        summary = sf.run(self.root, self.candles_path, ["4h"], now=self.now)
        r = summary["issued"][0]
        issued = parse_iso_utc(r["issued_at"])
        self.assertEqual(issued.minute, 0)
        self.assertEqual(issued.second, 0)
        self.assertEqual(issued.hour, 12)


# ── E: conservative probability bounds ───────────────────────────────────────
class TestProbabilityBounds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candles_path = self.root / "candles_1h.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_probability_within_conservative_band(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        # Try across a wide range of price trajectories — flat, up, down,
        # extreme up. In every case the published probability must stay
        # in (PROB_FLOOR, PROB_CEIL].
        scenarios = [
            ("flat",     {"base": 70000.0, "step": 0.0}),
            ("uptrend",  {"base": 70000.0, "step": 100.0}),
            ("downtrnd", {"base": 80000.0, "step": -100.0}),
            ("spike",    {"base": 70000.0, "step": 5000.0}),
        ]
        for name, kw in scenarios:
            _write_candles(self.candles_path, _make_candles(now, **kw))
            # Fresh ledger root each scenario.
            tmp = tempfile.TemporaryDirectory()
            try:
                root = Path(tmp.name)
                summary = sf.run(root, self.candles_path,
                                 ["1h", "4h", "12h", "24h"], now=now)
                self.assertEqual(summary["errors"], [], (name, summary))
                for r in summary["issued"]:
                    p = r["probability"]
                    self.assertGreater(p, 0.5, (name, p))
                    self.assertLessEqual(p, sf.PROB_CEIL, (name, p))
                    self.assertGreaterEqual(p, sf.PROB_FLOOR, (name, p))
            finally:
                tmp.cleanup()

    def test_probability_strictly_in_open_unit_interval(self):
        # Defensive: schema requires p in (0, 1) exclusive. PROB_FLOOR > 0
        # and PROB_CEIL < 1, so we should always be valid.
        self.assertGreater(sf.PROB_FLOOR, 0.0)
        self.assertLess(sf.PROB_CEIL, 1.0)

    def test_no_strong_confidence_published(self):
        # Hard ceiling: no row should ever publish probability > 0.55.
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        _write_candles(self.candles_path,
                       _make_candles(now, base=70000.0, step=10000.0))
        summary = sf.run(self.root, self.candles_path,
                         ["1h", "4h", "12h", "24h"], now=now)
        for r in summary["issued"]:
            self.assertLessEqual(r["probability"], 0.55,
                                 "shadow model must not publish strong claims")


# ── F: incomplete candle and stale snapshot guards ───────────────────────────
class TestSafetyGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candles_path = self.root / "candles_1h.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_snapshot_errors_no_issuance(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        s = sf.run(self.root, self.candles_path, ["1h"], now=now)
        self.assertEqual(s["issued"], [])
        self.assertTrue(s["errors"])

    def test_stale_snapshot_errors_no_issuance(self):
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        # Build candles whose newest closed candle is 1 day old.
        old = now - timedelta(days=1)
        _write_candles(self.candles_path, _make_candles(old))
        s = sf.run(self.root, self.candles_path, ["1h"], now=now)
        self.assertEqual(s["issued"], [])
        self.assertTrue(s["errors"])
        self.assertIn("stale", s["errors"][0]["reason"].lower())

    def test_in_progress_candle_is_ignored(self):
        # Add an in-progress candle whose close_time is in the future. The
        # issuer must still pick the previous closed candle, not the open one.
        now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        doc = _make_candles(now)
        # Append an open candle starting at top-of-hour 12:00, closing 13:00.
        ot = now.replace(minute=0, second=0, microsecond=0)
        ct = ot + timedelta(hours=1)
        in_progress_close = 99999.99
        doc["data"]["candles"].append({
            "open": 71000.0, "high": 72000.0, "low": 70000.0,
            "close": in_progress_close, "volume": 1.0,
            "open_time_ms": int(ot.timestamp() * 1000),
            "close_time_ms": int(ct.timestamp() * 1000),
        })
        _write_candles(self.candles_path, doc)
        s = sf.run(self.root, self.candles_path, ["1h"], now=now)
        self.assertEqual(s["errors"], [], s)
        self.assertEqual(len(s["issued"]), 1)
        self.assertNotEqual(s["issued"][0]["entry_price"], in_progress_close,
                            "must not use in-progress candle close")


# ── G: no public accuracy claim leaks via accuracy.json ──────────────────────
class TestNoPublicAccuracyClaims(unittest.TestCase):
    """Issuance alone must not move accuracy.json into a 'display_ready' state.

    With 0 resolutions, total_resolved is 0 and global.display_ready is False.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candles_path = _write_candles(
            self.root / "candles_1h.json",
            _make_candles(datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_metrics_stays_not_display_ready_after_issuance(self):
        # Import here to avoid loading at module import time.
        sys.path.insert(0, str(HERE.parent / "scripts"))
        import metrics as metrics_mod  # noqa: E402

        now = datetime(2026, 4, 28, 12, 30, tzinfo=timezone.utc)
        sf.run(self.root, self.candles_path,
               ["1h", "4h", "12h", "24h"], now=now)
        m = metrics_mod.build(self.root)
        self.assertEqual(m["total_resolved"], 0)
        self.assertFalse(m["global"]["display_ready"])
        # Per-bucket buckets created from issuance alone are empty (only
        # resolved rows make it into by_horizon), so display_ready cannot
        # flip to True from issuance alone.
        self.assertEqual(m["by_horizon"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
