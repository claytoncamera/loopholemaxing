"""
CLI to issue a new forecast row.

Example:
    python issue_forecast.py --root btc-brain/ledger/data \
        --horizon 1h --direction up --probability 0.62 \
        --entry-price 67450.0 --regime chop \
        --confidence-reason "4H momentum + funding flat" \
        --invalidation "BTC < 65500 before target"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger import (  # noqa: E402
    Ledger,
    new_forecast_id,
    parse_iso_utc,
    utc_now_iso,
    HORIZONS,
)

HORIZON_DELTA = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def build_row(args: argparse.Namespace) -> dict:
    issued = parse_iso_utc(args.issued_at) if args.issued_at else parse_iso_utc(utc_now_iso())
    target = issued + HORIZON_DELTA[args.horizon]
    return {
        "forecast_id": args.forecast_id or new_forecast_id(),
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asset": args.asset,
        "horizon": args.horizon,
        "target_time": target.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_rule": args.target_rule,
        "direction": args.direction,
        "probability": args.probability,
        "entry_price": args.entry_price,
        "model_version": args.model_version,
        "signal_version": args.signal_version,
        "regime_at_issue": args.regime,
        "feature_snapshot_uri": args.feature_snapshot_uri,
        "source_snapshot_uri": args.source_snapshot_uri,
        "confidence_reason": args.confidence_reason,
        "invalidation": args.invalidation,
        "created_by": args.created_by,
        "status": "open",
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--asset", default="BTCUSD")
    ap.add_argument("--horizon", required=True, choices=sorted(HORIZONS))
    ap.add_argument("--direction", required=True, choices=["up", "down"])
    ap.add_argument("--probability", type=float, required=True)
    ap.add_argument("--entry-price", dest="entry_price", type=float, required=True)
    ap.add_argument("--target-rule", dest="target_rule", default="close_above_entry")
    ap.add_argument("--model-version", dest="model_version", default="v0.1.0-baseline")
    ap.add_argument("--signal-version", dest="signal_version", default="v0.1.0")
    ap.add_argument("--regime", default="unknown",
                    choices=["bull", "bear", "chop", "unknown"])
    ap.add_argument("--feature-snapshot-uri", dest="feature_snapshot_uri",
                    default="snapshots/none.json")
    ap.add_argument("--source-snapshot-uri", dest="source_snapshot_uri",
                    default="snapshots/none.json")
    ap.add_argument("--confidence-reason", dest="confidence_reason", required=True)
    ap.add_argument("--invalidation", required=True)
    ap.add_argument("--created-by", dest="created_by", default="cli")
    ap.add_argument("--issued-at", dest="issued_at",
                    help="override issued_at (ISO UTC)")
    ap.add_argument("--forecast-id", dest="forecast_id",
                    help="override forecast_id (UUID)")
    args = ap.parse_args(argv)
    row = build_row(args)
    Ledger.at(args.root).append_forecast(row)
    json.dump(row, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
