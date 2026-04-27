"""
Shadow-mode forecast row builder.

Produces forecast rows compatible with the Phase 1 ledger schema, so they
can be appended to `forecasts.jsonl` and resolved by the existing resolver.
The Phase 1 metric job already segments by `model_version`, so prefixing
the version with `shadow-` keeps these rows out of any future "headline
accuracy" computation that filters to non-shadow models.

Important constraints (Phase 0/1/2/3 invariants):
  * Never overwrite an existing forecast row.
  * Never resolve using future data — that's the resolver's job, and it
    only uses closed candles.
  * Never modify public UI state. This module is library-only.
  * Probability is the probability of `direction` (always `up` if p>=0.5,
    `down` otherwise — we flip if needed and use `1-p`).

Output shape — see `btc-brain/ledger/SCHEMA.md`.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional


HORIZON_DELTA = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# Map our model horizon strings to the ledger's allowed horizon strings.
LEDGER_HORIZON = {
    "1h": "1h",
    "4h": "4h",
    "12h": "1d",   # ledger does not allow 12h; we shadow-resolve at 1d.
    "24h": "1d",
}


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_shadow_forecast_row(
    *,
    model_id: str,                       # e.g. shadow-logistic-1h-v0.1.0
    horizon: str,                        # 1h|4h|12h|24h
    p_up: float,                         # P(close[t+H] > close[t])
    entry_price: float,
    issued_at: Optional[datetime] = None,
    regime: str = "unknown",
    feature_snapshot_uri: str = "snapshots/none.json",
    source_snapshot_uri: str = "snapshots/none.json",
    confidence_reason: str = "shadow forecast (not promoted)",
    invalidation: str = "shadow only — not actionable",
    signal_version: str = "shadow-v0.1.0",
) -> dict:
    """Build an append-ready ledger row for a shadow forecast."""
    if not model_id.startswith("shadow-"):
        raise ValueError("model_id must start with 'shadow-' in Phase 3")
    if horizon not in HORIZON_DELTA:
        raise ValueError(f"unknown horizon: {horizon}")
    if not (0.0 < p_up < 1.0):
        # clamp away from singularities — keep ledger validation happy
        p_up = max(min(p_up, 1 - 1e-4), 1e-4)
    issued = issued_at or datetime.now(timezone.utc)
    target = issued + HORIZON_DELTA[horizon]
    if p_up >= 0.5:
        direction = "up"
        probability = p_up
    else:
        direction = "down"
        probability = 1.0 - p_up
    return {
        "forecast_id": str(uuid.uuid4()),
        "issued_at": _utc(issued),
        "asset": "BTCUSD",
        "horizon": LEDGER_HORIZON[horizon],
        "target_time": _utc(target),
        "target_rule": "close_above_entry" if direction == "up" else "close_below_entry",
        "direction": direction,
        "probability": probability,
        "entry_price": float(entry_price),
        "model_version": model_id,
        "signal_version": signal_version,
        "regime_at_issue": regime if regime in ("bull", "bear", "chop", "unknown") else "unknown",
        "feature_snapshot_uri": feature_snapshot_uri,
        "source_snapshot_uri": source_snapshot_uri,
        "confidence_reason": confidence_reason,
        "invalidation": invalidation,
        "created_by": "phase3-shadow",
        "status": "open",
    }
