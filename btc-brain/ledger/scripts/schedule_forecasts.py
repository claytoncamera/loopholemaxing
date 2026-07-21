"""
Scheduled forecast issuer (baseline shadow + optional edge-policy dual issuer).

Issues conservative, append-only shadow forecasts for BTCUSD.

Models
------
1. v0.1.0-baseline-shadow — SMA(24) control; horizons 1h/4h/12h/24h
2. v0.2.0-shadow-policy24 — edge-focused candidate:
   - horizons 12h + 24h only (fee-surviving band from live autopsy)
   - same SMA direction
   - *inverted* confidence: mild SMA divergence → higher prob (autopsy:
     high |rel| underperformed)
   - skips hour 20 UTC (toxic hour in autopsy; shadow filter)
   - live regime_at_issue from Phase 4 detector

Design constraints
------------------
- Append-only. Existing rows are never edited.
- Per (model_version, horizon, issued_bucket) duplicate prevention.
- No live ticker. Entry from most recent closed 1h candle.
- No incomplete candles.
- Shadow labelling only — never promoted by this script.
- No secrets.
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
)

# Regime detector (optional — falls back to unknown if import fails)
_REGIME_OK = False
try:
    _PHASE4 = Path(__file__).resolve().parents[2] / "models" / "phase4"
    if str(_PHASE4) not in sys.path:
        sys.path.insert(0, str(_PHASE4.parent.parent / "models"))
    # models/ on path → phase4.regime
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "models"))
    from phase4.regime import regime_at as _regime_at  # type: ignore  # noqa: E402
    _REGIME_OK = True
except Exception:  # noqa: BLE001
    _REGIME_OK = False

    def _regime_at(closes, **kwargs):  # type: ignore
        return ("unknown", "unknown")


ISSUER_VERSION = "scheduler-v0.2.0"

# ── Baseline model identity (tests pin these names) ──────────────────────────
MODEL_VERSION = "v0.1.0-baseline-shadow"
SIGNAL_VERSION = "shadow-v0.1.0"
CREATED_BY = "scheduled-issuer/baseline-shadow"

# ── Policy candidate (12h/24h edge path) ─────────────────────────────────────
POLICY_MODEL_VERSION = "v0.2.0-shadow-policy24"
POLICY_SIGNAL_VERSION = "shadow-policy24-v0.1.0"
POLICY_CREATED_BY = "scheduled-issuer/policy24"
POLICY_HORIZONS = ("12h", "24h")
POLICY_SKIP_HOURS_UTC = frozenset({20})

HORIZON_SPEC = {
    "1h":  {"delta": timedelta(hours=1),  "bucket_hours": 1},
    "4h":  {"delta": timedelta(hours=4),  "bucket_hours": 4},
    "12h": {"delta": timedelta(hours=12), "bucket_hours": 12},
    "24h": {"delta": timedelta(hours=24), "bucket_hours": 24},
}

PROB_FLOOR = 0.5005
PROB_CEIL = 0.55
MAX_SNAPSHOT_STALENESS = timedelta(hours=6)


def load_candles(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    candles = (raw.get("data") or {}).get("candles") or []
    return list(candles)


def latest_closed_candle(candles: list[dict], now: datetime) -> dict | None:
    now_ms = int(now.timestamp() * 1000)
    closed = [c for c in candles if int(c["close_time_ms"]) <= now_ms]
    if not closed:
        return None
    return max(closed, key=lambda c: int(c["close_time_ms"]))


def _sma_state(candles: list[dict], lookback: int = 24) -> tuple[str, float, float, str]:
    """Return (direction, rel, last, reason_core)."""
    closes = [float(c["close"]) for c in candles[-(lookback + 1):]]
    if len(closes) < 2:
        return "up", 0.0, closes[-1] if closes else 0.0, "insufficient-history"
    last = closes[-1]
    prior = closes[:-1]
    sma = sum(prior) / len(prior)
    direction = "up" if last >= sma else "down"
    rel = 0.0 if sma <= 0 else abs(last - sma) / sma
    reason = f"shadow:sma{lookback} last={last:.2f} sma={sma:.2f} rel={rel:.4f}"
    return direction, rel, last, reason


def baseline_direction_and_prob(candles: list[dict], lookback: int = 24) -> tuple[str, float, str]:
    """Original baseline: larger |rel| → higher prob (control model)."""
    direction, rel, _last, reason = _sma_state(candles, lookback=lookback)
    if reason == "insufficient-history":
        return "up", PROB_FLOOR, reason
    bump = min(rel, PROB_CEIL - PROB_FLOOR)
    prob = max(PROB_FLOOR, min(PROB_CEIL, PROB_FLOOR + bump))
    return direction, prob, reason


def policy24_direction_and_prob(candles: list[dict], lookback: int = 24) -> tuple[str, float, str]:
    """Edge policy: same direction, *inverted* confidence on |rel|.

    Autopsy 2026-07-21: low SMA divergence hit ~60%; high divergence ~48%.
    Mild rel gets more confidence; large extensions get floored.
    """
    direction, rel, _last, reason = _sma_state(candles, lookback=lookback)
    if reason == "insufficient-history":
        return "up", PROB_FLOOR, "policy24:" + reason
    # Invert: peak confidence near rel≈0.001–0.003, decay after 0.5%
    if rel <= 0.001:
        strength = 0.7
    elif rel <= 0.003:
        strength = 1.0
    elif rel <= 0.005:
        strength = 0.55
    elif rel <= 0.01:
        strength = 0.25
    else:
        strength = 0.05
    bump = strength * (PROB_CEIL - PROB_FLOOR)
    prob = max(PROB_FLOOR, min(PROB_CEIL, PROB_FLOOR + bump))
    return direction, prob, f"policy24:inv_conf|{reason}"


def detect_regime_label(candles: list[dict]) -> str:
    closes = [float(c["close"]) for c in candles]
    if len(closes) < 30:
        return "unknown"
    try:
        coarse, _fine = _regime_at(closes)
        if coarse in ("bull", "bear", "chop", "unknown"):
            return coarse
    except Exception:  # noqa: BLE001
        return "unknown"
    return "unknown"


def issued_bucket(now: datetime, bucket_hours: int) -> datetime:
    floored_hour = (now.hour // bucket_hours) * bucket_hours
    return now.replace(minute=0, second=0, microsecond=0, hour=floored_hour)


def existing_buckets(forecasts: Iterable[dict], model_version: str) -> set[tuple[str, str]]:
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


def build_row(
    horizon: str,
    issued: datetime,
    entry_price: float,
    direction: str,
    probability: float,
    reason: str,
    feature_uri: str,
    source_uri: str,
    *,
    model_version: str = MODEL_VERSION,
    signal_version: str = SIGNAL_VERSION,
    created_by: str = CREATED_BY,
    regime_at_issue: str = "unknown",
) -> dict:
    spec = HORIZON_SPEC[horizon]
    target = issued + spec["delta"]
    invalidation_dir = "up" if direction == "down" else "down"
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
        "model_version": model_version,
        "signal_version": signal_version,
        "regime_at_issue": regime_at_issue,
        "feature_snapshot_uri": feature_uri,
        "source_snapshot_uri": source_uri,
        "confidence_reason": reason,
        "invalidation": invalidation,
        "created_by": created_by,
        "status": "open",
    }


def _prepare(candles_path: Path, now: datetime) -> tuple[list[dict] | None, dict | None, list[dict]]:
    """Return (candles, last_closed, errors)."""
    errors: list[dict] = []
    if not candles_path.exists():
        errors.append({"reason": f"candles snapshot missing: {candles_path}"})
        return None, None, errors
    try:
        candles = load_candles(candles_path)
    except Exception as e:  # noqa: BLE001
        errors.append({"reason": f"candles snapshot unparseable: {e}"})
        return None, None, errors
    last_closed = latest_closed_candle(candles, now)
    if last_closed is None:
        errors.append({"reason": "no closed candle in snapshot"})
        return candles, None, errors
    last_close_time = datetime.fromtimestamp(
        int(last_closed["close_time_ms"]) / 1000, tz=timezone.utc
    )
    age = now - last_close_time
    if age > MAX_SNAPSHOT_STALENESS:
        errors.append({
            "reason": f"snapshot stale: latest closed candle is {age} old",
            "last_close_time": last_close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return candles, None, errors
    return candles, last_closed, errors


def run_model(
    ledger_root: Path,
    candles_path: Path,
    horizons: list[str],
    *,
    model_version: str,
    signal_version: str,
    created_by: str,
    signal_fn,
    now: datetime | None = None,
    dry_run: bool = False,
    feature_uri: str | None = None,
    source_uri: str | None = None,
    skip_hours_utc: frozenset[int] | None = None,
    closed_candles_for_signal: list[dict] | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    summary = {
        "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issuer_version": ISSUER_VERSION,
        "model_version": model_version,
        "issued": [],
        "skipped_duplicate": [],
        "skipped_filter": [],
        "errors": [],
    }

    candles, last_closed, prep_errors = _prepare(candles_path, now)
    summary["errors"].extend(prep_errors)
    if candles is None or last_closed is None:
        return summary

    # Use only closed candles for signal + regime
    now_ms = int(now.timestamp() * 1000)
    closed = [c for c in candles if int(c["close_time_ms"]) <= now_ms]
    closed.sort(key=lambda c: int(c["close_time_ms"]))
    if closed_candles_for_signal is not None:
        closed = closed_candles_for_signal

    entry_price = float(last_closed["close"])
    direction, probability, reason = signal_fn(closed)
    regime = detect_regime_label(closed)

    feature_uri_ = feature_uri or "data/public/candles_1h.json"
    source_uri_ = source_uri or "data/public/candles_1h.json"

    ledger = Ledger.at(ledger_root)
    existing = existing_buckets(ledger.iter_forecasts(), model_version)

    if skip_hours_utc and now.hour in skip_hours_utc:
        summary["skipped_filter"].append({
            "reason": f"skip_hour_utc={now.hour}",
            "model_version": model_version,
        })
        return summary

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
            model_version=model_version,
            signal_version=signal_version,
            created_by=created_by,
            regime_at_issue=regime,
        )
        if dry_run:
            summary["issued"].append({"dry_run": True, **row})
            continue
        try:
            ledger.append_forecast(row)
        except Exception as e:  # noqa: BLE001
            summary["errors"].append({"horizon": h, "reason": str(e)})
            continue
        existing.add((h, bucket_iso))
        summary["issued"].append(row)

    return summary


def run(
    ledger_root: Path,
    candles_path: Path,
    horizons: list[str],
    now: datetime | None = None,
    dry_run: bool = False,
    feature_uri: str | None = None,
    source_uri: str | None = None,
) -> dict:
    """Baseline-only issuer — preserves prior API for unit tests."""
    return run_model(
        ledger_root,
        candles_path,
        horizons,
        model_version=MODEL_VERSION,
        signal_version=SIGNAL_VERSION,
        created_by=CREATED_BY,
        signal_fn=baseline_direction_and_prob,
        now=now,
        dry_run=dry_run,
        feature_uri=feature_uri,
        source_uri=source_uri,
    )


def run_all(
    ledger_root: Path,
    candles_path: Path,
    baseline_horizons: list[str],
    now: datetime | None = None,
    dry_run: bool = False,
    feature_uri: str | None = None,
    source_uri: str | None = None,
    enable_policy24: bool = True,
) -> dict:
    """Dual issuer: baseline control + policy24 edge candidate."""
    base = run(
        ledger_root, candles_path, baseline_horizons,
        now=now, dry_run=dry_run,
        feature_uri=feature_uri, source_uri=source_uri,
    )
    out = {
        "issuer_version": ISSUER_VERSION,
        "models": {"baseline": base},
        "issued_total": len(base.get("issued") or []),
        "errors": list(base.get("errors") or []),
    }
    if enable_policy24:
        pol = run_model(
            ledger_root,
            candles_path,
            list(POLICY_HORIZONS),
            model_version=POLICY_MODEL_VERSION,
            signal_version=POLICY_SIGNAL_VERSION,
            created_by=POLICY_CREATED_BY,
            signal_fn=policy24_direction_and_prob,
            now=now,
            dry_run=dry_run,
            feature_uri=feature_uri,
            source_uri=source_uri,
            skip_hours_utc=POLICY_SKIP_HOURS_UTC,
        )
        out["models"]["policy24"] = pol
        out["issued_total"] += len(pol.get("issued") or [])
        out["errors"].extend(pol.get("errors") or [])
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--candles", required=True,
                    help="path to public candles_1h.json snapshot")
    ap.add_argument("--horizons", default="1h,4h,12h,24h",
                    help="comma-separated baseline horizons")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--feature-snapshot-uri", dest="feature_uri", default=None)
    ap.add_argument("--source-snapshot-uri", dest="source_uri", default=None)
    ap.add_argument(
        "--mode",
        choices=["baseline", "dual"],
        default="dual",
        help="baseline=control only; dual=baseline+policy24 (default)",
    )
    ap.add_argument("--no-policy24", action="store_true",
                    help="disable policy24 even in dual mode")
    args = ap.parse_args(argv)
    horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]

    if args.mode == "baseline":
        summary = run(
            ledger_root=Path(args.root),
            candles_path=Path(args.candles),
            horizons=horizons,
            dry_run=args.dry_run,
            feature_uri=args.feature_uri,
            source_uri=args.source_uri,
        )
    else:
        summary = run_all(
            ledger_root=Path(args.root),
            candles_path=Path(args.candles),
            baseline_horizons=horizons,
            dry_run=args.dry_run,
            feature_uri=args.feature_uri,
            source_uri=args.source_uri,
            enable_policy24=not args.no_policy24,
        )

    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    if args.mode == "baseline":
        if summary["errors"] and not summary["issued"] and not summary["skipped_duplicate"]:
            return 1
        return 0

    # dual mode
    models = summary.get("models") or {}
    any_progress = summary.get("issued_total", 0) > 0
    any_skip = False
    for m in models.values():
        if m.get("skipped_duplicate") or m.get("skipped_filter"):
            any_skip = True
    if summary.get("errors") and not any_progress and not any_skip:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
