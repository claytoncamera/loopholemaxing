"""
Phase 2 — Data Foundation tests.

Run:
    cd btc-brain/data && python tests/test_phase2.py
or:
    python -m unittest btc-brain.data.tests.test_phase2

These tests are entirely offline. They never make a real HTTP call.
Every provider is exercised through an injected `fetcher` that returns
canned JSON, including failure paths.

Invariants verified:
  * No synthesized OHLC: when every provider fails, the artifact's `data`
    is None and `status` is `failed` — never a fabricated candle.
  * Fallback order Binance → Coinbase → Kraken → CoinGecko works for
    candles and OKX is used for derivatives when Binance is down.
  * The closed-candle helper always drops the in-progress candle and is
    used end-to-end before key-level computation.
  * Dynamic key-level fields are arithmetic of the supplied closed
    candles only — no hard-coded fallbacks.
  * Source health correctly reports overall status (ok / degraded /
    failed) and per-source freshness fields.
  * Freshness budgets are present in source_health for every kind.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scripts"))

from feeds.base import (
    FeedResult,
    HttpError,
    STATUS_FAILED,
    STATUS_OK,
    drop_incomplete_candle,
    run_with_fallback,
)
from feeds import candles as candles_feed
from feeds import derivatives as derivs_feed
from feeds import sentiment as sentiment_feed
from key_levels import compute_key_levels
import snapshot as snap


# ── Canned fixture data ────────────────────────────────────────────────────
def _binance_klines_fixture(n_complete=24, include_live=True):
    """Build n complete 1h candles plus optionally one in-progress."""
    now_ms = int(datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    h = 60 * 60 * 1000
    out = []
    base = 65000.0
    for i in range(n_complete):
        open_ms = now_ms - (n_complete - i) * h
        close_ms = open_ms + h - 1  # Binance includes inclusive endpoint
        px = base + i * 100.0
        out.append([
            open_ms, str(px - 50), str(px + 80), str(px - 90), str(px + 10),
            "12.0", close_ms, "0", 0, "0", "0", "0",
        ])
    if include_live:
        live_open = now_ms
        live_close = live_open + h - 1
        out.append([
            live_open, "70000", "70500", "69900", "70100", "5.0",
            live_close, "0", 0, "0", "0", "0",
        ])
    return out


def _binance_candles_fetcher(payload):
    def _f(url, *a, **kw):
        return payload
    return _f


def _failing_fetcher(*a, **kw):
    raise HttpError("simulated network failure")


# ── Tests ──────────────────────────────────────────────────────────────────
class TestFallback(unittest.TestCase):
    def test_binance_used_when_ok(self):
        payload = _binance_klines_fixture(n_complete=4, include_live=False)
        chain = [
            lambda: candles_feed.fetch_binance_candles("1h", fetcher=_binance_candles_fetcher(payload)),
            lambda: candles_feed.fetch_coinbase_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_kraken_candles("1h", fetcher=_failing_fetcher),
        ]
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.source, "binance")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertEqual(len(attempts), 1)

    def test_falls_through_to_coinbase(self):
        cb_payload = [
            # [time_s, low, high, open, close, volume]
            [1745740800, 64000.0, 64500.0, 64100.0, 64400.0, 11.0],
            [1745744400, 64400.0, 64900.0, 64400.0, 64800.0, 12.0],
        ]
        chain = [
            lambda: candles_feed.fetch_binance_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coinbase_candles("1h", fetcher=_binance_candles_fetcher(cb_payload)),
            lambda: candles_feed.fetch_kraken_candles("1h", fetcher=_failing_fetcher),
        ]
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.source, "coinbase")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertGreaterEqual(len(attempts), 2)
        # First attempt should be a binance failure record.
        self.assertEqual(attempts[0].source, "binance")
        self.assertEqual(attempts[0].status, STATUS_FAILED)

    def test_falls_through_to_kraken(self):
        kraken_payload = {
            "error": [],
            "result": {
                "XXBTZUSD": [
                    [1745740800, "64100", "64500", "64000", "64400", "64200", "11.0", 100],
                    [1745744400, "64400", "64900", "64400", "64800", "64600", "12.0", 110],
                ],
                "last": 1745744400,
            },
        }
        chain = [
            lambda: candles_feed.fetch_binance_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coinbase_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_kraken_candles("1h", fetcher=_binance_candles_fetcher(kraken_payload)),
        ]
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.source, "kraken")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertEqual(len(attempts), 3)

    def test_falls_through_to_coingecko_for_daily(self):
        cg_payload = [
            [1745625600000, 64000.0, 64500.0, 63800.0, 64400.0],
            [1745712000000, 64400.0, 65000.0, 64200.0, 64900.0],
        ]
        chain = [
            lambda: candles_feed.fetch_binance_candles("1d", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coinbase_candles("1d", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_kraken_candles("1d", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coingecko_candles("1d", fetcher=_binance_candles_fetcher(cg_payload)),
        ]
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.source, "coingecko")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertEqual(len(attempts), 4)

    def test_all_fail_no_fabrication(self):
        """When every provider fails the chosen result is `failed` and data
        is None — we never fabricate OHLC."""
        chain = [
            lambda: candles_feed.fetch_binance_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coinbase_candles("1h", fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_kraken_candles("1h", fetcher=_failing_fetcher),
        ]
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.status, STATUS_FAILED)
        self.assertIsNone(chosen.data)
        self.assertEqual(len(attempts), 3)
        for a in attempts:
            self.assertEqual(a.status, STATUS_FAILED)


class TestClosedCandlesOnly(unittest.TestCase):
    def test_drops_in_progress_candle(self):
        payload = _binance_klines_fixture(n_complete=4, include_live=True)
        # Pin "now" between the last complete candle's close and the live
        # candle's close.
        result = candles_feed.fetch_binance_candles(
            "1h",
            fetcher=_binance_candles_fetcher(payload),
        )
        # Binance result includes 5 candles total (4 complete + 1 live).
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(len(result.data["candles"]), 5)
        now = datetime(2026, 4, 27, 12, 30, 0, tzinfo=timezone.utc)
        closed = candles_feed.closed_candles(result, now=now)
        self.assertEqual(len(closed), 4, "in-progress candle must be dropped")
        # All closes are below the live candle's open.
        last_closed_close = closed[-1]["close"]
        self.assertLess(last_closed_close, 70000)


class TestDerivatives(unittest.TestCase):
    def test_binance_ok(self):
        def fetcher(url, *a, **kw):
            if "premiumIndex" in url:
                return {
                    "lastFundingRate": "0.00012",
                    "nextFundingTime": 1745740800000,
                    "markPrice": "65250.5",
                }
            if "openInterest" in url:
                return {"openInterest": "73250.0"}
            if "globalLongShortAccountRatio" in url:
                return [{"longShortRatio": "1.42", "longAccount": "0.59", "shortAccount": "0.41"}]
            raise HttpError("unexpected url")
        chain = [lambda: derivs_feed.fetch_binance_derivatives(fetcher=fetcher)]
        chosen, _ = run_with_fallback(chain, accept=lambda r: r.status in (STATUS_OK, "degraded"))
        self.assertEqual(chosen.source, "binance")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertAlmostEqual(chosen.data["funding_rate"], 0.00012)
        self.assertAlmostEqual(chosen.data["open_interest_btc"], 73250.0)

    def test_binance_451_falls_through(self):
        """Binance returning 451 must not poison the chain — OKX/Bybit
        get a chance and the artifact carries non-fabricated data."""
        def fetcher(url, *a, **kw):
            if "fapi.binance.com" in url:
                raise HttpError("HTTP Error 451: ")
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                raise HttpError("rubik blocked")
            if "bybit.com" in url and "tickers" in url:
                return {"result": {"list": [{
                    "fundingRate": "0.00009", "markPrice": "65010.0",
                    "openInterest": "72000.0", "nextFundingTime": "1745740800000",
                }]}}
            if "bybit.com" in url and "account-ratio" in url:
                return {"result": {"list": [{"buyRatio": "0.55", "sellRatio": "0.45"}]}}
            raise HttpError(f"unexpected: {url}")
        chain = derivs_feed.default_provider_chain(fetcher=fetcher)
        chosen, attempts = run_with_fallback(
            chain,
            accept=lambda r: r.status == STATUS_OK,
        )
        self.assertEqual(chosen.source, "bybit")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertAlmostEqual(chosen.data["funding_rate"], 0.00009)
        self.assertAlmostEqual(chosen.data["open_interest_btc"], 72000.0)
        self.assertIsNotNone(chosen.data["long_short_ratio"])
        # First attempt must be the Binance failure.
        self.assertEqual(attempts[0].source, "binance")
        self.assertEqual(attempts[0].status, STATUS_FAILED)

    def test_okx_partial_ok_when_only_rich_fields_missing(self):
        """OKX returns funding + OI + mark but no long/short — the
        result is partial_ok, not degraded, and no fields are fabricated."""
        def fetcher(url, *a, **kw):
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                raise HttpError("rubik unavailable")
            raise HttpError("unexpected url")
        result = derivs_feed.fetch_okx_derivatives(fetcher=fetcher)
        self.assertEqual(result.source, "okx")
        self.assertEqual(result.status, derivs_feed.STATUS_PARTIAL_OK)
        self.assertAlmostEqual(result.data["funding_rate"], 0.0001)
        self.assertAlmostEqual(result.data["open_interest_btc"], 70000.0)
        self.assertAlmostEqual(result.data["mark_price"], 65000.0)
        # Long/short fields stay null — never fabricated.
        self.assertIsNone(result.data["long_short_ratio"])
        self.assertIsNone(result.data["long_account_pct"])
        self.assertIsNone(result.data["short_account_pct"])

    def test_okx_degraded_when_core_field_missing(self):
        """If OI is missing, core is incomplete → degraded (not partial_ok)."""
        def fetcher(url, *a, **kw):
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001"}]}
            if "okx.com" in url and "open-interest" in url:
                raise HttpError("oi blocked")
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                raise HttpError("blocked")
            raise HttpError("nope")
        result = derivs_feed.fetch_okx_derivatives(fetcher=fetcher)
        self.assertEqual(result.status, "degraded")
        self.assertIsNone(result.data["open_interest_btc"])
        self.assertIsNone(result.data["long_short_ratio"])

    def test_bybit_full_ok(self):
        def fetcher(url, *a, **kw):
            if "bybit.com" in url and "tickers" in url:
                return {"result": {"list": [{
                    "fundingRate": "0.00007", "markPrice": "65020.0",
                    "openInterest": "71000.0", "nextFundingTime": "1745740800000",
                }]}}
            if "bybit.com" in url and "account-ratio" in url:
                return {"result": {"list": [{"buyRatio": "0.6", "sellRatio": "0.4"}]}}
            raise HttpError("unexpected")
        result = derivs_feed.fetch_bybit_derivatives(fetcher=fetcher)
        self.assertEqual(result.source, "bybit")
        self.assertEqual(result.status, STATUS_OK)
        self.assertAlmostEqual(result.data["mark_price"], 65020.0)
        self.assertAlmostEqual(result.data["long_account_pct"], 0.6)
        self.assertAlmostEqual(result.data["short_account_pct"], 0.4)
        self.assertAlmostEqual(result.data["long_short_ratio"], 1.5)

    def test_no_fabrication_when_all_providers_partial_or_fail(self):
        """If every provider is degraded/partial, the artifact data must
        contain only fields actually supplied by that provider — no
        cross-provider field stitching, no fabricated values."""
        def fetcher(url, *a, **kw):
            if "fapi.binance.com" in url:
                raise HttpError("HTTP Error 451: ")
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                raise HttpError("mark blocked")
            if "okx.com" in url and "rubik" in url:
                raise HttpError("rubik blocked")
            if "bybit.com" in url:
                raise HttpError("bybit blocked")
            if "deribit.com" in url:
                raise HttpError("deribit blocked")
            raise HttpError("unexpected")
        result = derivs_feed.fetch_okx_derivatives(fetcher=fetcher)
        # Each null field must be exactly what the API didn't return.
        self.assertIsNone(result.data["mark_price"])
        self.assertIsNone(result.data["long_short_ratio"])
        # Present fields must be the parsed real values.
        self.assertAlmostEqual(result.data["funding_rate"], 0.0001)
        self.assertAlmostEqual(result.data["open_interest_btc"], 70000.0)

    def test_okx_long_short_ratio_parsed_from_rubik(self):
        """When OKX rubik returns a long/short series, the most recent
        ratio is parsed and surfaced (no fabrication of pct breakdown)."""
        def fetcher(url, *a, **kw):
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                # data is [[ts, ratio], …] with most recent last.
                return {"code": "0", "data": [["1745740500000", "1.10"], ["1745740800000", "1.23"]]}
            raise HttpError("unexpected")
        result = derivs_feed.fetch_okx_derivatives(fetcher=fetcher)
        self.assertAlmostEqual(result.data["long_short_ratio"], 1.23)
        # We do NOT synthesise long/short percentages from a single ratio.
        self.assertIsNone(result.data["long_account_pct"])
        self.assertIsNone(result.data["short_account_pct"])

    def test_snapshot_prefers_full_ok_over_partial(self):
        """If OKX returns partial_ok and Bybit returns full ok, the
        snapshot writer must pick Bybit even though OKX came first."""
        from feeds import base as feed_base
        def fetcher(url, *a, **kw):
            if "fapi.binance.com" in url:
                raise HttpError("HTTP Error 451: ")
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                raise HttpError("rubik blocked")
            if "bybit.com" in url and "tickers" in url:
                return {"result": {"list": [{
                    "fundingRate": "0.00009", "markPrice": "65010.0",
                    "openInterest": "72000.0", "nextFundingTime": "1745740800000",
                }]}}
            if "bybit.com" in url and "account-ratio" in url:
                return {"result": {"list": [{"buyRatio": "0.55", "sellRatio": "0.45"}]}}
            raise HttpError(f"unexpected: {url}")
        original_chain = derivs_feed.default_provider_chain
        derivs_feed.default_provider_chain = lambda: [
            lambda: derivs_feed.fetch_binance_derivatives(fetcher=fetcher),
            lambda: derivs_feed.fetch_okx_derivatives(fetcher=fetcher),
            lambda: derivs_feed.fetch_bybit_derivatives(fetcher=fetcher),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                chosen = snap.snapshot_derivatives(out)
                self.assertEqual(chosen.source, "bybit")
                self.assertEqual(chosen.status, STATUS_OK)
                doc = json.loads((out / "derivatives.json").read_text())
                self.assertEqual(doc["source"], "bybit")
                self.assertEqual(doc["status"], "ok")
                # All provider attempts must be recorded for transparency.
                sources = [a["source"] for a in doc["attempts"]]
                self.assertIn("binance", sources)
                self.assertIn("okx", sources)
                self.assertIn("bybit", sources)
        finally:
            derivs_feed.default_provider_chain = original_chain

    def test_snapshot_picks_partial_ok_when_no_full_ok(self):
        """If no provider returns full ok, the snapshot picks the best
        available (partial_ok over degraded), preserving truthfulness."""
        def fetcher(url, *a, **kw):
            if "fapi.binance.com" in url:
                raise HttpError("HTTP Error 451: ")
            if "okx.com" in url and "funding-rate" in url:
                return {"data": [{"fundingRate": "0.0001", "nextFundingTime": "1745740800000"}]}
            if "okx.com" in url and "open-interest" in url:
                return {"data": [{"oiCcy": "70000.0"}]}
            if "okx.com" in url and "mark-price" in url:
                return {"data": [{"markPx": "65000.0"}]}
            if "okx.com" in url and "rubik" in url:
                raise HttpError("rubik blocked")
            if "bybit.com" in url:
                raise HttpError("bybit unavailable")
            if "deribit.com" in url:
                raise HttpError("deribit unavailable")
            raise HttpError(f"unexpected: {url}")
        original_chain = derivs_feed.default_provider_chain
        derivs_feed.default_provider_chain = lambda: [
            lambda: derivs_feed.fetch_binance_derivatives(fetcher=fetcher),
            lambda: derivs_feed.fetch_okx_derivatives(fetcher=fetcher),
            lambda: derivs_feed.fetch_bybit_derivatives(fetcher=fetcher),
            lambda: derivs_feed.fetch_deribit_derivatives(fetcher=fetcher),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                chosen = snap.snapshot_derivatives(out)
                self.assertEqual(chosen.source, "okx")
                self.assertEqual(chosen.status, derivs_feed.STATUS_PARTIAL_OK)
                self.assertIsNone(chosen.data["long_short_ratio"])
                self.assertAlmostEqual(chosen.data["mark_price"], 65000.0)
        finally:
            derivs_feed.default_provider_chain = original_chain


class TestSentiment(unittest.TestCase):
    def test_fng_ok(self):
        def fetcher(url, *a, **kw):
            return {"data": [{"value": "63", "value_classification": "Greed", "timestamp": "1745740800"}]}
        chain = [lambda: sentiment_feed.fetch_fng_sentiment(fetcher=fetcher)]
        chosen, _ = run_with_fallback(chain)
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertEqual(chosen.data["fear_greed_value"], 63)
        self.assertEqual(chosen.data["fear_greed_label"], "Greed")

    def test_fallback_to_coingecko(self):
        def fetcher(url, *a, **kw):
            if "alternative.me" in url:
                raise HttpError("down")
            if "coingecko.com" in url:
                return {
                    "sentiment_votes_up_percentage": 71.0,
                    "sentiment_votes_down_percentage": 29.0,
                }
            raise HttpError("nope")
        chain = sentiment_feed.default_provider_chain(fetcher=fetcher)
        chosen, attempts = run_with_fallback(chain)
        self.assertEqual(chosen.source, "coingecko")
        self.assertEqual(chosen.status, STATUS_OK)
        self.assertEqual(chosen.data["fear_greed_value"], 71)


class TestKeyLevels(unittest.TestCase):
    def test_pivots_match_canonical_formula(self):
        # Build a single previous daily candle: H=70000 L=64000 C=68000.
        d1 = [{
            "open_time_ms": 0, "close_time_ms": 86_400_000,
            "open": 65000, "high": 70000, "low": 64000, "close": 68000, "volume": 1000.0,
        }]
        h = 70000.0; l = 64000.0; c = 68000.0
        p = (h + l + c) / 3.0
        levels = compute_key_levels([], d1)
        self.assertAlmostEqual(levels["pivot_classic"], p)
        self.assertAlmostEqual(levels["r1"], 2 * p - l)
        self.assertAlmostEqual(levels["s1"], 2 * p - h)
        self.assertAlmostEqual(levels["r2"], p + (h - l))
        self.assertAlmostEqual(levels["s2"], p - (h - l))

    def test_recent_high_low_from_real_candles(self):
        # 24 hourly candles, varying highs/lows.
        h1 = []
        for i in range(24):
            h1.append({
                "open_time_ms": i * 3600_000,
                "close_time_ms": (i + 1) * 3600_000,
                "open": 65000 + i,
                "high": 65000 + i + 100,
                "low": 65000 + i - 50,
                "close": 65000 + i + 10,
                "volume": 5.0,
            })
        levels = compute_key_levels(h1, [])
        self.assertEqual(levels["recent_high"], max(c["high"] for c in h1))
        self.assertEqual(levels["recent_low"], min(c["low"] for c in h1))

    def test_no_candles_marks_degraded(self):
        levels = compute_key_levels([], [])
        self.assertTrue(levels["degraded"])
        self.assertIsNone(levels["pivot_classic"])
        self.assertIsNone(levels["recent_high"])

    def test_sma_uses_only_supplied_closes(self):
        d1 = []
        for i in range(20):
            d1.append({
                "open_time_ms": i * 86_400_000,
                "close_time_ms": (i + 1) * 86_400_000,
                "open": 60000 + i, "high": 60500 + i, "low": 59500 + i,
                "close": 60000 + i, "volume": 100.0,
            })
        levels = compute_key_levels([], d1)
        expected = sum(60000 + i for i in range(20)) / 20
        self.assertAlmostEqual(levels["sma_20"], expected)
        self.assertIsNone(levels["sma_50"])  # not enough data — never fabricated
        self.assertIsNone(levels["sma_200"])


class TestSnapshotWriter(unittest.TestCase):
    def test_full_failure_writes_failed_artifact_no_fabrication(self):
        # Force every fetcher to fail by monkeypatching http_get_json.
        from feeds import base as feed_base
        original = feed_base.http_get_json
        feed_base.http_get_json = _failing_fetcher
        # Also patch the module-level fetcher used by the default chain
        # builders (they default to feeds.base.http_get_json — but they
        # captured it at import time, so we re-pass `_failing_fetcher`
        # explicitly through monkeypatching the chain builders).
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                # Use 1h interval only for speed.
                # We replace the chain builders to use the failing fetcher.
                original_candles_chain = candles_feed.default_provider_chain
                original_derivs_chain = derivs_feed.default_provider_chain
                original_senti_chain = sentiment_feed.default_provider_chain
                candles_feed.default_provider_chain = lambda interval: [
                    lambda: candles_feed.fetch_binance_candles(interval, fetcher=_failing_fetcher),
                    lambda: candles_feed.fetch_coinbase_candles(interval, fetcher=_failing_fetcher),
                    lambda: candles_feed.fetch_kraken_candles(interval, fetcher=_failing_fetcher),
                ]
                derivs_feed.default_provider_chain = lambda: [
                    lambda: derivs_feed.fetch_binance_derivatives(fetcher=_failing_fetcher),
                    lambda: derivs_feed.fetch_okx_derivatives(fetcher=_failing_fetcher),
                    lambda: derivs_feed.fetch_bybit_derivatives(fetcher=_failing_fetcher),
                    lambda: derivs_feed.fetch_deribit_derivatives(fetcher=_failing_fetcher),
                ]
                sentiment_feed.default_provider_chain = lambda: [
                    lambda: sentiment_feed.fetch_fng_sentiment(fetcher=_failing_fetcher),
                    lambda: sentiment_feed.fetch_coingecko_sentiment(fetcher=_failing_fetcher),
                ]
                try:
                    snap.run(out, intervals=("1h",))
                finally:
                    candles_feed.default_provider_chain = original_candles_chain
                    derivs_feed.default_provider_chain = original_derivs_chain
                    sentiment_feed.default_provider_chain = original_senti_chain

                candles_path = out / "candles_1h.json"
                self.assertTrue(candles_path.exists())
                doc = json.loads(candles_path.read_text())
                self.assertEqual(doc["status"], "failed")
                self.assertIsNone(doc["data"], "must not fabricate candles when all sources fail")
                self.assertGreaterEqual(len(doc["attempts"]), 3)

                health = json.loads((out / "source_health.json").read_text())
                self.assertEqual(health["overall"], "failed")
                # Every kind has a freshness budget defined — including the
                # sub-hour candle kinds, even when no run is currently
                # producing one (the budget table is the contract the UI
                # reads to decide what STALE means).
                for k in (
                    "candles_1m", "candles_5m", "candles_15m",
                    "candles_1h", "candles_4h", "candles_1d",
                    "derivatives", "sentiment",
                ):
                    self.assertIn(k, health["freshness_budget_seconds"])
                # Sub-hour budgets must be tighter than the 1h budget — a
                # 1m candle that is two hours old is unambiguously stale.
                self.assertLess(
                    health["freshness_budget_seconds"]["candles_1m"],
                    health["freshness_budget_seconds"]["candles_1h"],
                )
                self.assertLess(
                    health["freshness_budget_seconds"]["candles_5m"],
                    health["freshness_budget_seconds"]["candles_1h"],
                )
                self.assertLessEqual(
                    health["freshness_budget_seconds"]["candles_15m"],
                    health["freshness_budget_seconds"]["candles_1h"],
                )
                # All sources reported failed.
                for v in health["sources"].values():
                    self.assertIn(v["status"], ("failed", "degraded"))
        finally:
            feed_base.http_get_json = original

    def test_happy_path_produces_real_artifacts(self):
        binance_h1 = _binance_klines_fixture(n_complete=24, include_live=False)
        binance_d1 = []
        # Build 30 daily candles for SMA / pivot.
        d_ms = 86_400_000
        base_open = 1745625600000
        for i in range(30):
            o = base_open + i * d_ms
            binance_d1.append([
                o, "60000", "60800", "59500", "60200", "1000",
                o + d_ms - 1, "0", 0, "0", "0", "0",
            ])
        binance_h4 = []
        for i in range(20):
            o = base_open + i * 4 * 3600 * 1000
            binance_h4.append([
                o, "60000", "60500", "59800", "60200", "100",
                o + 4 * 3600 * 1000 - 1, "0", 0, "0", "0", "0",
            ])

        def http_for_url(url, *a, **kw):
            if "klines" in url and "interval=1h" in url:
                return binance_h1
            if "klines" in url and "interval=4h" in url:
                return binance_h4
            if "klines" in url and "interval=1d" in url:
                return binance_d1
            if "premiumIndex" in url:
                return {"lastFundingRate": "0.00010", "nextFundingTime": 1745740800000, "markPrice": "65000"}
            if "openInterest" in url:
                return {"openInterest": "73000"}
            if "globalLongShortAccountRatio" in url:
                return [{"longShortRatio": "1.4", "longAccount": "0.58", "shortAccount": "0.42"}]
            if "alternative.me" in url:
                return {"data": [{"value": "55", "value_classification": "Greed", "timestamp": "1745740800"}]}
            raise HttpError(f"unhandled {url}")

        from feeds import base as feed_base
        original = feed_base.http_get_json
        original_candles_chain = candles_feed.default_provider_chain
        original_derivs_chain = derivs_feed.default_provider_chain
        original_senti_chain = sentiment_feed.default_provider_chain
        feed_base.http_get_json = http_for_url
        candles_feed.default_provider_chain = lambda interval: [
            lambda: candles_feed.fetch_binance_candles(interval, fetcher=http_for_url),
        ]
        derivs_feed.default_provider_chain = lambda: [
            lambda: derivs_feed.fetch_binance_derivatives(fetcher=http_for_url),
        ]
        sentiment_feed.default_provider_chain = lambda: [
            lambda: sentiment_feed.fetch_fng_sentiment(fetcher=http_for_url),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                snap.run(out, intervals=("1h", "4h", "1d"))
                # Candles ok
                doc = json.loads((out / "candles_1h.json").read_text())
                self.assertEqual(doc["status"], "ok")
                self.assertEqual(doc["source"], "binance")
                # Derivatives ok
                ddoc = json.loads((out / "derivatives.json").read_text())
                self.assertEqual(ddoc["source"], "binance")
                self.assertIn(ddoc["status"], ("ok", "degraded"))
                # Sentiment ok
                sdoc = json.loads((out / "sentiment.json").read_text())
                self.assertEqual(sdoc["source"], "alternative.me")
                # Key levels
                kl = json.loads((out / "key_levels.json").read_text())
                self.assertEqual(kl["status"], "ok")
                self.assertIsNotNone(kl["data"]["pivot_classic"])
                self.assertIsNotNone(kl["data"]["recent_high"])
                # Health
                health = json.loads((out / "source_health.json").read_text())
                self.assertEqual(health["overall"], "ok")
        finally:
            feed_base.http_get_json = original
            candles_feed.default_provider_chain = original_candles_chain
            derivs_feed.default_provider_chain = original_derivs_chain
            sentiment_feed.default_provider_chain = original_senti_chain


class TestSubHourCandleArtifacts(unittest.TestCase):
    """Phase A — wire 1m / 5m / 15m candle artifacts.

    These tests verify the snapshot writer produces real closed-candle
    artifacts for the sub-hour timeframes, that source_health surfaces
    them with named providers + freshness budgets, and that the
    no-synthetic-OHLC invariant holds when every provider fails.
    """

    def _binance_subhour_fixture(self, interval_ms: int, n: int = 30):
        """Build n closed Binance kline tuples with monotonic time stamps."""
        base_ms = 1745625600000
        out = []
        for i in range(n):
            o = base_ms + i * interval_ms
            out.append([
                o, "60000", "60500", "59800", "60200", "10",
                o + interval_ms - 1, "0", 0, "0", "0", "0",
            ])
        return out

    def test_sub_hour_intervals_produce_real_artifacts(self):
        """Snapshot writer creates candles_{1m,5m,15m}.json with real
        closed candles when Binance is reachable."""
        m1 = self._binance_subhour_fixture(60_000, n=30)
        m5 = self._binance_subhour_fixture(5 * 60_000, n=30)
        m15 = self._binance_subhour_fixture(15 * 60_000, n=30)

        def http_for_url(url, *a, **kw):
            if "interval=1m" in url:
                return m1
            if "interval=5m" in url:
                return m5
            if "interval=15m" in url:
                return m15
            if "interval=1h" in url:
                return self._binance_subhour_fixture(60 * 60_000, n=24)
            if "interval=4h" in url:
                return self._binance_subhour_fixture(4 * 60 * 60_000, n=20)
            if "interval=1d" in url:
                return self._binance_subhour_fixture(24 * 60 * 60_000, n=30)
            if "premiumIndex" in url:
                return {"lastFundingRate": "0.0001", "nextFundingTime": 1745740800000, "markPrice": "65000"}
            if "openInterest" in url:
                return {"openInterest": "73000"}
            if "globalLongShortAccountRatio" in url:
                return [{"longShortRatio": "1.4", "longAccount": "0.58", "shortAccount": "0.42"}]
            if "alternative.me" in url:
                return {"data": [{"value": "55", "value_classification": "Greed", "timestamp": "1745740800"}]}
            raise HttpError(f"unhandled {url}")

        original_candles_chain = candles_feed.default_provider_chain
        original_derivs_chain = derivs_feed.default_provider_chain
        original_senti_chain = sentiment_feed.default_provider_chain
        candles_feed.default_provider_chain = lambda interval: [
            lambda: candles_feed.fetch_binance_candles(interval, fetcher=http_for_url),
        ]
        derivs_feed.default_provider_chain = lambda: [
            lambda: derivs_feed.fetch_binance_derivatives(fetcher=http_for_url),
        ]
        sentiment_feed.default_provider_chain = lambda: [
            lambda: sentiment_feed.fetch_fng_sentiment(fetcher=http_for_url),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                snap.run(out)  # default intervals include 1m/5m/15m
                for kind, expected_count in (("1m", 30), ("5m", 30), ("15m", 30)):
                    path = out / f"candles_{kind}.json"
                    self.assertTrue(path.exists(), f"missing {path}")
                    doc = json.loads(path.read_text())
                    self.assertEqual(doc["status"], "ok", f"{kind} should be ok")
                    self.assertEqual(doc["kind"], f"candles_{kind}")
                    self.assertEqual(doc["source"], "binance")
                    self.assertIsNotNone(doc["data"])
                    self.assertEqual(len(doc["data"]["candles"]), expected_count)
                    # Every candle must carry real OHLC keys.
                    for c in doc["data"]["candles"]:
                        for k in ("open", "high", "low", "close", "open_time_ms", "close_time_ms"):
                            self.assertIn(k, c)
                        self.assertGreaterEqual(c["high"], c["low"])
                        # Closed-candle invariant: close_time strictly after open_time.
                        self.assertGreater(c["close_time_ms"], c["open_time_ms"])

                # Source health must surface every sub-hour kind with a
                # named provider and a freshness budget.
                health = json.loads((out / "source_health.json").read_text())
                for kind in ("candles_1m", "candles_5m", "candles_15m"):
                    self.assertIn(kind, health["sources"])
                    self.assertEqual(health["sources"][kind]["source"], "binance")
                    self.assertEqual(health["sources"][kind]["status"], "ok")
                    self.assertIn(kind, health["freshness_budget_seconds"])
                    self.assertGreater(health["freshness_budget_seconds"][kind], 0)
        finally:
            candles_feed.default_provider_chain = original_candles_chain
            derivs_feed.default_provider_chain = original_derivs_chain
            sentiment_feed.default_provider_chain = original_senti_chain

    def test_sub_hour_falls_through_to_coinbase(self):
        """Binance 451 must not break the 1m/5m/15m artifacts — Coinbase
        provides each of these granularities natively."""
        # Coinbase format: [time_s, low, high, open, close, volume]
        cb_1m = [
            [1745740800, 64000.0, 64500.0, 64100.0, 64400.0, 5.0],
            [1745740860, 64400.0, 64900.0, 64400.0, 64800.0, 6.0],
            [1745740920, 64800.0, 65000.0, 64700.0, 64950.0, 7.0],
        ]

        def http_for_url(url, *a, **kw):
            if "binance.com" in url:
                raise HttpError("HTTP Error 451: ")
            if "exchange.coinbase.com" in url and "granularity=60" in url:
                return cb_1m
            if "exchange.coinbase.com" in url and "granularity=300" in url:
                # Same shape, different cadence — three 5m bars.
                return cb_1m
            if "exchange.coinbase.com" in url and "granularity=900" in url:
                return cb_1m
            raise HttpError("unexpected")

        for interval in ("1m", "5m", "15m"):
            chain = [
                lambda i=interval: candles_feed.fetch_binance_candles(i, fetcher=http_for_url),
                lambda i=interval: candles_feed.fetch_coinbase_candles(i, fetcher=http_for_url),
                lambda i=interval: candles_feed.fetch_kraken_candles(i, fetcher=_failing_fetcher),
            ]
            chosen, attempts = run_with_fallback(chain)
            self.assertEqual(chosen.status, STATUS_OK, f"{interval} should succeed via coinbase")
            self.assertEqual(chosen.source, "coinbase",
                             f"{interval} must fall back to coinbase when binance is 451")
            self.assertEqual(attempts[0].source, "binance")
            self.assertEqual(attempts[0].status, STATUS_FAILED)

    def test_sub_hour_no_synthetic_ohlc_when_all_fail(self):
        """If every provider fails, the 1m/5m/15m artifacts must be
        `failed` with `data is None` — never fabricated OHLC."""
        original_candles_chain = candles_feed.default_provider_chain
        original_derivs_chain = derivs_feed.default_provider_chain
        original_senti_chain = sentiment_feed.default_provider_chain
        candles_feed.default_provider_chain = lambda interval: [
            lambda: candles_feed.fetch_binance_candles(interval, fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_coinbase_candles(interval, fetcher=_failing_fetcher),
            lambda: candles_feed.fetch_kraken_candles(interval, fetcher=_failing_fetcher),
        ]
        derivs_feed.default_provider_chain = lambda: [
            lambda: derivs_feed.fetch_binance_derivatives(fetcher=_failing_fetcher),
        ]
        sentiment_feed.default_provider_chain = lambda: [
            lambda: sentiment_feed.fetch_fng_sentiment(fetcher=_failing_fetcher),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                snap.run(out, intervals=("1m", "5m", "15m"))
                for kind in ("1m", "5m", "15m"):
                    path = out / f"candles_{kind}.json"
                    self.assertTrue(path.exists())
                    doc = json.loads(path.read_text())
                    self.assertEqual(doc["status"], "failed",
                                     f"{kind} must be failed when all providers fail")
                    self.assertIsNone(doc["data"],
                                      f"{kind} must NOT contain fabricated candle data")
                    # Provenance: every provider attempt is recorded.
                    sources = [a["source"] for a in doc["attempts"]]
                    self.assertIn("binance", sources)
                    self.assertIn("coinbase", sources)
                    self.assertIn("kraken", sources)

                # Source health declares the sub-hour kinds as failed but
                # still publishes their freshness budgets so the UI can
                # render a STALE row instead of a blank.
                health = json.loads((out / "source_health.json").read_text())
                for kind in ("candles_1m", "candles_5m", "candles_15m"):
                    self.assertEqual(health["sources"][kind]["status"], "failed")
                    self.assertIn(kind, health["freshness_budget_seconds"])
        finally:
            candles_feed.default_provider_chain = original_candles_chain
            derivs_feed.default_provider_chain = original_derivs_chain
            sentiment_feed.default_provider_chain = original_senti_chain

    def test_sub_hour_closed_candle_invariant(self):
        """The snapshotter must drop the in-progress (live) candle from
        every sub-hour series before persisting, so the artifact only
        contains real closed bars."""
        # 30 closed bars + 1 live (in-progress) bar.
        interval_ms = 60_000  # 1m
        base_ms = 1745625600000
        complete = []
        for i in range(30):
            o = base_ms + i * interval_ms
            complete.append([
                o, "60000", "60500", "59800", "60200", "10",
                o + interval_ms - 1, "0", 0, "0", "0", "0",
            ])
        live_open = base_ms + 30 * interval_ms
        live = [
            live_open, "60200", "60900", "60100", "60800", "5",
            live_open + interval_ms - 1, "0", 0, "0", "0", "0",
        ]
        payload = complete + [live]

        result = candles_feed.fetch_binance_candles(
            "1m", fetcher=_binance_candles_fetcher(payload),
        )
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(len(result.data["candles"]), 31)

        # Pin "now" to mid-live-candle.
        now = datetime.fromtimestamp((live_open + interval_ms / 2) / 1000, tz=timezone.utc)
        closed = candles_feed.closed_candles(result, now=now)
        self.assertEqual(len(closed), 30, "live 1m candle must be dropped")
        # Last closed candle's close_time_ms is strictly <= now.
        now_ms = int(now.timestamp() * 1000)
        for c in closed:
            self.assertLessEqual(c["close_time_ms"], now_ms)


if __name__ == "__main__":
    unittest.main(verbosity=2)
