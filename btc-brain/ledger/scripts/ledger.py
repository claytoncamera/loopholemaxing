"""
Append-only forecast ledger primitives.

Two JSONL files:
  - forecasts.jsonl     immutable forecast events
  - resolutions.jsonl   immutable resolution events (one per forecast_id)

We never edit a line. Corrections are new events.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

LEDGER_VERSION = "1"

# ── Allowed enums ────────────────────────────────────────────────────────────
HORIZONS = {"1h", "4h", "1d", "7d", "30d"}
DIRECTIONS = {"up", "down"}
REGIMES = {"bull", "bear", "chop", "unknown"}
FORECAST_STATUSES = {"open", "resolved", "voided", "superseded"}
RESOLUTION_STATUSES = {"resolved", "voided"}

# Required forecast fields, in canonical order.
FORECAST_FIELDS = (
    "forecast_id",
    "issued_at",
    "asset",
    "horizon",
    "target_time",
    "target_rule",
    "direction",
    "probability",
    "entry_price",
    "model_version",
    "signal_version",
    "regime_at_issue",
    "feature_snapshot_uri",
    "source_snapshot_uri",
    "confidence_reason",
    "invalidation",
    "created_by",
    "status",
)

RESOLUTION_FIELDS = (
    "forecast_id",
    "resolved_at",
    "actual_close",
    "actual_return",
    "direction_correct",
    "brier_component",
    "logloss_component",
    "status",
    "resolver_version",
    "candle_open_time",
    "candle_close_time",
    "price_source",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_forecast_id() -> str:
    return str(uuid.uuid4())


# ── Validation ───────────────────────────────────────────────────────────────
class LedgerError(ValueError):
    pass


def validate_forecast(row: dict) -> None:
    missing = [f for f in FORECAST_FIELDS if f not in row]
    if missing:
        raise LedgerError(f"forecast missing fields: {missing}")
    if row["horizon"] not in HORIZONS:
        raise LedgerError(f"bad horizon: {row['horizon']}")
    if row["direction"] not in DIRECTIONS:
        raise LedgerError(f"bad direction: {row['direction']}")
    if row["regime_at_issue"] not in REGIMES:
        raise LedgerError(f"bad regime: {row['regime_at_issue']}")
    if row["status"] not in FORECAST_STATUSES:
        raise LedgerError(f"bad status: {row['status']}")
    p = row["probability"]
    if not (isinstance(p, (int, float)) and 0.0 < p < 1.0):
        raise LedgerError(f"probability must be in (0,1): {p}")
    if not isinstance(row["entry_price"], (int, float)) or row["entry_price"] <= 0:
        raise LedgerError("entry_price must be positive number")
    # Time sanity.
    issued = parse_iso_utc(row["issued_at"])
    target = parse_iso_utc(row["target_time"])
    if target <= issued:
        raise LedgerError("target_time must be strictly after issued_at")


def validate_resolution(row: dict) -> None:
    missing = [f for f in RESOLUTION_FIELDS if f not in row]
    if missing:
        raise LedgerError(f"resolution missing fields: {missing}")
    if row["status"] not in RESOLUTION_STATUSES:
        raise LedgerError(f"bad resolution status: {row['status']}")
    if not isinstance(row["actual_close"], (int, float)) or row["actual_close"] <= 0:
        raise LedgerError("actual_close must be positive number")
    if not isinstance(row["direction_correct"], bool):
        raise LedgerError("direction_correct must be boolean")


# ── Append-only IO ───────────────────────────────────────────────────────────
def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            yield json.loads(ln)


@dataclass
class Ledger:
    """Thin wrapper over two JSONL paths. Stateless beyond paths."""

    forecasts_path: Path
    resolutions_path: Path

    @classmethod
    def at(cls, root: str | os.PathLike) -> "Ledger":
        root = Path(root)
        return cls(root / "forecasts.jsonl", root / "resolutions.jsonl")

    # --- writes -----------------------------------------------------------
    def append_forecast(self, row: dict) -> dict:
        # Defensive: never let a caller sneak in resolution fields here.
        for k in ("resolved_at", "actual_close", "actual_return",
                  "direction_correct", "brier_component", "logloss_component"):
            if k in row:
                raise LedgerError(
                    f"forecast row may not carry resolution field {k!r}; "
                    "resolutions live in resolutions.jsonl")
        validate_forecast(row)
        # Refuse duplicate forecast_id (append-only, but not duplicate-allowed).
        if any(f["forecast_id"] == row["forecast_id"] for f in self.iter_forecasts()):
            raise LedgerError(f"forecast_id already exists: {row['forecast_id']}")
        _append_jsonl(self.forecasts_path, row)
        return row

    def append_resolution(self, row: dict) -> dict:
        validate_resolution(row)
        # Refuse double resolution.
        for r in self.iter_resolutions():
            if r["forecast_id"] == row["forecast_id"]:
                raise LedgerError(
                    f"forecast already resolved: {row['forecast_id']}")
        # Refuse resolution for unknown forecast.
        if not any(f["forecast_id"] == row["forecast_id"]
                   for f in self.iter_forecasts()):
            raise LedgerError(
                f"resolution references unknown forecast_id: {row['forecast_id']}")
        _append_jsonl(self.resolutions_path, row)
        return row

    # --- reads ------------------------------------------------------------
    def iter_forecasts(self) -> Iterator[dict]:
        return _read_jsonl(self.forecasts_path)

    def iter_resolutions(self) -> Iterator[dict]:
        return _read_jsonl(self.resolutions_path)

    def open_forecasts(self, now: datetime | None = None) -> list[dict]:
        """Forecasts whose target_time is in the past and not yet resolved."""
        now = now or datetime.now(timezone.utc)
        resolved_ids = {r["forecast_id"] for r in self.iter_resolutions()}
        out = []
        for f in self.iter_forecasts():
            if f["forecast_id"] in resolved_ids:
                continue
            if f.get("status") == "superseded":
                continue
            if parse_iso_utc(f["target_time"]) <= now:
                out.append(f)
        return out

    def joined(self) -> list[dict]:
        """List of {forecast: ..., resolution: ... | None} for every forecast."""
        res_by_id = {r["forecast_id"]: r for r in self.iter_resolutions()}
        rows = []
        for f in self.iter_forecasts():
            rows.append({"forecast": f, "resolution": res_by_id.get(f["forecast_id"])})
        return rows


# ── Math helpers ─────────────────────────────────────────────────────────────
import math


def brier(probability_for_direction: float, outcome: int) -> float:
    """Brier score component for a single forecast.

    `probability_for_direction` is the probability that the forecasted
    direction is correct. `outcome` is 1 if it was correct, 0 otherwise.
    """
    return (probability_for_direction - outcome) ** 2


def logloss(probability_for_direction: float, outcome: int) -> float:
    eps = 1e-6
    p = min(max(probability_for_direction, eps), 1 - eps)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))
