"""
Phase 2 snapshot writer.

Produces the public artifacts the BTC Brain frontend reads:

  btc-brain/data/public/candles_1m.json
  btc-brain/data/public/candles_5m.json
  btc-brain/data/public/candles_15m.json
  btc-brain/data/public/candles_1h.json
  btc-brain/data/public/candles_4h.json
  btc-brain/data/public/candles_1d.json
  btc-brain/data/public/derivatives.json
  btc-brain/data/public/sentiment.json
  btc-brain/data/public/key_levels.json
  btc-brain/data/public/source_health.json

Every artifact carries:
  * `source`               which provider supplied the data
  * `status`               ok | degraded | stale | failed
  * `fetched_at`           ISO-8601 UTC
  * `schema_version`       monotonically increasing
  * `attempts`             list of {source, status, error?, latency_ms}
                           — for transparency

We never write fabricated data. If the chosen result is `failed`, the
artifact's `data` is null and `status` is `failed` — the frontend renders
"unavailable" rather than guessing.

Usage:
    python btc-brain/data/scripts/snapshot.py \
        --out btc-brain/data/public

Add `--offline-fixture` to write a smoke artifact from a local fixture
file (used by tests / CI dry runs).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from feeds.base import (  # noqa: E402
    FeedResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_STALE,
    run_with_fallback,
    utc_now_iso,
)
from feeds import candles as candles_feed  # noqa: E402
from feeds import derivatives as derivs_feed  # noqa: E402
from feeds import sentiment as sentiment_feed  # noqa: E402
from key_levels import compute_key_levels  # noqa: E402


SCHEMA_VERSION = "phase2-data-v1"


def _wrap_artifact(kind: str, chosen: FeedResult, attempts: list[FeedResult]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "source": chosen.source,
        "status": chosen.status,
        "fetched_at": chosen.fetched_at,
        "error": chosen.error,
        "data": chosen.data,
        "attempts": [a.to_dict() for a in attempts],
        "notes": list(chosen.notes),
    }


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


DEFAULT_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


def snapshot_candles(out_dir: Path, intervals=DEFAULT_INTERVALS) -> dict:
    results: dict = {}
    for interval in intervals:
        chain = candles_feed.default_provider_chain(interval)
        chosen, attempts = run_with_fallback(chain)
        artifact = _wrap_artifact(f"candles_{interval}", chosen, attempts)
        write_json(out_dir / f"candles_{interval}.json", artifact)
        results[interval] = chosen
    return results


def snapshot_derivatives(out_dir: Path) -> FeedResult:
    chain = derivs_feed.default_provider_chain()
    # Two-pass acceptance:
    #   1. Accept the first provider that returns full `ok`.
    #   2. If none, accept the first that returns `partial_ok` (core
    #      fields present, only the rich/optional sub-fields missing).
    #   3. Otherwise fall back to whatever is left (degraded / failed).
    # This way Binance 451 → OKX partial → Bybit ok upgrades the live
    # status from degraded to ok without ever fabricating a sub-field.
    chosen, attempts = run_with_fallback(
        chain,
        accept=lambda r: r.status == STATUS_OK,
    )
    if chosen.status != STATUS_OK:
        # Re-walk the attempts already collected to pick the best one.
        for a in attempts:
            if a.status == derivs_feed.STATUS_PARTIAL_OK:
                chosen = a
                break
        else:
            for a in attempts:
                if a.status == "degraded" and a.data:
                    chosen = a
                    break
    artifact = _wrap_artifact("derivatives", chosen, attempts)
    write_json(out_dir / "derivatives.json", artifact)
    return chosen


def snapshot_sentiment(out_dir: Path) -> FeedResult:
    chain = sentiment_feed.default_provider_chain()
    chosen, attempts = run_with_fallback(chain)
    artifact = _wrap_artifact("sentiment", chosen, attempts)
    write_json(out_dir / "sentiment.json", artifact)
    return chosen


def snapshot_key_levels(out_dir: Path, candle_results: dict) -> dict:
    h1 = candle_results.get("1h")
    d1 = candle_results.get("1d")
    closed_1h = candles_feed.closed_candles(h1) if h1 else []
    closed_1d = candles_feed.closed_candles(d1) if d1 else []
    levels = compute_key_levels(closed_1h, closed_1d)

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "kind": "key_levels",
        "source": "computed",
        "status": "failed" if (not closed_1h and not closed_1d) else (
            "degraded" if levels.get("degraded") else STATUS_OK
        ),
        "fetched_at": utc_now_iso(),
        "data": levels,
        "inputs": {
            "candles_1h_source": h1.source if h1 else None,
            "candles_1h_status": h1.status if h1 else None,
            "candles_1d_source": d1.source if d1 else None,
            "candles_1d_status": d1.status if d1 else None,
        },
    }
    write_json(out_dir / "key_levels.json", artifact)
    return artifact


def snapshot_source_health(out_dir: Path, parts: dict) -> dict:
    """Aggregate health across all snapshot artifacts.

    `parts` maps logical name → FeedResult or wrapped artifact.
    """
    sources = {}
    for name, p in parts.items():
        if isinstance(p, FeedResult):
            sources[name] = {
                "source": p.source,
                "status": p.status,
                "fetched_at": p.fetched_at,
                "error": p.error,
                "latency_ms": p.latency_ms,
            }
        elif isinstance(p, dict):
            sources[name] = {
                "source": p.get("source"),
                "status": p.get("status"),
                "fetched_at": p.get("fetched_at"),
                "error": p.get("error"),
            }
    overall = "ok"
    for v in sources.values():
        s = v.get("status")
        if s == "failed":
            overall = "failed"
            break
        if s == "degraded" and overall in ("ok", "partial_ok"):
            overall = "degraded"
        elif s in ("partial_ok", "stale") and overall == "ok":
            overall = "partial_ok"
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "kind": "source_health",
        "generated_at": utc_now_iso(),
        "overall": overall,
        "sources": sources,
        "freshness_budget_seconds": {
            # Sub-hour budgets give one full snapshot cadence (~30 min) of
            # grace on top of the candle period — the snapshotter runs at
            # :13/:43, so a 1m artifact written at :13 is at most ~30 min
            # old when the next run begins.
            "candles_1m":  45 * 60,    # 1m candle + ~half-hour cadence grace
            "candles_5m":  45 * 60,    # 5m candle + cadence grace
            "candles_15m": 60 * 60,    # 15m candle + cadence grace
            "candles_1h":  90 * 60,    # 1h candle + grace
            "candles_4h":   5 * 3600,
            "candles_1d":  26 * 3600,
            "derivatives":  30 * 60,
            "sentiment":   24 * 3600,
        },
    }
    write_json(out_dir / "source_health.json", artifact)
    return artifact


def run(out_dir: Path, intervals=DEFAULT_INTERVALS) -> dict:
    candles = snapshot_candles(out_dir, intervals=intervals)
    derivs = snapshot_derivatives(out_dir)
    senti = snapshot_sentiment(out_dir)
    levels = snapshot_key_levels(out_dir, candles)
    health_parts = {f"candles_{k}": v for k, v in candles.items()}
    health_parts["derivatives"] = derivs
    health_parts["sentiment"] = senti
    health_parts["key_levels"] = levels
    health = snapshot_source_health(out_dir, health_parts)
    return {
        "candles": {k: v.to_dict() for k, v in candles.items()},
        "derivatives": derivs.to_dict(),
        "sentiment": senti.to_dict(),
        "key_levels": levels,
        "source_health": health,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="public artifact dir")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS))
    args = ap.parse_args(argv)
    out = Path(args.out)
    intervals = tuple(s.strip() for s in args.intervals.split(",") if s.strip())
    summary = run(out, intervals=intervals)
    json.dump(
        {
            "ok": True,
            "out_dir": str(out),
            "overall": summary["source_health"]["overall"],
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
