"""
Scheduled forecast issuer (baseline shadow + guard24 dual issuer, v0.3).

Issues conservative, append-only shadow forecasts for BTCUSD.

Models
------
1. v0.1.0-baseline-shadow — SMA(24) control; horizons 1h/4h/12h/24h.
   Signal logic is FROZEN (it is the control). Only issuance cadence
   changed in v0.3 (12h/24h accrue hourly — see HORIZON_SPEC).
2. v0.3.0-shadow-guard24 — guarded candidate (audit 2026-08-10):
   - horizons 12h + 24h only
   - rel = (last - sma24)/sma24; |rel| > 1% → ABSTAIN (Q4 rel hit 44-48%)
   - up if last >= sma24; down requires last < sma24 AND last < sma72
     (down calls were anti-predictive without confirmation)
   - weekend guard: abstain on down calls issued Sat/Sun UTC
     (Saturday down-calls hit 28.2%)
   - probability 0.55 when |rel| < 0.5% (that slice hit 67.3%, n=52,
     Wilson LB 53.8%), else 0.52
3. v0.2.0-shadow-policy24 — KILLED 2026-08-10 (its own 24h record met the
   master-plan kill criteria: n=62, hit 43.5%, maker -21.8bps). The code
   stays importable for historical reproducibility and the frozen dual
   tests, but it is no longer issued by the CLI/workflow path.

v0.3 honesty upgrades
---------------------
- No backdating: the CLI skips a bucket when the run starts more than
  MAX_BACKDATE (15 min) after the bucket opened. A missing bucket is
  honest; a backdated one corrupts horizon length + hour-of-day analysis
  (64/128 24h and 112/253 12h rows were backdated >= 1h pre-v0.3).
- Every new row records `issued_at_actual` (real wall-clock) next to the
  bucket-floored `issued_at` (additive schema).
- Every new row records `entry_source` (winning provider from the candles
  snapshot metadata: top-level `source` key) and `entry_symbol` when
  derivable, so the resolver can resolve against the SAME venue.

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


ISSUER_VERSION = "scheduler-v0.3.0"

# ── Baseline model identity (tests pin these names) ──────────────────────────
MODEL_VERSION = "v0.1.0-baseline-shadow"
SIGNAL_VERSION = "shadow-v0.1.0"
CREATED_BY = "scheduled-issuer/baseline-shadow"

# ── Policy candidate (12h/24h edge path) — KILLED 2026-08-10 ─────────────────
# Kept importable for historical reproducibility + frozen dual tests only.
# Not issued by the CLI/workflow path any more (kill criteria met: n=62,
# hit 43.5%, maker −21.8bps on its own 24h record).
POLICY_MODEL_VERSION = "v0.2.0-shadow-policy24"
POLICY_SIGNAL_VERSION = "shadow-policy24-v0.1.0"
POLICY_CREATED_BY = "scheduled-issuer/policy24"
POLICY_HORIZONS = ("12h", "24h")
POLICY_SKIP_HOURS_UTC = frozenset({20})

# ── Guard candidate (12h/24h guarded path, v0.3) ─────────────────────────────
GUARD_MODEL_VERSION = "v0.3.0-shadow-guard24"
GUARD_SIGNAL_VERSION = "shadow-guard24-v0.1.0"
GUARD_CREATED_BY = "scheduled-issuer/guard24"
GUARD_HORIZONS = ("12h", "24h")
GUARD_REL_ABSTAIN = 0.01     # |rel| above this → abstain (Q4 rel hit 44-48%)
GUARD_HIGH_BAND = 0.005      # |rel| below this → high-conviction band
GUARD_PROB_HIGH = 0.55       # rel<0.5% slice hit 67.3% (n=52, Wilson LB 53.8%)
GUARD_PROB_LOW = 0.52
GUARD_SMA_FAST = 24
GUARD_SMA_SLOW = 72          # down needs last < sma72 confirmation

# v0.3 overlapping accrual: 12h/24h issue EVERY HOUR (bucket_hours=1) so the
# flagship horizons accrue n hourly instead of 1/day. The 00 UTC subseries
# remains the clean non-overlapping control (filter issued_at hour == 0).
# 1h/4h grids unchanged. Baseline signal logic is untouched — cadence only.
HORIZON_SPEC = {
    "1h":  {"delta": timedelta(hours=1),  "bucket_hours": 1},
    "4h":  {"delta": timedelta(hours=4),  "bucket_hours": 4},
    "12h": {"delta": timedelta(hours=12), "bucket_hours": 1},
    "24h": {"delta": timedelta(hours=24), "bucket_hours": 1},
}

PROB_FLOOR = 0.5005
PROB_CEIL = 0.55
MAX_SNAPSHOT_STALENESS = timedelta(hours=6)

# No-backdating guard (enforced by the CLI path; see main()). A run that
# starts more than this long after a bucket opened must NOT fill that bucket:
# entry/signal come from run time, so a backdated issued_at lies about the
# horizon. A missing bucket is honest.
MAX_BACKDATE_DEFAULT = timedelta(minutes=15)

# entry_source → venue symbol used at entry (derivable venues only).
ENTRY_SYMBOLS = {
    "binance": "BTCUSDT",
    "coinbase": "BTC-USD",
    "kraken": "XBTUSD",
}


def load_candles(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    candles = (raw.get("data") or {}).get("candles") or []
    return list(candles)


def load_snapshot(path: Path) -> tuple[list[dict], dict]:
    """Return (candles, meta) from a candles_1h.json snapshot.

    meta["entry_source"] is the snapshot's top-level `source` key — the
    provider that actually won the fetch (e.g. "coinbase" when Binance is
    geo-blocked from CI with HTTP 451). Snapshots without the key (older
    fixtures) yield "unknown". meta["entry_symbol"] is present only when the
    venue symbol is derivable.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    candles = (raw.get("data") or {}).get("candles") or []
    src = raw.get("source")
    entry_source = str(src).strip().lower() if src else "unknown"
    meta = {"entry_source": entry_source}
    symbol = ENTRY_SYMBOLS.get(entry_source)
    if symbol:
        meta["entry_symbol"] = symbol
    return list(candles), meta


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


def guard24_direction_and_prob(
    candles: list[dict], now: datetime
) -> tuple[str, float | None, str]:
    """v0.3.0-shadow-guard24 signal. Returns ("abstain", None, reason) often.

    Rules (audit 2026-08-10, ~500 resolved rows):
      - rel = (last - sma24) / sma24 (SIGNED; sma24 = mean of prior 24 closes)
      - |rel| > 1%             → abstain (extended moves hit 44-48%)
      - last >= sma24          → up
      - last <  sma24          → down ONLY if last < sma72 too (sma72 = mean
                                 of prior 72 closes); else abstain
      - down call on Sat/Sun UTC issue time → abstain (weekend down 28.2%)
      - probability 0.55 when |rel| < 0.5% (67.3% slice), else 0.52
    """
    closes = [float(c["close"]) for c in candles]
    need = GUARD_SMA_SLOW + 1  # prior 72 closes + the last close
    if len(closes) < need:
        return (
            "abstain", None,
            f"guard24:abstain=insufficient-history|have={len(closes)}|need={need}",
        )
    last = closes[-1]
    sma24 = sum(closes[-(GUARD_SMA_FAST + 1):-1]) / GUARD_SMA_FAST
    sma72 = sum(closes[-(GUARD_SMA_SLOW + 1):-1]) / GUARD_SMA_SLOW
    if sma24 <= 0:
        return "abstain", None, "guard24:abstain=degenerate-sma24"
    rel = (last - sma24) / sma24
    core = f"rel={rel:.4f}|sma24={sma24:.2f}|sma72={sma72:.2f}"
    if abs(rel) > GUARD_REL_ABSTAIN:
        return "abstain", None, f"guard24:abstain=rel-extreme|{core}"
    if last >= sma24:
        direction = "up"
    else:
        if not (last < sma72):
            return "abstain", None, f"guard24:abstain=no-sma72-confirm|{core}"
        if now.weekday() >= 5:  # 5=Saturday, 6=Sunday (UTC issue time)
            return "abstain", None, f"guard24:abstain=weekend-down|{core}"
        direction = "down"
    band = "high" if abs(rel) < GUARD_HIGH_BAND else "low"
    prob = GUARD_PROB_HIGH if band == "high" else GUARD_PROB_LOW
    return direction, prob, f"guard24:{core}|band={band}"


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
    issued_at_actual: str | None = None,
    entry_source: str | None = None,
    entry_symbol: str | None = None,
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
    row = {
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
    # v0.3 additive provenance fields (metrics parses rows by known keys, so
    # extra keys are safe; validate_forecast only checks required fields).
    if issued_at_actual is not None:
        row["issued_at_actual"] = issued_at_actual
    if entry_source is not None:
        row["entry_source"] = entry_source
    if entry_symbol is not None:
        row["entry_symbol"] = entry_symbol
    return row


def _prepare(
    candles_path: Path, now: datetime
) -> tuple[list[dict] | None, dict | None, list[dict], dict]:
    """Return (candles, last_closed, errors, snapshot_meta)."""
    errors: list[dict] = []
    meta: dict = {"entry_source": "unknown"}
    if not candles_path.exists():
        errors.append({"reason": f"candles snapshot missing: {candles_path}"})
        return None, None, errors, meta
    try:
        candles, meta = load_snapshot(candles_path)
    except Exception as e:  # noqa: BLE001
        errors.append({"reason": f"candles snapshot unparseable: {e}"})
        return None, None, errors, meta
    last_closed = latest_closed_candle(candles, now)
    if last_closed is None:
        errors.append({"reason": "no closed candle in snapshot"})
        return candles, None, errors, meta
    last_close_time = datetime.fromtimestamp(
        int(last_closed["close_time_ms"]) / 1000, tz=timezone.utc
    )
    age = now - last_close_time
    if age > MAX_SNAPSHOT_STALENESS:
        errors.append({
            "reason": f"snapshot stale: latest closed candle is {age} old",
            "last_close_time": last_close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return candles, None, errors, meta
    return candles, last_closed, errors, meta


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
    max_backdate: timedelta | None = None,
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

    candles, last_closed, prep_errors, snap_meta = _prepare(candles_path, now)
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

    # Abstaining models (guard24) return direction="abstain" — visible in the
    # run log via skipped_filter, but no ledger row is ever written.
    if direction == "abstain":
        summary["skipped_filter"].append({
            "model_version": model_version,
            "abstain": True,
            "reason": reason,
        })
        return summary

    regime = detect_regime_label(closed)

    feature_uri_ = feature_uri or "data/public/candles_1h.json"
    source_uri_ = source_uri or "data/public/candles_1h.json"
    issued_at_actual = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    entry_source = snap_meta.get("entry_source") or "unknown"
    entry_symbol = snap_meta.get("entry_symbol")

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
        # No-backdating guard: a bucket whose start is further in the past
        # than max_backdate must stay empty — entry/signal are from run time,
        # so filling it would misstate the true horizon. Missing is honest.
        if max_backdate is not None and (now - bucket) > max_backdate:
            late_min = int((now - bucket).total_seconds() // 60)
            summary["skipped_filter"].append({
                "horizon": h,
                "issued_bucket": bucket_iso,
                "reason": (
                    f"backfill-guard: now is {late_min}m past bucket start "
                    f"(max {int(max_backdate.total_seconds() // 60)}m); "
                    "skipping — a missing bucket is honest"
                ),
            })
            continue
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
            issued_at_actual=issued_at_actual,
            entry_source=entry_source,
            entry_symbol=entry_symbol,
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
    max_backdate: timedelta | None = None,
) -> dict:
    """Baseline-only issuer — preserves prior API for unit tests.

    NOTE: `max_backdate` defaults to None (no guard) so pre-v0.3 API callers
    and the frozen unit tests keep their behavior. The production CLI path
    (main) always passes the guard — see MAX_BACKDATE_DEFAULT.
    """
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
        max_backdate=max_backdate,
    )


def run_all(
    ledger_root: Path,
    candles_path: Path,
    baseline_horizons: list[str],
    now: datetime | None = None,
    dry_run: bool = False,
    feature_uri: str | None = None,
    source_uri: str | None = None,
    enable_policy24: bool = False,
    enable_guard24: bool = True,
    max_backdate: timedelta | None = None,
) -> dict:
    """Dual issuer: baseline control + guard24 candidate.

    policy24 was KILLED 2026-08-10 and now defaults OFF; the parameter
    remains so the frozen dual tests (which pass enable_policy24=True) and
    any historical replay keep working.
    """
    # Resolve `now` once so every model in this run shares the same clock
    # (guard24's weekend rule reads it, and issued_at_actual should agree).
    now = now or datetime.now(timezone.utc)
    base = run(
        ledger_root, candles_path, baseline_horizons,
        now=now, dry_run=dry_run,
        feature_uri=feature_uri, source_uri=source_uri,
        max_backdate=max_backdate,
    )
    out = {
        "issuer_version": ISSUER_VERSION,
        "models": {"baseline": base},
        "issued_total": len(base.get("issued") or []),
        "errors": list(base.get("errors") or []),
    }
    if enable_guard24:
        guard = run_model(
            ledger_root,
            candles_path,
            list(GUARD_HORIZONS),
            model_version=GUARD_MODEL_VERSION,
            signal_version=GUARD_SIGNAL_VERSION,
            created_by=GUARD_CREATED_BY,
            signal_fn=lambda closes: guard24_direction_and_prob(closes, now),
            now=now,
            dry_run=dry_run,
            feature_uri=feature_uri,
            source_uri=source_uri,
            max_backdate=max_backdate,
        )
        out["models"]["guard24"] = guard
        out["issued_total"] += len(guard.get("issued") or [])
        out["errors"].extend(guard.get("errors") or [])
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
            max_backdate=max_backdate,
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
        help="baseline=control only; dual=baseline+guard24 (default). "
             "policy24 was killed 2026-08-10 and is no longer issuable "
             "from the CLI.",
    )
    ap.add_argument("--no-guard24", action="store_true",
                    help="disable the guard24 candidate even in dual mode")
    ap.add_argument(
        "--max-backdate-minutes",
        type=int,
        default=int(MAX_BACKDATE_DEFAULT.total_seconds() // 60),
        help="skip any bucket whose start is more than this many minutes "
             "before now (no-backdating guard; <=0 disables — replay only)",
    )
    args = ap.parse_args(argv)
    horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]
    max_backdate = (
        timedelta(minutes=args.max_backdate_minutes)
        if args.max_backdate_minutes > 0 else None
    )

    if args.mode == "baseline":
        summary = run(
            ledger_root=Path(args.root),
            candles_path=Path(args.candles),
            horizons=horizons,
            dry_run=args.dry_run,
            feature_uri=args.feature_uri,
            source_uri=args.source_uri,
            max_backdate=max_backdate,
        )
    else:
        summary = run_all(
            ledger_root=Path(args.root),
            candles_path=Path(args.candles),
            baseline_horizons=horizons,
            dry_run=args.dry_run,
            feature_uri=args.feature_uri,
            source_uri=args.source_uri,
            enable_guard24=not args.no_guard24,
            max_backdate=max_backdate,
        )

    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    # Run-log visibility for abstains + backfill skips (stderr, greppable).
    models = summary.get("models") or {"_": summary}
    for name, m in models.items():
        for skip in m.get("skipped_filter") or []:
            print(f"[issue][{name}] skipped: {skip.get('reason')}",
                  file=sys.stderr)

    if args.mode == "baseline":
        if (summary["errors"] and not summary["issued"]
                and not summary["skipped_duplicate"]
                and not summary["skipped_filter"]):
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
