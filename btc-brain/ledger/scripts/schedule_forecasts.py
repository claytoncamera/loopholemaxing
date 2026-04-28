"""
Scheduled forecast issuer (baseline / shadow).

Issues conservative, append-only baseline forecasts for BTCUSD across the
horizons 1h, 4h, 12h, 24h. This is a *shadow* model — it is never promoted
and the public UI must remain truth-gated until enough resolutions exist
for accuracy.json to mark a bucket as display_ready.

Design constraints honored here
-------------------------------
- Append-only. Existing rows are never edited.
- Per (model_version, horizon, issued_bucket) duplicate prevention. Re-running
  the issuer in the same hour bucket is a no-op for that bucket.
- No live ticker. The entry price comes from the most recent **closed** 1h
  candle in btc-brain/data/public/candles_1h.json. We refuse to issue if the
  snapshot is missing or stale.
- No incomplete candles. We use a candle as "closed" only when its close_time
  is strictly in the past relative to `now`.
- Calibrated-neutral probabilities. The shadow probability is clamped into a
  conservative band [0.50, 0.55] so we never publish strong confidence.
- Clear baseline/shadow labelling. model_version contains "shadow"; the row
  is not produced by a promoted model.
- No secrets. Uses only the public artifacts already on disk.

Usage
-----
    python schedule_forecasts.py \
        --root btc-brain/ledger/data \
        --candles btc-brain/data/public/candles_1h.json \
        [--horizons 1h,4h,12h,24h] \
        [--dry-run]

Exit codes
    0 — at least one forecast issued, or all eligible buckets already had
        a forecast (idempotent success).
    1 — input data unusable (missing snapshot, stale, no closed candle).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))
from ledger import (  # noqa: E402
    Ledger,
    new_forecast_id,
    parse_iso_utc,
    utc_now_iso,
)

ISSUER_VERSION = "scheduler-v0.1.0"
MODEL_VERSION = "v0.1.0-baseline-shadow"
SIGNAL_VERSION = "shadow-v0.1.0"
CREATED_BY = "scheduled-issuer/baseline-shadow"

# Horizons we issue on every run, mapped to a timedelta and a bucket grid.
# `bucket_hours` is the spacing between distinct issuance buckets for a
# horizon. We bucket by horizon length so that, e.g., 4h forecasts are only
# issued once per 4h grid square — no duplicates from re-running the
# scheduler at :07 and :37.
HORIZON_SPEC = {
    "1h":  {"delta": timedelta(hours=1),  "bucket_hours": 1},
    "4h":  {"delta": timedelta(hours=4),  "bucket_hours": 4},
    "12h": {"delta": timedelta(hours=12), "bucket_hours": 12},
    "24h": {"delta": timedelta(hours=24), "bucket_hours": 24},
}

# Conservative probability band. We never publish anything stronger than
# 0.55 from this baseline. 0.50 is excluded by the schema, so we clamp to
# (0.50, 0.55].
PROB_FLOOR = 0.5005
PROB_CEIL = 0.55

# Snapshot freshness: refuse to issue if the most recent closed 1h candle
# is older than this. 6 hours is conservative; the snapshot workflow runs
# every 30 minutes so this only trips during a real outage.
MAX_SNAPSHOT_STALENESS = timedelta(hours=6)


# ── Snapshot helpers ─────────────────────────────────────────────────────────
def load_candles(path: Path) -> list[dict]:
    """Return the candle list from a Phase 2 candles_1h.json artifact."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    candles = (raw.get("data") or {}).get("candles") or []
    return list(candles)


def latest_closed_candle(candles: list[dict], now: datetime) -> dict | None:
    """Return the most recent candle whose close_time is strictly past `now`.

    Defends against the in-progress candle showing up at the tail.
    """
    now_ms = int(now.timestamp() * 1000)
    closed = [c for c in candles if int(c["close_time_ms"]) <= now_ms]
    if not closed:
        return None
    return max(closed, key=lambda c: int(c["close_time_ms"]))


# ── Signal logic (deterministic, conservative) ───────────────────────────────
def baseline_direction_and_prob(candles: list[dict], lookback: int = 24) -> tuple[str, float, str]:
    """Compute a conservative shadow signal from closed 1h candles.

    Strategy: compare the latest *closed* candle close to the simple moving
    average of the prior `lookback` closes. If above SMA → `up`, else `down`.
    Probability is mapped to a tiny band above the floor so we never publish
    a confident claim from a baseline model.
    """
    closes = [float(c["close"]) for c in candles[-(lookback + 1):]]
    if len(closes) < 2:
        # Not enough history — neutral up at the floor.
        return "up", PROB_FLOOR, "insufficient-history"
    last = closes[-1]
    prior = closes[:-1]
    sma = sum(prior) / len(prior)
    direction = "up" if last >= sma else "down"
    # Map distance from SMA to a conservative probability bump within the
    # [floor, ceil] band. The bigger the divergence, the closer to ceil —
    # but never above ceil.
    if sma <= 0:
        rel = 0.0
    else:
        rel = abs(last - sma) / sma
    # 1% divergence → +0.01 over floor, capped at PROB_CEIL.
    bump = min(rel, PROB_CEIL - PROB_FLOOR)
    prob = max(PROB_FLOOR, min(PROB_CEIL, PROB_FLOOR + bump))
    reason = f"shadow:sma{lookback} last={last:.2f} sma={sma:.2f} rel={rel:.4f}"
    return direction, prob, reason


# ── Bucketing & duplicate prevention ─────────────────────────────────────────
def issued_bucket(now: datetime, bucket_hours: int) -> datetime:
    """Floor `now` to the start of the issuance bucket."""
    floored_hour = (now.hour // bucket_hours) * bucket_hours
    return now.replace(minute=0, second=0, microsecond=0, hour=floored_hour)


def existing_buckets(forecasts: Iterable[dict], model_version: str) -> set[tuple[str, str]]:
    """Set of (horizon, issued_bucket_iso) already present for this model.

    issued_at on existing rows is the original issuance time — which by
    construction was floored to the bucket grid. So we floor by horizon
    again for safety.
    """
    out: set[tuple[str, str]] = set()
    for f in forecasts:
        if f.get("model_version") != model_version:
            continue
        h = f.get("horizon")
        if h not in HORIZON_SPEC:
            continue
        try:
            issued = parse_iso_utc(f["issued_at"])
        except Exception:
            continue
        bucket = issued_bucket(issued, HORIZON_SPEC[h]["bucket_hours"])
        out.add((h, bucket.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return out


# ── Row builder ──────────────────────────────────────────────────────────────
def build_row(
    horizon: str,
    issued: datetime,
    entry_price: float,
    direction: str,
    probability: float,
    reason: str,
    feature_uri: str,
    source_uri: str,
) -> dict:
    spec = HORIZON_SPEC[horizon]
    target = issued + spec["delta"]
    invalidation_dir = "up" if direction == "down" else "down"
    # An invalidation that triggers on a 5% adverse move is intentionally
    # loose — we want very few voids from this baseline.
    pct = 0.05
    if invalidation_dir == "up":
        invalid_level = round(entry_price * (1 + pct), 2)
        invalidation = f"BTC > {invalid_level} before target"
    else:
        invalid_level = round(entry_price * (1 - pct), 2)
        invalidation = f"BTC < {invalid_level} before target"
    return {
        "forecast_id": new_forecast_id(),
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asset": "BTCUSD",
        "horizon": horizon,
        "target_time": target.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_rule": "close_above_entry" if direction == "up" else "close_below_entry",
        "direction": direction,
        "probability": probability,
        "entry_price": entry_price,
        "model_version": MODEL_VERSION,
        "signal_version": SIGNAL_VERSION,
        "regime_at_issue": "unknown",
        "feature_snapshot_uri": feature_uri,
        "source_snapshot_uri": source_uri,
        "confidence_reason": reason,
        "invalidation": invalidation,
        "created_by": CREATED_BY,
        "status": "open",
    }


# ── Main runner ──────────────────────────────────────────────────────────────
def run(
    ledger_root: Path,
    candles_path: Path,
    horizons: list[str],
    now: datetime | None = None,
    dry_run: bool = False,
    feature_uri: str | None = None,
    source_uri: str | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    summary = {
        "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issuer_version": ISSUER_VERSION,
        "model_version": MODEL_VERSION,
        "issued": [],
        "skipped_duplicate": [],
        "errors": [],
    }

    if not candles_path.exists():
        summary["errors"].append({"reason": f"candles snapshot missing: {candles_path}"})
        return summary

    try:
        candles = load_candles(candles_path)
    except Exception as e:  # noqa: BLE001
        summary["errors"].append({"reason": f"candles snapshot unparseable: {e}"})
        return summary

    last_closed = latest_closed_candle(candles, now)
    if last_closed is None:
        summary["errors"].append({"reason": "no closed candle in snapshot"})
        return summary

    last_close_time = datetime.fromtimestamp(int(last_closed["close_time_ms"]) / 1000, tz=timezone.utc)
    age = now - last_close_time
    if age > MAX_SNAPSHOT_STALENESS:
        summary["errors"].append({
            "reason": f"snapshot stale: latest closed candle is {age} old",
            "last_close_time": last_close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return summary

    entry_price = float(last_closed["close"])
    direction, probability, reason = baseline_direction_and_prob(candles)

    feature_uri_ = feature_uri or "data/public/candles_1h.json"
    source_uri_ = source_uri or "data/public/candles_1h.json"

    ledger = Ledger.at(ledger_root)
    existing = existing_buckets(ledger.iter_forecasts(), MODEL_VERSION)

    for h in horizons:
        if h not in HORIZON_SPEC:
            summary["errors"].append({"horizon": h, "reason": "unknown horizon"})
            continue
        bucket = issued_bucket(now, HORIZON_SPEC[h]["bucket_hours"])
        bucket_iso = bucket.strftime("%Y-%m-%dT%H:%M:%SZ")
        if (h, bucket_iso) in existing:
            summary["skipped_duplicate"].append({
                "horizon": h, "issued_bucket": bucket_iso,
            })
            continue
        row = build_row(
            horizon=h,
            issued=bucket,
            entry_price=entry_price,
            direction=direction,
            probability=probability,
            reason=reason,
            feature_uri=feature_uri_,
            source_uri=source_uri_,
        )
        if dry_run:
            summary["issued"].append({"dry_run": True, **row})
            continue
        try:
            ledger.append_forecast(row)
        except Exception as e:  # noqa: BLE001
            summary["errors"].append({"horizon": h, "reason": str(e)})
            continue
        # Track in-memory so a second horizon at the same bucket doesn't dup.
        existing.add((h, bucket_iso))
        summary["issued"].append(row)

    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--candles", required=True,
                    help="path to public candles_1h.json snapshot")
    ap.add_argument("--horizons", default="1h,4h,12h,24h",
                    help="comma-separated horizons to issue")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--feature-snapshot-uri", dest="feature_uri", default=None)
    ap.add_argument("--source-snapshot-uri", dest="source_uri", default=None)
    args = ap.parse_args(argv)
    horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]
    summary = run(
        ledger_root=Path(args.root),
        candles_path=Path(args.candles),
        horizons=horizons,
        dry_run=args.dry_run,
        feature_uri=args.feature_uri,
        source_uri=args.source_uri,
    )
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    # Errors are not fatal if at least one forecast was issued or all were
    # skipped as duplicates; but a totally-failed run (errors and zero
    # issues, zero skips) returns 1.
    if summary["errors"] and not summary["issued"] and not summary["skipped_duplicate"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
