"""
Exact-horizon resolver.

For every open forecast whose target_time has passed:
  1. Fetch the 1h candle whose interval contains target_time.
  2. Refuse incomplete candles (closeTime > now → NotYet, skip).
  3. Compute realized direction relative to entry_price.
  4. Compute correctness, Brier, and log-loss components.
  5. Append a single resolution event. Original forecast row untouched.

Usage:
    python resolve.py --root btc-brain/ledger/data
    python resolve.py --root btc-brain/ledger/data --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Local imports — when this script is run from any cwd.
sys.path.insert(0, str(Path(__file__).parent))
from ledger import (  # noqa: E402
    Ledger,
    LedgerError,
    brier,
    logloss,
    parse_iso_utc,
    utc_now_iso,
)
import price_source as _ps  # noqa: E402
from price_source import (  # noqa: E402
    Candle,
    NotYet,
    PriceFetchError,
    fetch_close_for_target,
    fetch_closes_for_targets,
    PRICE_SOURCE_VERSION,
    SOURCE_BINANCE,
    SOURCE_COINGECKO,
    SOURCE_KRAKEN,
)

_ps_binance_range_map = _ps._binance_range_map

RESOLVER_VERSION = "resolver-v0.1.0"


def _outcome(direction: str, entry_price: float, actual_close: float) -> int:
    """1 if forecasted direction was right, 0 otherwise.

    Tie-breaker: an exact-equal close is treated as "no movement" and counts
    against the forecast (outcome=0) regardless of direction. This is
    intentional and conservative.
    """
    if actual_close == entry_price:
        return 0
    moved_up = actual_close > entry_price
    if direction == "up":
        return 1 if moved_up else 0
    return 0 if moved_up else 1


def resolve_one(forecast: dict, candle: Candle) -> dict:
    actual_close = candle.close_price
    entry = float(forecast["entry_price"])
    actual_return = (actual_close - entry) / entry
    o = _outcome(forecast["direction"], entry, actual_close)
    p = float(forecast["probability"])
    return {
        "forecast_id": forecast["forecast_id"],
        "resolved_at": utc_now_iso(),
        "actual_close": actual_close,
        "actual_return": actual_return,
        "direction_correct": bool(o),
        "brier_component": brier(p, o),
        "logloss_component": logloss(p, o),
        "status": "resolved",
        "resolver_version": RESOLVER_VERSION,
        "candle_open_time": candle.open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candle_close_time": candle.close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_source": candle.source,
    }


def _count_calls(fn):
    """Wrap a 0+ arg callable, counting invocations on `.calls`."""
    def wrapped(*a, **kw):
        wrapped.calls += 1
        return fn(*a, **kw)
    wrapped.calls = 0
    return wrapped


def _instrumented_default_sources():
    """Default Binance->CoinGecko->Kraken chain whose network calls are counted.

    Returns (sources, counter) where `counter.calls` is the total number of
    outbound HTTP page requests issued across all sources during a run. This
    is what we log to prove the batched resolver makes far fewer round-trips
    than the old per-forecast path.
    """
    counter = _count_calls(lambda: None)
    counter.calls = 0

    def _bump():
        counter.calls += 1

    def _binance_fetch(symbol, interval, start_ms, end_ms):
        _bump()
        return _ps._binance_klines(symbol, interval, start_ms, end_ms)

    def _coingecko_fetch():
        _bump()
        return _ps._coingecko_fetch()

    def _kraken_fetch(since_s):
        _bump()
        return _ps._kraken_fetch(since_s)

    sources = [
        (SOURCE_BINANCE, lambda s, e: _ps._binance_range_map(s, e, _binance_fetch)),
        (SOURCE_COINGECKO, lambda s, e: _ps._coingecko_range_map(s, e, _coingecko_fetch)),
        (SOURCE_KRAKEN, lambda s, e: _ps._kraken_range_map(s, e, _kraken_fetch)),
    ]
    return sources, counter


def run(root: Path, dry_run: bool = False, fetcher=None, now=None,
        sources=None) -> dict:
    """Resolve every due forecast from a single batched fetch.

    All due forecasts are collected first; their closing candles are fetched
    in as few network round-trips as possible (one paged range over the
    Binance source, then CoinGecko/Kraken only for stragglers) and resolved by
    in-memory lookup. A target with no candle in any source is left open
    (skipped_not_yet) — never fabricated.

    `fetcher` (a Binance-shaped page fetcher) is honored for backward
    compatibility: when provided it becomes the Binance source so existing
    single-fetcher tests keep working through the batched path.
    """
    ledger = Ledger.at(root)
    open_forecasts = ledger.open_forecasts(now=now)
    summary = {
        "now": utc_now_iso(),
        "open_count": len(open_forecasts),
        "resolved": [],
        "skipped_not_yet": [],
        "errors": [],
    }
    if not open_forecasts:
        summary["request_count"] = 0
        return summary

    # Build the source chain. A test/explicit `fetcher` replaces the Binance
    # range source with one driven by that fetcher (still paged internally).
    if sources is None:
        if fetcher is not None:
            counted = _count_calls(fetcher)
            sources = [(
                "binance",
                lambda s, e: _ps_binance_range_map(s, e, counted),
            )]
            _request_counter = counted
        else:
            sources, _request_counter = _instrumented_default_sources()
    else:
        _request_counter = None

    stats: dict = {}
    targets = [fc["target_time"] for fc in open_forecasts]
    candle_map = fetch_closes_for_targets(
        targets, now=now, sources=sources, stats=stats
    )

    for fc in open_forecasts:
        candle = candle_map.get(fc["target_time"])
        if candle is None:
            summary["skipped_not_yet"].append(
                {"forecast_id": fc["forecast_id"],
                 "reason": f"no closed candle for target {fc['target_time']} "
                           f"in any source"}
            )
            continue
        resolution = resolve_one(fc, candle)
        if dry_run:
            summary["resolved"].append({"dry_run": True, **resolution})
            continue
        try:
            ledger.append_resolution(resolution)
        except LedgerError as e:
            summary["errors"].append(
                {"forecast_id": fc["forecast_id"], "error": str(e)}
            )
            continue
        summary["resolved"].append(resolution)

    summary["source_hits"] = stats.get("source_hits", {})
    summary["source_errors"] = stats.get("source_errors", {})
    if _request_counter is not None:
        summary["request_count"] = getattr(_request_counter, "calls", None)
    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    summary = run(Path(args.root), dry_run=args.dry_run)
    # Observability: prove the batched resolver issues few requests even on a
    # large backlog (old path was one request per forecast).
    print(
        f"[resolve] open={summary['open_count']} "
        f"resolved={len(summary['resolved'])} "
        f"skipped={len(summary['skipped_not_yet'])} "
        f"http_requests={summary.get('request_count')} "
        f"source_hits={summary.get('source_hits', {})}",
        file=sys.stderr,
    )
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
