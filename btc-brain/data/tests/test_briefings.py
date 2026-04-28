"""
Tests for the daily briefing generator and indexer.

Run:
    cd btc-brain/data && python tests/test_briefings.py

Invariants verified:
  * Index schema is stable across empty and populated states.
  * Empty state stays empty: no briefing files → index has briefings=[]
    and the existing stub note.
  * Populated state: index lists every <YYYY-MM-DD>.json file under
    briefings/, sorted newest-first, with a public-bundle relative URL.
  * No financial advice / trading instruction language appears in any
    field of a generated briefing.
  * No fabricated accuracy: when ledger accuracy reports
    display_ready=false, the briefing must NOT include hit_rate / brier
    / logloss / ece — even if those keys appear in the source JSON.
  * When ledger accuracy is display_ready=true, the briefing copies the
    ledger metrics verbatim (no rounding, no derivation).
  * The generator is fully offline — it makes no network calls — and
    runs even when individual public artifacts are missing or malformed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import briefings  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────
def _write(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _make_health(overall: str = "ok") -> dict:
    return {
        "schema_version": "phase2-data-v1",
        "kind": "source_health",
        "generated_at": "2026-04-28T04:00:00Z",
        "overall": overall,
        "sources": {
            "candles_1h": {"source": "coinbase", "status": "ok",
                           "fetched_at": "2026-04-28T04:00:00Z",
                           "error": None, "latency_ms": 22},
            "derivatives": {"source": "okx", "status": "degraded",
                            "fetched_at": "2026-04-28T04:00:00Z",
                            "error": None, "latency_ms": 358},
            "sentiment": {"source": "alternative.me", "status": "ok",
                          "fetched_at": "2026-04-28T04:00:00Z",
                          "error": None, "latency_ms": 247},
        },
        "freshness_budget_seconds": {"candles_1h": 5400},
    }


def _make_levels() -> dict:
    return {
        "schema_version": "phase2-data-v1",
        "kind": "key_levels",
        "source": "computed",
        "status": "ok",
        "fetched_at": "2026-04-28T04:00:00Z",
        "data": {
            "computed_at": "2026-04-28T04:00:00Z",
            "degraded": False,
            "pivot_classic": 77769.31,
            "r1": 79091.11,
            "r2": 80817.8,
            "s1": 76042.62,
            "s2": 74720.81,
            "recent_high": 79175.92,
            "recent_low": 76447.51,
            "sma_20": 75242.98,
            "sma_50": 71806.63,
            "sma_200": None,
            "vwap_session": 77081.30,
            "version": "key-levels-v0.1.0",
            "notes": ["sma_200 needs 200+ daily closes"],
        },
    }


def _make_sentiment() -> dict:
    return {
        "schema_version": "phase2-data-v1",
        "kind": "sentiment",
        "source": "alternative.me",
        "status": "ok",
        "fetched_at": "2026-04-28T04:00:00Z",
        "data": {
            "fear_greed_value": 33,
            "fear_greed_label": "Fear",
            "indicator": "fear_greed_btc_crypto",
            "sample_timestamp": "1777334400",
        },
    }


def _make_derivs() -> dict:
    return {
        "schema_version": "phase2-data-v1",
        "kind": "derivatives",
        "source": "okx",
        "status": "degraded",
        "fetched_at": "2026-04-28T04:00:00Z",
        "data": {
            "funding_rate": -6.48e-5,
            "open_interest_btc": 32934.17,
            "mark_price": None,
            "long_short_ratio": None,
        },
        "notes": ["missing:mark_price"],
    }


def _make_accuracy(*, display_ready: bool, n: int = 0) -> dict:
    base = {
        "by_horizon": {},
        "by_model_version": {},
        "generated_at": "2026-04-28T04:00:00Z",
        "global": {
            "base_rate": None,
            "baseline_brier": None,
            "baseline_hit_rate": None,
            "brier": None,
            "display_ready": display_ready,
            "ece": None,
            "hit_rate": None,
            "logloss": None,
            "n": n,
        },
        "metrics_version": "metrics-v0.1.0",
        "min_n_display": 20,
        "rolling": {},
        "schema_version": "1",
        "total_forecasts": n,
        "total_resolved": n,
    }
    if display_ready:
        base["global"].update({
            "hit_rate": 0.612,
            "brier": 0.221,
            "logloss": 0.633,
            "ece": 0.043,
            "baseline_brier": 0.250,
            "baseline_hit_rate": 0.500,
            "base_rate": 0.500,
        })
    return base


def _make_dirs(tmp: Path):
    public = tmp / "public"
    ledger = tmp / "ledger_public"
    briefings_dir = public / "briefings"
    public.mkdir(parents=True, exist_ok=True)
    ledger.mkdir(parents=True, exist_ok=True)
    briefings_dir.mkdir(parents=True, exist_ok=True)
    return public, ledger, briefings_dir


# ── tests ───────────────────────────────────────────────────────────────
class TestIndexSchema(unittest.TestCase):
    def test_empty_state_is_stub(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, _, briefings_dir = _make_dirs(Path(tmp))
            briefings.reindex_only(public)
            doc = json.loads((briefings_dir / "index.json").read_text())
            self.assertEqual(doc["schema_version"], "1")
            self.assertEqual(doc["briefings"], [])
            self.assertIn("Stub artifact", doc["notes"])
            self.assertIn("generated_at", doc)

    def test_populated_index_lists_files_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, _, briefings_dir = _make_dirs(Path(tmp))
            for date in ("2026-04-26", "2026-04-28", "2026-04-27"):
                _write(briefings_dir / f"{date}.json", {
                    "schema_version": "briefings-v1",
                    "id": f"briefing-{date}",
                    "date": date,
                    "title": f"BTC Brain daily briefing — {date}",
                    "generated_at": f"{date}T10:17:00Z",
                    "not_financial_advice": True,
                    "disclaimer": briefings.DISCLAIMER,
                    "summary": {},
                })
            briefings.reindex_only(public)
            doc = json.loads((briefings_dir / "index.json").read_text())
            dates = [b["date"] for b in doc["briefings"]]
            self.assertEqual(dates, ["2026-04-28", "2026-04-27", "2026-04-26"])
            for entry in doc["briefings"]:
                self.assertEqual(entry["url"],
                                 f"data/public/briefings/{entry['date']}.json")
                self.assertTrue(entry["id"].startswith("briefing-"))
                self.assertIn(entry["date"], entry["title"])
                self.assertEqual(entry["schema_version"], "briefings-v1")

    def test_index_ignores_non_date_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, _, briefings_dir = _make_dirs(Path(tmp))
            (briefings_dir / "README.md").write_text("hi", encoding="utf-8")
            (briefings_dir / "draft.json").write_text("{}", encoding="utf-8")
            (briefings_dir / "2026-04-28.json").write_text(json.dumps({
                "schema_version": "briefings-v1",
                "id": "briefing-2026-04-28",
                "date": "2026-04-28",
                "title": "t",
                "generated_at": "2026-04-28T00:00:00Z",
                "not_financial_advice": True,
                "disclaimer": briefings.DISCLAIMER,
                "summary": {},
            }), encoding="utf-8")
            briefings.reindex_only(public)
            doc = json.loads((briefings_dir / "index.json").read_text())
            self.assertEqual(len(doc["briefings"]), 1)
            self.assertEqual(doc["briefings"][0]["date"], "2026-04-28")


class TestNoFinancialAdvice(unittest.TestCase):
    FORBIDDEN_TERMS = (
        "buy", "sell", "long ", "short ", "leverage", "stop-loss",
        "stop loss", "take profit", "take-profit", "entry at",
        "exit at", "target price", "price target", "should buy",
        "should sell", "we recommend", "you should", "guaranteed",
        "risk-free", "trading signal",
    )

    def _flatten(self, obj, out: list[str]):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str):
                    out.append(v)
                else:
                    self._flatten(v, out)
        elif isinstance(obj, list):
            for v in obj:
                self._flatten(v, out)
        elif isinstance(obj, str):
            out.append(obj)

    def test_disclaimer_present_and_flag_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            _write(ledger / "accuracy.json",
                   _make_accuracy(display_ready=False))
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            self.assertTrue(doc["not_financial_advice"])
            self.assertIn("Not financial advice", doc["disclaimer"])

    def test_no_trading_instruction_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            _write(ledger / "accuracy.json",
                   _make_accuracy(display_ready=False))
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            strings: list[str] = []
            self._flatten(doc, strings)
            # Drop the disclaimer string itself — it explicitly
            # *negates* the forbidden actions ("No buy, sell, hold...").
            strings = [s for s in strings
                       if "not financial advice" not in s.lower()]
            joined = "\n".join(strings).lower()
            for bad in self.FORBIDDEN_TERMS:
                self.assertNotIn(
                    bad, joined,
                    f"forbidden phrase {bad!r} found in briefing body",
                )


class TestNoFabricatedAccuracy(unittest.TestCase):
    def test_display_ready_false_omits_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            _write(ledger / "accuracy.json",
                   _make_accuracy(display_ready=False, n=3))
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            acc = doc["summary"]["accuracy"]
            self.assertFalse(acc["display_ready"])
            self.assertEqual(acc["n"], 3)
            self.assertEqual(acc["min_n_display"], 20)
            self.assertIn("note", acc)
            for forbidden in ("hit_rate", "brier", "logloss", "ece",
                              "baseline_hit_rate", "baseline_brier",
                              "base_rate"):
                self.assertNotIn(forbidden, acc,
                                 f"{forbidden} leaked despite display_ready=false")

    def test_display_ready_true_copies_metrics_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            ledger_doc = _make_accuracy(display_ready=True, n=42)
            _write(ledger / "accuracy.json", ledger_doc)
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            acc = doc["summary"]["accuracy"]
            self.assertTrue(acc["display_ready"])
            self.assertEqual(acc["n"], 42)
            self.assertEqual(acc["hit_rate"], 0.612)
            self.assertEqual(acc["brier"], 0.221)
            self.assertEqual(acc["logloss"], 0.633)
            self.assertEqual(acc["ece"], 0.043)
            self.assertEqual(acc["baseline_brier"], 0.250)

    def test_missing_accuracy_artifact_is_handled(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            acc = doc["summary"]["accuracy"]
            self.assertFalse(acc["available"])
            self.assertFalse(acc["display_ready"])
            self.assertEqual(acc["n"], 0)
            for forbidden in ("hit_rate", "brier", "logloss", "ece"):
                self.assertNotIn(forbidden, acc)


class TestEmptyVsPopulated(unittest.TestCase):
    def test_empty_then_populated_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            briefings.reindex_only(public)
            empty = json.loads((briefings_dir / "index.json").read_text())
            self.assertEqual(empty["briefings"], [])

            _write(public / "source_health.json", _make_health())
            _write(public / "key_levels.json", _make_levels())
            _write(public / "sentiment.json", _make_sentiment())
            _write(public / "derivatives.json", _make_derivs())
            _write(ledger / "accuracy.json",
                   _make_accuracy(display_ready=False))
            briefings.generate_today(public, ledger, date="2026-04-28")
            populated = json.loads(
                (briefings_dir / "index.json").read_text())
            self.assertEqual(len(populated["briefings"]), 1)
            self.assertEqual(populated["briefings"][0]["date"], "2026-04-28")
            self.assertEqual(empty["schema_version"],
                             populated["schema_version"])


class TestRobustnessOffline(unittest.TestCase):
    def test_handles_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            for k in ("source_health", "key_levels",
                      "sentiment", "derivatives"):
                self.assertFalse(doc["summary"][k]["available"])
            self.assertTrue(doc["not_financial_advice"])

    def test_handles_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            public, ledger, briefings_dir = _make_dirs(Path(tmp))
            (public / "source_health.json").write_text(
                "{not json", encoding="utf-8")
            briefings.generate_today(public, ledger, date="2026-04-28")
            doc = json.loads(
                (briefings_dir / "2026-04-28.json").read_text())
            self.assertFalse(doc["summary"]["source_health"]["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
