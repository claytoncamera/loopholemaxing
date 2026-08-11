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
    SOURCE_COINBASE,
    SOURCE_COINGECKO,
    SOURCE_KRAKEN,
    VENUE_TAGS,
    default_venue_sources,
)

_ps_binance_range_map = _ps._binance_range_map

RESOLVER_VERSION = "resolver-v0.2.0"


def _normalize_source_tag(candle_source: str) -> str:
    """Plain venue tag for a Candle.source value.

    Binance candles historically carry PRICE_SOURCE_VERSION
    ("binance:BTCUSDT:1h"); other sources carry plain tags. The additive
    `resolution_source` field always gets the plain tag so entry/resolution
    venue matching is analyzable with a string compare.
    """
    return candle_source.split(":", 1)[0]


def _entry_venue(forecast: dict) -> str | None:
    """The venue this forecast's entry price came from, if resolvable.

    Only rows that carry entry_source naming a known venue get venue-matched
    resolution; everything else (all pre-v0.3 rows, "unknown", coingecko)
    resolves through the existing default chain exactly as before.
    """
    v = str(forecast.get("entry_source") or "").strip().lower()
    return v if v in VENUE_TAGS else None


def _chain_for_venue(venue: str, base_sources: list, venue_sources: dict) -> list:
    """Source chain that tries `venue` FIRST, then the existing chain.

    If the base chain already contains the venue (e.g. binance), it is moved
    to the front rather than duplicated — this keeps test-injected fetchers
    authoritative. If the venue has no available range fn, the base chain is
    returned unchanged (graceful fallback, never an error).
    """
    base = list(base_sources)
    for i, (tag, fn) in enumerate(base):
        if tag == venue:
            return [base[i]] + base[:i] + base[i + 1:]
    vfn = (venue_sources or {}).get(venue)
    if vfn is None:
        return base
    return [(venue, vfn)] + base


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
        # Additive v0.2 field: plain venue tag ("binance", "coinbase", ...)
        # so entry/resolution venue matching is auditable without parsing
        # the richer price_source string.
        "resolution_source": _normalize_source_tag(candle.source),
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

    def _coinbase_fetch(start_iso, end_iso):
        _bump()
        return _ps._coinbase_fetch(start_iso, end_iso)

    sources = [
        (SOURCE_BINANCE, lambda s, e: _ps._binance_range_map(s, e, _binance_fetch)),
        (SOURCE_COINGECKO, lambda s, e: _ps._coingecko_range_map(s, e, _coingecko_fetch)),
        (SOURCE_KRAKEN, lambda s, e: _ps._kraken_range_map(s, e, _kraken_fetch)),
    ]
    # Venue map for entry-source-matched resolution, same request counter.
    venue_sources = {
        SOURCE_BINANCE: lambda s, e: _ps._binance_range_map(s, e, _binance_fetch),
        SOURCE_COINBASE: lambda s, e: _ps._coinbase_range_map(s, e, _coinbase_fetch),
        SOURCE_KRAKEN: lambda s, e: _ps._kraken_range_map(s, e, _kraken_fetch),
    }
    return sources, counter, venue_sources


def run(root: Path, dry_run: bool = False, fetcher=None, now=None,
        sources=None, venue_sources=None) -> dict:
    """Resolve every due forecast from a single batched fetch.

    All due forecasts are collected first; their closing candles are fetched
    in as few network round-trips as possible (one paged range over the
    Binance source, then CoinGecko/Kraken only for stragglers) and resolved by
    in-memory lookup. A target with no candle in any source is left open
    (skipped_not_yet) — never fabricated.

    Venue unification (v0.2): a forecast that carries `entry_source` naming a
    known venue (binance/coinbase/kraken) is resolved against a chain that
    tries THAT venue first, falling back to the existing chain when it cannot
    answer — entry and resolution then come from the same exchange, killing
    the 5-10bps cross-exchange basis that decided ~90 near-tie resolutions.
    Rows without entry_source resolve exactly as before. `venue_sources`
    ({tag: range_map_fn}) may be injected for tests; the comparison rule
    (close vs entry_price) is unchanged in all paths.

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
            sources, _request_counter, default_venues = \
                _instrumented_default_sources()
            if venue_sources is None:
                venue_sources = default_venues
    else:
        _request_counter = None
    if venue_sources is None:
        venue_sources = default_venue_sources()

    # Partition: rows naming a known entry venue get a venue-first chain;
    # everything else takes the default chain (bit-identical to pre-v0.2).
    default_group: list[dict] = []
    venue_groups: dict[str, list[dict]] = {}
    for fc in open_forecasts:
        venue = _entry_venue(fc)
        if venue is None:
            default_group.append(fc)
        else:
            venue_groups.setdefault(venue, []).append(fc)

    stats: dict = {}
    candle_by_forecast: dict[str, Candle] = {}
    if default_group:
        cmap = fetch_closes_for_targets(
            [fc["target_time"] for fc in default_group],
            now=now, sources=sources, stats=stats,
        )
        for fc in default_group:
            c = cmap.get(fc["target_time"])
            if c is not None:
                candle_by_forecast[fc["forecast_id"]] = c
    for venue in sorted(venue_groups):
        group = venue_groups[venue]
        chain = _chain_for_venue(venue, sources, venue_sources)
        cmap = fetch_closes_for_targets(
            [fc["target_time"] for fc in group],
            now=now, sources=chain, stats=stats,
        )
        for fc in group:
            c = cmap.get(fc["target_time"])
            if c is not None:
                candle_by_forecast[fc["forecast_id"]] = c

    for fc in open_forecasts:
        candle = candle_by_forecast.get(fc["forecast_id"])
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
