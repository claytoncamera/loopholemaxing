"""
Emit versioned paper-trading signal.json from the forecast ledger.

Rules (hard):
  - Only 24h by default (12h optional via flag)
  - Never emit 1h/4h as actionable_paper
  - status=actionable_paper only when rolling gates clear; else shadow/halted
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

SIGNAL_SCHEMA_VERSION = "signal-v0.1.0"
DEFAULT_HORIZONS = ("24h",)
PREFERRED_MODELS = (
    "v0.2.0-shadow-policy24",
    "v0.1.0-baseline-shadow",
)


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


def _gates(accuracy: dict, horizon: str) -> dict:
    by_h = (accuracy.get("by_horizon") or {}).get(horizon) or {}
    rolling = (accuracy.get("rolling") or {}).get("30d") or {}
    n = by_h.get("n") or 0
    hit = by_h.get("hit_rate")
    maker = by_h.get("expectancy_maker_2bps")
    vs = by_h.get("vs_majority_pp")
    # Prefer horizon-specific; fall back to rolling global if thin
    ok = bool(
        n >= 40
        and hit is not None and hit >= 0.55
        and maker is not None and maker > 0
        and vs is not None and vs > 0
    )
    return {
        "ok": ok,
        "n": n,
        "hit_rate": hit,
        "expectancy_maker_2bps": maker,
        "vs_majority_pp": vs,
        "rolling_30d_hit": rolling.get("hit_rate"),
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

    g = _gates(accuracy, f["horizon"])
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
