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
from price_source import (  # noqa: E402
    Candle,
    NotYet,
    PriceFetchError,
    fetch_close_for_target,
    PRICE_SOURCE_VERSION,
)

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


def run(root: Path, dry_run: bool = False, fetcher=None, now=None) -> dict:
    ledger = Ledger.at(root)
    open_forecasts = ledger.open_forecasts(now=now)
    summary = {
        "now": utc_now_iso(),
        "open_count": len(open_forecasts),
        "resolved": [],
        "skipped_not_yet": [],
        "errors": [],
    }
    for fc in open_forecasts:
        try:
            kwargs = {} if fetcher is None else {"fetcher": fetcher}
            if now is not None:
                kwargs["now"] = now
            candle = fetch_close_for_target(fc["target_time"], **kwargs)
        except NotYet as e:
            summary["skipped_not_yet"].append(
                {"forecast_id": fc["forecast_id"], "reason": str(e)}
            )
            continue
        except PriceFetchError as e:
            summary["errors"].append(
                {"forecast_id": fc["forecast_id"], "error": str(e)}
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
    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    summary = run(Path(args.root), dry_run=args.dry_run)
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
