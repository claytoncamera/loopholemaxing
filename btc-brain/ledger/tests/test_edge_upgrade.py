"""Tests for dual issuer, edge hunter, and signal emitter."""
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
import edge_hunter as eh  # noqa: E402
import emit_signal as es  # noqa: E402
from ledger import Ledger  # noqa: E402


def _make_candles(now: datetime, n: int = 40, base: float = 70000.0, step: float = 50.0):
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


class TestDualIssuer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Use hour 12 so policy24 is not hour-filtered
        self.now = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
        self.candles = self.root / "candles.json"
        self.candles.write_text(json.dumps(_make_candles(self.now)), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dual_issues_baseline_and_policy24(self):
        summary = sf.run_all(
            self.root, self.candles, ["1h", "4h", "12h", "24h"],
            now=self.now, enable_policy24=True,
        )
        rows = list(Ledger.at(self.root).iter_forecasts())
        models = {r["model_version"] for r in rows}
        self.assertIn(sf.MODEL_VERSION, models)
        self.assertIn(sf.POLICY_MODEL_VERSION, models)
        # baseline: 4 horizons; policy: 12h+24h
        self.assertEqual(len(rows), 6)
        pol = [r for r in rows if r["model_version"] == sf.POLICY_MODEL_VERSION]
        self.assertEqual(sorted(r["horizon"] for r in pol), ["12h", "24h"])
        # regime should be set (bull on rising series after warmup)
        for r in rows:
            self.assertIn(r["regime_at_issue"], ("bull", "bear", "chop", "unknown"))

    def test_policy_skips_hour_20(self):
        now = datetime(2026, 4, 28, 20, 30, 0, tzinfo=timezone.utc)
        self.candles.write_text(json.dumps(_make_candles(now)), encoding="utf-8")
        summary = sf.run_all(
            self.root, self.candles, ["24h"], now=now, enable_policy24=True,
        )
        pol = summary["models"]["policy24"]
        self.assertEqual(pol["issued"], [])
        self.assertTrue(pol["skipped_filter"])

    def test_baseline_api_unchanged(self):
        s = sf.run(self.root, self.candles, ["1h"], now=self.now)
        self.assertEqual(len(s["issued"]), 1)
        self.assertEqual(s["issued"][0]["model_version"], sf.MODEL_VERSION)
        self.assertEqual(s["issued"][0]["created_by"], sf.CREATED_BY)


class TestPolicyConfidenceInvert(unittest.TestCase):
    def test_mild_rel_higher_prob_than_extreme(self):
        now = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
        # mild: small steps
        mild = _make_candles(now, n=40, step=5.0)["data"]["candles"]
        # extreme: huge last jump
        ext = _make_candles(now, n=40, step=5.0)["data"]["candles"]
        ext[-1]["close"] = ext[-2]["close"] * 1.05  # 5% jump
        d1, p_mild, _ = sf.policy24_direction_and_prob(mild)
        d2, p_ext, _ = sf.policy24_direction_and_prob(ext)
        self.assertGreater(p_mild, p_ext)


class TestEdgeHunterAndSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_edge_hunter_runs_empty(self):
        report = eh.hunt(self.root)
        self.assertEqual(report["edge_hunter_version"], eh.EDGE_HUNTER_VERSION)
        self.assertIn("next_experiments", report)

    def test_emit_signal_halted_without_forecasts(self):
        doc = es.build_signal(self.root)
        self.assertEqual(doc["status"], "halted")
        self.assertTrue(doc["not_financial_advice"])


if __name__ == "__main__":
    unittest.main()
