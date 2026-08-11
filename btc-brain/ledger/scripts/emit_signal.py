"""
Emit versioned paper-trading signal.json from the forecast ledger.

Rules (hard):
  - Only 24h by default (12h optional via flag)
  - Never emit 1h/4h as actionable_paper
  - Gates evaluate the EMITTING model's own (model_version × horizon) record,
    never a pooled bucket. status=actionable_paper ONLY if ALL of:
      * all-time n_resolved >= 40 for that model × horizon
      * all-time wilson_lb_95 > 0.50
      * rolling-30d (issued_at-keyed): n >= 20 AND hit_rate >= 0.52
        AND expectancy_maker_2bps > 0
      * the emitted forecast is not past expires_at
    Anything else → shadow, with every failing condition listed in
    gates.reasons. A preferred model that fails gates still has its forecast
    emitted — as shadow. Honest state over green lights.
  - Not financial advice — paper contract for OpenClaw only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger import Ledger, parse_iso_utc, utc_now_iso  # noqa: E402
import metrics as metrics_mod  # noqa: E402

SIGNAL_SCHEMA_VERSION = "signal-v0.2.0"
DEFAULT_HORIZONS = ("24h",)
# v0.3.0-shadow-guard24 replaced v0.2.0-shadow-policy24 on 2026-08-10
# (Phase 6 kill decision — see research/promotion_decision_20260810.md).
# policy24 stays listed last so its final open forecasts can still resolve
# into an honest shadow signal until they age out; it no longer issues.
PREFERRED_MODELS = (
    "v0.3.0-shadow-guard24",
    "v0.1.0-baseline-shadow",
    "v0.2.0-shadow-policy24",
)

# Gate thresholds (master plan Phase 5/6).
GATE_MIN_N_RESOLVED = 40
GATE_MIN_WILSON_LB = 0.50       # strict: must be > this
GATE_R30_MIN_N = 20
GATE_R30_MIN_HIT = 0.52


def _pick_forecast(forecasts: list[dict], horizons: tuple[str, ...]) -> dict | None:
    # Prefer newest open (or most recently issued) forecast matching preferred models + horizons
    cands = [f for f in forecasts if f.get("horizon") in horizons]
    if not cands:
        return None
    # rank by model preference then issued_at
    def key(f: dict):
        try:
            mi = PREFERRED_MODELS.index(f.get("model_version", ""))
        except ValueError:
            mi = 99
        return (mi, f.get("issued_at", ""))

    cands.sort(key=key)
    # among best model tier, take latest issued
    best_model = cands[0].get("model_version")
    tier = [f for f in cands if f.get("model_version") == best_model]
    tier.sort(key=lambda f: f.get("issued_at", ""), reverse=True)
    return tier[0]


def _fmt(x, digits: int = 4) -> str:
    return "null" if x is None else f"{x:.{digits}f}"


def _gates(accuracy: dict, forecast: dict, now: datetime | None = None) -> dict:
    """Gate on the EMITTING model's own (model_version × horizon) record.

    Old bug: the gate read the pooled by_horizon bucket, so a failing model
    riding a strong pooled bucket said actionable_paper. Now the gate and
    the emitted forecast always talk about the same model.
    """
    now = now or datetime.now(timezone.utc)
    model = forecast.get("model_version", "unknown")
    horizon = forecast.get("horizon", "unknown")
    key = metrics_mod.model_horizon_key(model, horizon)

    bucket = (accuracy.get("by_model_horizon") or {}).get(key) or {}
    roll_mh = ((accuracy.get("rolling") or {}).get("by_model_horizon")
               or {}).get(key) or {}
    r30 = roll_mh.get("30d") or {}
    rolling_global = (accuracy.get("rolling") or {}).get("30d") or {}

    n = bucket.get("n") or 0
    hit = bucket.get("hit_rate")
    maker = bucket.get("expectancy_maker_2bps")
    wlb = bucket.get("wilson_lb_95")
    vs = bucket.get("vs_majority_pp")
    r30_n = r30.get("n") or 0
    r30_hit = r30.get("hit_rate")
    r30_maker = r30.get("expectancy_maker_2bps")

    reasons: list[str] = []
    if not bucket:
        reasons.append(
            f"no by_model_horizon bucket for {key} in accuracy metrics "
            "(requires metrics-v0.3.0 accuracy.json)")
    if n < GATE_MIN_N_RESOLVED:
        reasons.append(
            f"all-time n_resolved {n} < {GATE_MIN_N_RESOLVED} "
            f"for {model} × {horizon}")
    if wlb is None or wlb <= GATE_MIN_WILSON_LB:
        reasons.append(
            f"all-time wilson_lb_95 {_fmt(wlb)} not > {GATE_MIN_WILSON_LB} "
            f"(hit_rate {_fmt(hit)} at n={n})")
    if r30_n < GATE_R30_MIN_N:
        reasons.append(
            f"rolling-30d n {r30_n} < {GATE_R30_MIN_N} (issued_at-keyed)")
    if r30_hit is None or r30_hit < GATE_R30_MIN_HIT:
        reasons.append(
            f"rolling-30d hit_rate {_fmt(r30_hit)} < {GATE_R30_MIN_HIT}")
    if r30_maker is None or r30_maker <= 0:
        reasons.append(
            f"rolling-30d expectancy_maker_2bps {_fmt(r30_maker, 2)} not > 0")
    expires_at = forecast.get("target_time")
    if expires_at and parse_iso_utc(expires_at) <= now:
        reasons.append(f"forecast expired: target_time {expires_at} <= now")

    ok = not reasons
    return {
        "ok": ok,
        "model_version": model,
        "horizon": horizon,
        "bucket": key,
        "n": n,
        "hit_rate": hit,
        "expectancy_maker_2bps": maker,
        "wilson_lb_95": wlb,
        "vs_majority_pp": vs,
        "rolling_30d": {
            "window_keyed_on": "issued_at",
            "n": r30_n,
            "hit_rate": r30_hit,
            "expectancy_maker_2bps": r30_maker,
            "wilson_lb_95": r30.get("wilson_lb_95"),
        },
        "rolling_30d_hit": rolling_global.get("hit_rate"),
        "thresholds": {
            "min_n_resolved": GATE_MIN_N_RESOLVED,
            "wilson_lb_95_gt": GATE_MIN_WILSON_LB,
            "rolling_30d_min_n": GATE_R30_MIN_N,
            "rolling_30d_min_hit": GATE_R30_MIN_HIT,
            "rolling_30d_maker_bps_gt": 0,
        },
        "reasons": reasons,
        "reason": (
            "gates_cleared"
            if ok
            else "insufficient_edge_or_sample — remain shadow"
        ),
    }


def build_signal(
    ledger_root: Path,
    accuracy_path: Path | None = None,
    horizons: tuple[str, ...] = DEFAULT_HORIZONS,
) -> dict:
    ledger = Ledger.at(ledger_root)
    forecasts = list(ledger.iter_forecasts())
    f = _pick_forecast(forecasts, horizons)

    accuracy = {}
    if accuracy_path and accuracy_path.exists():
        accuracy = json.loads(accuracy_path.read_text(encoding="utf-8"))
    else:
        accuracy = metrics_mod.build(ledger_root)

    if f is None:
        return {
            "schema_version": SIGNAL_SCHEMA_VERSION,
            "generated_at": utc_now_iso(),
            "status": "halted",
            "reason": "no_matching_forecast",
            "not_financial_advice": True,
            "disclaimer": "Paper signal only. Not financial advice. No live orders.",
            "signal": None,
        }

    g = _gates(accuracy, f)
    status = "actionable_paper" if g["ok"] else "shadow"

    return {
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "gates": g,
        "not_financial_advice": True,
        "disclaimer": (
            "Educational / paper-trading signal for OpenClaw. "
            "Not financial advice. No buy/sell instruction is implied."
        ),
        "economics": {
            "fee_assumption": "maker_rt_2bps",
            "horizon_primary": "24h",
            "expectancy_maker_2bps": g.get("expectancy_maker_2bps"),
            "hit_rate": g.get("hit_rate"),
            "vs_majority_pp": g.get("vs_majority_pp"),
            "n": g.get("n"),
        },
        "signal": {
            "signal_id": f"sig-{f['forecast_id'][:8]}",
            "forecast_id": f["forecast_id"],
            "issued_at": f["issued_at"],
            "expires_at": f["target_time"],
            "asset": f.get("asset", "BTCUSD"),
            "horizon": f["horizon"],
            "direction": f["direction"],
            "probability": f["probability"],
            "entry_ref": f["entry_price"],
            "model_version": f["model_version"],
            "signal_version": f.get("signal_version"),
            "regime": f.get("regime_at_issue", "unknown"),
            "invalidation": f.get("invalidation"),
            "confidence_reason": f.get("confidence_reason"),
            "target_rule": f.get("target_rule"),
        },
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--accuracy", default=None, help="path to accuracy.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--horizons", default="24h")
    args = ap.parse_args(argv)
    horizons = tuple(h.strip() for h in args.horizons.split(",") if h.strip())
    # Safety: strip short horizons even if passed
    horizons = tuple(h for h in horizons if h in ("12h", "24h", "1d", "7d", "30d"))
    if not horizons:
        horizons = DEFAULT_HORIZONS
    acc = Path(args.accuracy) if args.accuracy else None
    doc = build_signal(Path(args.root), accuracy_path=acc, horizons=horizons)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sig = doc.get("signal") or {}
    print(f"wrote {out} status={doc['status']} "
          f"horizon={sig.get('horizon')} dir={sig.get('direction')} "
          f"model={sig.get('model_version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
