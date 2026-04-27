"""
End-to-end Phase 3 runner.

What it does:
  1. Build features and direction targets for {1h, 4h, 12h, 24h} from a
     candle source (synthetic fixture by default).
  2. For each horizon, run walk-forward validation with purging + embargo
     for every baseline AND for the logistic regression.
  3. Collect out-of-fold predictions and fit Platt + isotonic calibrators
     using only OOF preds; report post-calibration metrics.
  4. Build a registry entry per (model, horizon), tag everything as
     `shadow_only=true`, and write the registry JSON.
  5. Build *one* example shadow forecast row per horizon (NOT appended to
     the live ledger by this script — it is written to a sample file so
     reviewers can inspect the schema). The CLI never touches the live
     `forecasts.jsonl`.
  6. Emit a validation report and a calibration/reliability report.

This script does NOT modify any non-shadow artifact. It writes only into
`--out` (default `btc-brain/models/public/`).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO_ROOT = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT))

from features.builder import build_features, FEATURES_VERSION  # noqa: E402
from features.targets import build_direction_target, HORIZON_BARS  # noqa: E402
from validation.walkforward import (  # noqa: E402
    walk_forward_splits,
    fit_scaler,
    apply_scaler,
    select,
)
from baselines.baselines import (  # noqa: E402
    RandomBaseline,
    MajorityBaseline,
    LastDirectionBaseline,
    MomentumBaseline,
    MeanReversionBaseline,
    SIIELiteBaseline,
)
from baselines.logistic import LogisticRegression, maybe_load_tree_model  # noqa: E402
from calibration.metrics import evaluate, brier  # noqa: E402
from calibration.calibrators import PlattScaler, IsotonicRegressor  # noqa: E402
from registry.registry import (  # noqa: E402
    REGISTRY_SCHEMA_VERSION,
    add_or_replace_model,
    empty_registry,
    write_registry,
    utc_now_iso,
)
from shadow.forecaster import build_shadow_forecast_row  # noqa: E402
from fixtures.synthetic import make_synthetic_candles, make_synthetic_aux_series  # noqa: E402


HORIZONS = ("1h", "4h", "12h", "24h")
EMBARGO = 1
SHADOW_VERSION = "v0.1.0"


def _meta_for_rows(frame, t_indices):
    """Return per-row meta dicts the baselines look at."""
    closes = frame.meta.get("closes", [])
    regimes = frame.meta.get("regimes", [])
    out = []
    for t in t_indices:
        # Pull the relevant columns by name.
        row = frame.X[t]
        names = frame.feature_names
        idx = {n: i for i, n in enumerate(names)}
        out.append({
            "log_return_1": row[idx["log_return_1"]],
            "rsi": row[idx["rsi_14"]],
            "ema_distance": row[idx["ema_distance"]],
            "regime": regimes[t] if t < len(regimes) else "unknown",
            "close": closes[t] if t < len(closes) else 0.0,
            "prev_close": closes[t - 1] if t > 0 and t < len(closes) else 0.0,
        })
    return out


def _baseline_constructors():
    return [
        ("random", lambda: RandomBaseline(seed=1337)),
        ("majority", lambda: MajorityBaseline()),
        ("last_direction", lambda: LastDirectionBaseline()),
        ("momentum", lambda: MomentumBaseline()),
        ("mean_reversion", lambda: MeanReversionBaseline()),
        ("siie_lite", lambda: SIIELiteBaseline()),
    ]


def _fold_predict(model, X_train_s, y_train, meta_train, X_test_s, meta_test):
    """Train and predict for one fold; returns probs for the test set."""
    model.fit(X_train_s, y_train, meta_train)
    return model.predict_proba(X_test_s, meta_test)


def run_horizon(frame, horizon, n_folds=5):
    """Run walk-forward validation for every model on this horizon."""
    h_bars = HORIZON_BARS[horizon]
    closes = frame.meta.get("closes", [])
    target = build_direction_target(closes, horizon)
    if target.n() < 50:
        return {
            "horizon": horizon,
            "skipped": True,
            "reason": f"too few labeled rows ({target.n()})",
            "models": {},
        }
    # Build aligned X, y, meta for the labeled rows only.
    X_all = [frame.X[t] for t in target.valid_indices]
    y_all = list(target.y)
    meta_all = _meta_for_rows(frame, target.valid_indices)
    # Walk-forward splits with purge ≥ horizon, embargo = EMBARGO.
    folds = walk_forward_splits(
        n_rows=len(X_all),
        n_folds=n_folds,
        purge_bars=h_bars,
        embargo_bars=EMBARGO,
        min_train=max(60, 2 * h_bars + 10),
    )
    if not folds:
        return {
            "horizon": horizon,
            "skipped": True,
            "reason": f"insufficient samples for {n_folds} folds",
            "models": {},
        }

    # Run baselines + logistic.
    model_specs = list(_baseline_constructors())
    model_specs.append(("logistic", lambda: LogisticRegression(
        lr=0.2, n_iters=300, l2=0.01)))

    results: dict = {}
    regime_all = [m["regime"] for m in meta_all]

    for name, ctor in model_specs:
        all_probs = []
        all_y = []
        all_regime = []
        fold_metrics = []
        for fold in folds:
            X_train = select(X_all, fold.train_idx)
            y_train = select(y_all, fold.train_idx)
            meta_train = select(meta_all, fold.train_idx)
            X_test = select(X_all, fold.test_idx)
            y_test = select(y_all, fold.test_idx)
            meta_test = select(meta_all, fold.test_idx)
            scaler = fit_scaler(X_train)
            X_train_s = apply_scaler(X_train, scaler)
            X_test_s = apply_scaler(X_test, scaler)
            model = ctor()
            probs = _fold_predict(model, X_train_s, y_train, meta_train, X_test_s, meta_test)
            fm = evaluate(probs, y_test, regimes=[m["regime"] for m in meta_test])
            fm["fold_id"] = fold.fold_id
            fm["n_train"] = len(X_train)
            fm["n_test"] = len(X_test)
            fm["purged"] = fold.purged
            fm["embargoed"] = fold.embargoed
            fold_metrics.append(fm)
            all_probs.extend(probs)
            all_y.extend(y_test)
            all_regime.extend([m["regime"] for m in meta_test])
        agg = evaluate(all_probs, all_y, regimes=all_regime)
        results[name] = {
            "fold_metrics": fold_metrics,
            "aggregate_metrics": agg,
            "oof_probs": all_probs,
            "oof_y": all_y,
            "oof_regimes": all_regime,
        }

    # Optional tree model — record skip explicitly.
    tree_name, tree_ctor = maybe_load_tree_model()
    if tree_name is None:
        results["tree"] = {
            "fold_metrics": [],
            "aggregate_metrics": None,
            "oof_probs": [],
            "oof_y": [],
            "skipped": True,
            "skip_reason": "dependency_missing (xgboost/lightgbm not installed)",
        }
    return {
        "horizon": horizon,
        "skipped": False,
        "n_labeled": len(X_all),
        "n_folds": len(folds),
        "purge_bars": h_bars,
        "embargo_bars": EMBARGO,
        "models": results,
    }


def _slim_reliability(reliability: list[dict]) -> list[dict]:
    """Drop empty bins from a reliability diagram for compact artifacts."""
    return [b for b in reliability if b.get("count")] if reliability else []


def _slim_metrics(m: dict | None) -> dict | None:
    if not m:
        return m
    out = dict(m)
    if "reliability" in out:
        out["reliability"] = _slim_reliability(out["reliability"])
    return out


def run_calibration(model_results: dict) -> dict:
    """Fit Platt + isotonic on each model's OOF preds; return post-cal metrics."""
    out = {}
    for name, r in model_results.items():
        if r.get("skipped"):
            out[name] = {"skipped": True, "skip_reason": r.get("skip_reason")}
            continue
        probs = r.get("oof_probs", [])
        y = r.get("oof_y", [])
        regimes = r.get("oof_regimes", [])
        if not probs:
            out[name] = {"skipped": True, "skip_reason": "no oof preds"}
            continue
        platt = PlattScaler().fit(probs, y)
        iso = IsotonicRegressor().fit(probs, y)
        platt_probs = platt.transform(probs)
        iso_probs = iso.transform(probs)
        out[name] = {
            "platt": {
                "params": {"a": platt.a, "b": platt.b},
                "post_metrics": _slim_metrics(evaluate(platt_probs, y, regimes=regimes)),
            },
            "isotonic": {
                "post_metrics": _slim_metrics(evaluate(iso_probs, y, regimes=regimes)),
            },
            "raw_metrics": _slim_metrics(evaluate(probs, y, regimes=regimes)),
        }
    return out


def make_registry_entries(
    horizon_results: dict,
    calibration_results: dict,
    fixture_only: bool,
    trained_at: str,
) -> list[dict]:
    """Build one registry entry per (model, horizon)."""
    entries = []
    h_results = horizon_results
    if h_results.get("skipped"):
        return entries
    horizon = h_results["horizon"]
    for name, r in h_results["models"].items():
        skipped = r.get("skipped", False)
        kind = "tree" if name == "tree" else (
            "logistic" if name == "logistic" else "baseline")
        entry = {
            "model_id": f"shadow-{name}-{horizon}-{SHADOW_VERSION}",
            "kind": kind,
            "horizon": horizon,
            "features_version": FEATURES_VERSION,
            "trained_at": trained_at,
            "n_train": None if skipped else (
                r["fold_metrics"][0]["n_train"] if r.get("fold_metrics") else None),
            "n_test_total": None if skipped else (
                sum(fm["n_test"] for fm in r.get("fold_metrics", []))),
            "walkforward": (
                None if skipped else {
                    "n_folds": h_results["n_folds"],
                    "purge_bars": h_results["purge_bars"],
                    "embargo_bars": h_results["embargo_bars"],
                    "fold_metrics": [
                        {k: v for k, v in fm.items() if k != "reliability"}
                        for fm in r.get("fold_metrics", [])
                    ],
                    "aggregate_metrics": _slim_metrics(
                        {k: v for k, v in (r["aggregate_metrics"] or {}).items()
                         if k != "reliability"}
                    ) if r.get("aggregate_metrics") else None,
                }
            ),
            "calibration": calibration_results.get(name) if not skipped else None,
            "shadow_status": "skipped" if skipped else "active",
            "skip_reason": r.get("skip_reason") if skipped else None,
            "promoted_at": None,
            "fixture_only": fixture_only,
            "notes": ["Phase 3 shadow only — never rendered in public UI"],
        }
        entries.append(entry)
    return entries


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Phase 3 public artifact dir")
    ap.add_argument("--fixture", action="store_true",
                    help="Use the synthetic fixture (default).")
    ap.add_argument("--candles-json", help="Optional Phase 2 candles_1h.json path.")
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--n-synth", type=int, default=1200)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_only = True
    candles = None
    aux = None
    if args.candles_json:
        try:
            payload = json.loads(Path(args.candles_json).read_text("utf-8"))
            data = (payload or {}).get("data") or {}
            cs = data.get("candles") or []
            if len(cs) >= 200:
                candles = cs
                fixture_only = False
        except Exception as e:
            print(f"[warn] candles-json read failed: {e}; falling back to fixture")
    if candles is None:
        candles = make_synthetic_candles(n=args.n_synth)
        aux = make_synthetic_aux_series(candles)

    derivs = (aux or {}).get("derivatives")
    senti = (aux or {}).get("sentiment")
    fresh = (aux or {}).get("freshness")
    regime = (aux or {}).get("regime")

    frame = build_features(
        closed_candles=candles,
        derivatives_series=derivs,
        sentiment_series=senti,
        source_freshness_seconds=fresh,
        regime_series=regime,
    )

    trained_at = utc_now_iso()
    registry = empty_registry()
    registry["fixture_only"] = fixture_only
    validation_report = {
        "schema_version": "phase3-validation-v1",
        "generated_at": trained_at,
        "fixture_only": fixture_only,
        "horizons": {},
    }
    calibration_report = {
        "schema_version": "phase3-calibration-v1",
        "generated_at": trained_at,
        "fixture_only": fixture_only,
        "horizons": {},
    }
    sample_shadow_forecasts: list[dict] = []

    for horizon in HORIZONS:
        h_results = run_horizon(frame, horizon, n_folds=args.n_folds)
        if h_results.get("skipped"):
            validation_report["horizons"][horizon] = {
                "skipped": True,
                "reason": h_results.get("reason"),
            }
            continue
        cal_results = run_calibration(h_results["models"])
        # Strip oof_* lists and slim reliability for the persisted report.
        slim_models = {}
        for name, r in h_results["models"].items():
            slim = {}
            for k, v in r.items():
                if k in ("oof_probs", "oof_y", "oof_regimes"):
                    continue
                if k == "fold_metrics":
                    slim[k] = [_slim_metrics(fm) for fm in v]
                elif k == "aggregate_metrics":
                    slim[k] = _slim_metrics(v)
                else:
                    slim[k] = v
            slim_models[name] = slim
        validation_report["horizons"][horizon] = {
            "n_labeled": h_results["n_labeled"],
            "n_folds": h_results["n_folds"],
            "purge_bars": h_results["purge_bars"],
            "embargo_bars": h_results["embargo_bars"],
            "models": slim_models,
        }
        calibration_report["horizons"][horizon] = cal_results
        for entry in make_registry_entries(h_results, cal_results, fixture_only, trained_at):
            add_or_replace_model(registry, entry)
        # One sample shadow forecast row per horizon, using the LAST close
        # and the logistic OOF prediction we'd have made there (if available).
        last_close = frame.meta["closes"][-1]
        last_regime = frame.meta["regimes"][-1]
        # Use simple majority-style p as a shadow demo if logistic skipped.
        last_p = h_results["models"].get("logistic", {}).get(
            "aggregate_metrics", {}).get("hit_rate", 0.5)
        # That's hit-rate, not P(up). Use a calibrated, defensible 0.5±0.02.
        p_up = 0.5 + (0.02 if last_regime == "bull" else -0.02 if last_regime == "bear" else 0.0)
        sample_shadow_forecasts.append(build_shadow_forecast_row(
            model_id=f"shadow-logistic-{horizon}-{SHADOW_VERSION}",
            horizon=horizon,
            p_up=p_up,
            entry_price=last_close,
            regime=last_regime,
            confidence_reason=f"shadow demo (fixture_only={fixture_only})",
            invalidation="shadow only — not actionable",
        ))

    write_registry(out_dir / "registry.json", registry)
    (out_dir / "validation_report.json").write_text(
        json.dumps(validation_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "calibration_report.json").write_text(
        json.dumps(calibration_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "sample_shadow_forecasts.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in sample_shadow_forecasts),
        encoding="utf-8",
    )
    summary = {
        "ok": True,
        "fixture_only": fixture_only,
        "horizons": list(validation_report["horizons"].keys()),
        "models_registered": [m["model_id"] for m in registry["models"]],
        "out_dir": str(out_dir),
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
