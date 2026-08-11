"""
Phase 3 LIVE runner — walk-forward training on the real candle history.

Differences from run_phase3.py (the fixture-capable runner):
  * Data source is `data/history/candles_1h.jsonl` (17k+ closed 1h bars,
    Aug-2024 onward, built 2026-08-10 from git reconstruction + Coinbase
    backfill) — never the 200-bar snapshot, never the synthetic fixture.
  * A causal regime series (models/phase4/regime.py) is computed over the
    full history and fed to the feature builder — the fixture runner's
    real-data path silently dropped it.
  * Features are phase3-features-v0.2.0 (SMA24/72 rel, down-confirmation,
    trailing returns, calendar encodings — the edges the ledger measured).
  * Calibration is evaluated on a chronological holdout of the OOF stream
    (fit on the first 60%, scored on the last 40%) instead of in-sample on
    the same rows the calibrator saw.
  * Economics: every pooled-OOS row is also scored as a paper trade
    (direction = p>=0.5, signed simple return in bps, minus a 2 bps maker
    round trip), with a Wilson 95% lower bound on the hit rate.

SELECTION RULE — pre-specified (master plan Phase 3 step 6), evaluated by
code below and printed into the report BEFORE any human looks at results:

    The ML candidate is `logistic` on the 24h horizon. It is selected IFF
      (a) its pooled OOS hit rate is STRICTLY greater than the pooled OOS
          majority rate (max of always-up / always-down over the same
          rows), AND
      (b) its pooled OOS Brier is <= the best baseline Brier on 24h.
    Otherwise the verdict is NO CANDIDATE and nothing may be wired into
    the issuer. There is no post-hoc hyperparameter or threshold search:
    the logistic hyperparameters are fixed constants in this file.

Logistic runs only on 12h and 24h (the fee-surviving horizons). 1h/4h get
baselines only, for reporting — the master plan forbids tuning for them.

Outputs (all under --out, default btc-brain/models/public/):
  registry.json               — regenerated, fixture_only=false
  validation_report.json      — walk-forward metrics per model x horizon
  calibration_report.json     — raw + holdout-calibrated metrics
  sample_shadow_forecasts.jsonl
  phase3_live/candidate_v0.4.0.json   — frozen weights (ONLY if selected)
  phase3_live/selection_decision.json — machine-readable verdict either way
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO_ROOT = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

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
    _BaseModel,
    _clip,
)
from baselines.logistic import LogisticRegression  # noqa: E402
from calibration.metrics import evaluate  # noqa: E402
from calibration.calibrators import PlattScaler, IsotonicRegressor  # noqa: E402
from registry.registry import (  # noqa: E402
    add_or_replace_model,
    empty_registry,
    write_registry,
    utc_now_iso,
)
from shadow.forecaster import build_shadow_forecast_row  # noqa: E402
from phase4.regime import detect_regimes  # noqa: E402


HORIZONS_ALL = ("1h", "4h", "12h", "24h")
HORIZONS_ML = ("12h", "24h")
EMBARGO_BARS = 24
MIN_TRAIN = 4000
N_FOLDS = 6
SHADOW_VERSION = "v0.4.0"
MAKER_RT_BPS = 2.0
# Fixed constants — no search. Changing these invalidates the selection rule.
LOGISTIC_HYPERS = {"lr": 0.3, "n_iters": 250, "l2": 0.01}


class Sma24RuleBaseline(_BaseModel):
    """Replica of the live v0.1.0-baseline-shadow DIRECTION rule.

    up iff close >= SMA24 (RAW sma24_rel >= 0). The raw column values are
    injected at construction and predictions are keyed to the caller-passed
    meta rows via `_row_ids` — the X the harness passes is z-scored (fit on
    train), and thresholding the SCALED column at 0 silently becomes
    "raw >= train mean", which the 2026-08-11 adversarial verification
    measured at 297/11,320 flipped predictions. Probabilities are a fixed
    0.55/0.45; Brier for this replica is reported but not meaningful for
    the live model (which clamps to [0.5005, 0.55] by SMA distance).
    """

    name = "sma24_rule"

    def __init__(self, raw_col_by_rowid: dict[int, float]):
        self.raw = raw_col_by_rowid

    def predict_proba(self, X, meta):
        out = []
        for m in meta:
            raw = self.raw.get(m["_row_id"], 0.0)
            out.append(_clip(0.55) if raw >= 0.0 else _clip(0.45))
        return out


def load_history_candles(path: Path) -> list[dict]:
    """Load the history jsonl; enforce sorted/unique/closed-bar invariants."""
    now_ms = int(time.time() * 1000)
    current_hour_open_ms = (now_ms // 3600000) * 3600000
    by_open: dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            t = int(r["open_time_ms"])
            # Closed-bar guard: the bar opening in the CURRENT hour is still
            # in progress; anything at/after it is dropped.
            if t >= current_hour_open_ms:
                continue
            by_open[t] = {
                "open_time_ms": t,
                "close_time_ms": t + 3600000 - 1,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume") or 0.0),
            }
    candles = [by_open[t] for t in sorted(by_open)]
    if len(candles) < MIN_TRAIN:
        raise SystemExit(
            f"history too small: {len(candles)} bars < MIN_TRAIN={MIN_TRAIN}")
    return candles


def wilson_lb_95(p: float, n: int) -> float | None:
    if n <= 0:
        return None
    z = 1.959963984540054
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return (centre - margin) / denom


def economics(
    probs: list[float],
    entry_closes: list[float],
    exit_closes: list[float],
    h_bars: int = 1,
) -> dict:
    """Score pooled OOS predictions as 1-unit paper trades."""
    n = 0
    hits = 0
    sum_bps = 0.0
    sum_bps_maker = 0.0
    for p, c0, c1 in zip(probs, entry_closes, exit_closes):
        if c0 <= 0 or c1 <= 0:
            continue
        direction_up = p >= 0.5
        raw_bps = (c1 - c0) / c0 * 10000.0
        signed = raw_bps if direction_up else -raw_bps
        n += 1
        if signed > 0:
            hits += 1
        sum_bps += signed
        sum_bps_maker += signed - MAKER_RT_BPS
    hit = hits / n if n else None
    return {
        "n": n,
        "hit_rate": hit,
        "wilson_lb_95": wilson_lb_95(hit, n) if hit is not None else None,
        "wilson_lb_note": (
            "OVERSTATES precision on overlapping hourly-issued H-bar labels: "
            "consecutive labels share up to H-1 bars, so effective "
            "independent n ≈ n/H, widening the honest interval ~sqrt(H)x. "
            "Evidence field only — never a promotion gate input."),
        "effective_n_approx": (max(1, n // h_bars) if n else None),
        "expectancy_bps": (sum_bps / n) if n else None,
        "expectancy_maker_2bps": (sum_bps_maker / n) if n else None,
    }


def majority_rate(y: list[int]) -> float | None:
    if not y:
        return None
    up = sum(y) / len(y)
    return max(up, 1.0 - up)


def run_horizon(frame, horizon, include_logistic: bool, n_folds: int) -> dict:
    h_bars = HORIZON_BARS[horizon]
    closes = frame.meta["closes"]
    target = build_direction_target(closes, horizon)
    X_all = [frame.X[t] for t in target.valid_indices]
    y_all = list(target.y)
    entry_close_all = [closes[t] for t in target.valid_indices]
    exit_close_all = [closes[t] for t in target.target_close_idx]
    regimes = frame.meta["regimes"]
    meta_all = []
    idx = {n: i for i, n in enumerate(frame.feature_names)}
    for local_i, t in enumerate(target.valid_indices):
        row = frame.X[t]
        meta_all.append({
            "_row_id": local_i,
            "log_return_1": row[idx["log_return_1"]],
            "rsi": row[idx["rsi_14"]],
            "ema_distance": row[idx["ema_distance"]],
            "regime": regimes[t] if t < len(regimes) else "unknown",
            "close": closes[t],
            "prev_close": closes[t - 1] if t > 0 else 0.0,
        })

    folds = walk_forward_splits(
        n_rows=len(X_all),
        n_folds=n_folds,
        purge_bars=h_bars,
        embargo_bars=EMBARGO_BARS,
        min_train=MIN_TRAIN,
    )
    if not folds:
        return {"horizon": horizon, "skipped": True,
                "reason": "insufficient rows for folds", "models": {}}

    sma24_col = idx["sma24_rel"]
    raw_sma24_by_rowid = {
        i: X_all[i][sma24_col] for i in range(len(X_all))
    }
    model_specs = [
        ("random", lambda: RandomBaseline(seed=1337)),
        ("majority", lambda: MajorityBaseline()),
        ("last_direction", lambda: LastDirectionBaseline()),
        ("momentum", lambda: MomentumBaseline()),
        ("mean_reversion", lambda: MeanReversionBaseline()),
        ("siie_lite", lambda: SIIELiteBaseline()),
        ("sma24_rule", lambda: Sma24RuleBaseline(
            raw_col_by_rowid=raw_sma24_by_rowid)),
    ]
    if include_logistic:
        model_specs.append(("logistic", lambda: LogisticRegression(
            lr=LOGISTIC_HYPERS["lr"],
            n_iters=LOGISTIC_HYPERS["n_iters"],
            l2=LOGISTIC_HYPERS["l2"],
        )))

    results: dict = {}
    for name, ctor in model_specs:
        t_start = time.time()
        all_probs: list[float] = []
        all_y: list[int] = []
        all_regime: list[str] = []
        all_entry: list[float] = []
        all_exit: list[float] = []
        fold_metrics = []
        for fold in folds:
            X_train = select(X_all, fold.train_idx)
            y_train = select(y_all, fold.train_idx)
            meta_train = select(meta_all, fold.train_idx)
            X_test = select(X_all, fold.test_idx)
            y_test = select(y_all, fold.test_idx)
            meta_test = select(meta_all, fold.test_idx)
            scaler = fit_scaler(X_train)
            model = ctor()
            model.fit(apply_scaler(X_train, scaler), y_train, meta_train)
            probs = model.predict_proba(apply_scaler(X_test, scaler), meta_test)
            fm = evaluate(probs, y_test,
                          regimes=[m["regime"] for m in meta_test])
            fm.pop("reliability", None)
            fm["fold_id"] = fold.fold_id
            fm["n_train"] = len(X_train)
            fm["n_test"] = len(X_test)
            fm["majority_rate_test"] = majority_rate(y_test)
            fold_metrics.append(fm)
            all_probs.extend(probs)
            all_y.extend(y_test)
            all_regime.extend([m["regime"] for m in meta_test])
            all_entry.extend(select(entry_close_all, fold.test_idx))
            all_exit.extend(select(exit_close_all, fold.test_idx))
        agg = evaluate(all_probs, all_y, regimes=all_regime)
        agg.pop("reliability", None)
        maj = majority_rate(all_y)
        econ = economics(all_probs, all_entry, all_exit, h_bars=h_bars)
        results[name] = {
            "fold_metrics": fold_metrics,
            "aggregate_metrics": agg,
            "pooled_majority_rate": maj,
            "vs_majority_pp": (
                (agg.get("hit_rate") - maj)
                if (agg.get("hit_rate") is not None and maj is not None)
                else None),
            "economics": econ,
            "fit_seconds": round(time.time() - t_start, 1),
            "oof_probs": all_probs,
            "oof_y": all_y,
            "oof_regimes": all_regime,
        }
        print(f"  [{horizon}] {name}: hit={agg.get('hit_rate'):.4f} "
              f"brier={agg.get('brier'):.4f} vs_maj="
              f"{results[name]['vs_majority_pp']:+.4f} "
              f"maker={econ['expectancy_maker_2bps']:+.1f}bps "
              f"({results[name]['fit_seconds']}s)", flush=True)
    return {
        "horizon": horizon,
        "skipped": False,
        "n_labeled": len(X_all),
        "n_folds": len(folds),
        "purge_bars": h_bars,
        "embargo_bars": EMBARGO_BARS,
        "min_train": MIN_TRAIN,
        "models": results,
    }


def run_calibration_holdout(model_results: dict) -> dict:
    """Chronological-holdout calibration: fit on first 60% of the OOF
    stream, evaluate on the last 40%. OOF order is chronological because
    folds are chronological and extended in order."""
    out = {}
    for name, r in model_results.items():
        probs = r.get("oof_probs", [])
        y = r.get("oof_y", [])
        regimes = r.get("oof_regimes", [])
        if len(probs) < 100:
            out[name] = {"skipped": True, "skip_reason": "too few oof preds"}
            continue
        cut = int(len(probs) * 0.6)
        fit_p, fit_y = probs[:cut], y[:cut]
        ho_p, ho_y = probs[cut:], y[cut:]
        ho_regimes = regimes[cut:]
        platt = PlattScaler().fit(fit_p, fit_y)
        iso = IsotonicRegressor().fit(fit_p, fit_y)

        def _ev(pp):
            m = evaluate(pp, ho_y, regimes=ho_regimes)
            m.pop("reliability", None)
            return m

        raw_m = _ev(ho_p)
        out[name] = {
            "holdout_fraction": 0.4,
            "n_fit": len(fit_p),
            "n_holdout": len(ho_p),
            "raw_holdout_metrics": raw_m,
            "platt": {
                "params": {"a": platt.a, "b": platt.b},
                "holdout_metrics": _ev(platt.transform(ho_p)),
            },
            "isotonic": {
                "holdout_metrics": _ev(iso.transform(ho_p)),
            },
        }
    return out


def decide_candidate(h24: dict) -> dict:
    """Apply the pre-specified selection rule. Pure function of results."""
    models = h24.get("models", {})
    logi = models.get("logistic")
    decision = {
        "schema_version": "phase3-selection-v1",
        "rule": ("logistic@24h selected iff pooled OOS hit > pooled OOS "
                 "majority rate AND pooled OOS Brier <= best baseline Brier "
                 "on 24h; hyperparameters fixed in code; no search"),
        "horizon": "24h",
        "candidate_model": None,
        "selected": False,
        "reasons": [],
    }
    if not logi:
        decision["reasons"].append("logistic did not run on 24h")
        return decision
    hit = logi["aggregate_metrics"].get("hit_rate")
    brier = logi["aggregate_metrics"].get("brier")
    maj = logi.get("pooled_majority_rate")
    baseline_briers = {
        name: r["aggregate_metrics"].get("brier")
        for name, r in models.items()
        if name != "logistic" and r.get("aggregate_metrics")
    }
    best_baseline_brier = min(
        (b for b in baseline_briers.values() if b is not None), default=None)
    decision["evidence"] = {
        "logistic_hit": hit,
        "logistic_brier": brier,
        "pooled_majority_rate": maj,
        "vs_majority_pp": logi.get("vs_majority_pp"),
        "wilson_lb_95": logi["economics"].get("wilson_lb_95"),
        "expectancy_maker_2bps": logi["economics"].get("expectancy_maker_2bps"),
        "best_baseline_brier": best_baseline_brier,
        "baseline_briers": baseline_briers,
    }
    ok_hit = hit is not None and maj is not None and hit > maj
    ok_brier = (brier is not None and best_baseline_brier is not None
                and brier <= best_baseline_brier)
    if not ok_hit:
        decision["reasons"].append(
            f"hit {hit} does not beat pooled majority {maj}")
    if not ok_brier:
        decision["reasons"].append(
            f"brier {brier} not <= best baseline brier {best_baseline_brier}")
    if ok_hit and ok_brier:
        decision["selected"] = True
        decision["candidate_model"] = f"v{SHADOW_VERSION.lstrip('v')}-shadow-ml24"
        decision["reasons"].append("both selection criteria met")
    return decision


def freeze_candidate(frame, horizon: str, out_path: Path,
                     oof_probs: list[float], oof_y: list[int],
                     data_range: dict, trained_at: str) -> dict:
    """Fit final weights on ALL labeled rows (standard post-validation
    practice), scaler on the same, calibrator on the OOF stream (which is
    out-of-sample by construction)."""
    closes = frame.meta["closes"]
    target = build_direction_target(closes, horizon)
    X_all = [frame.X[t] for t in target.valid_indices]
    y_all = list(target.y)
    scaler = fit_scaler(X_all)
    model = LogisticRegression(
        lr=LOGISTIC_HYPERS["lr"],
        n_iters=LOGISTIC_HYPERS["n_iters"],
        l2=LOGISTIC_HYPERS["l2"],
    )
    model.fit(apply_scaler(X_all, scaler), y_all, None)
    platt = PlattScaler().fit(oof_probs, oof_y)
    frozen = {
        "schema_version": "ml24-candidate-v1",
        "model_version": f"v{SHADOW_VERSION.lstrip('v')}-shadow-ml24",
        "horizon": horizon,
        "features_version": FEATURES_VERSION,
        "feature_names": list(frame.feature_names),
        "trained_at": trained_at,
        "data_range": data_range,
        "n_train": len(X_all),
        "hyperparameters": dict(LOGISTIC_HYPERS),
        "scaler": {"means": scaler.means, "stds": scaler.stds},
        "weights": list(model.weights),
        "intercept": model.intercept,
        "calibration": {"method": "platt_on_oof",
                        "a": platt.a, "b": platt.b},
        "shadow_only": True,
        "notes": [
            "Frozen by run_phase3_live.py after walk-forward validation.",
            "Issuer must recompute features causally and refuse to predict "
            "if feature_names/version mismatch.",
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    return frozen


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(
        REPO_ROOT / "btc-brain" / "data" / "history" / "candles_1h.jsonl"))
    ap.add_argument("--out", default=str(
        REPO_ROOT / "btc-brain" / "models" / "public"))
    ap.add_argument("--n-folds", type=int, default=N_FOLDS)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    candles = load_history_candles(Path(args.history))
    closes = [c["close"] for c in candles]
    data_range = {
        "n_bars": len(candles),
        "first_open_ms": candles[0]["open_time_ms"],
        "last_open_ms": candles[-1]["open_time_ms"],
        "first_open_iso": datetime.fromtimestamp(
            candles[0]["open_time_ms"] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_open_iso": datetime.fromtimestamp(
            candles[-1]["open_time_ms"] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    print(f"history: {data_range['n_bars']} bars "
          f"{data_range['first_open_iso']} -> {data_range['last_open_iso']}",
          flush=True)

    regimes = detect_regimes(closes).coarse
    frame = build_features(closed_candles=candles, regime_series=regimes)
    trained_at = utc_now_iso()

    registry = empty_registry()
    registry["fixture_only"] = False
    validation_report = {
        "schema_version": "phase3-validation-v2-live",
        "generated_at": trained_at,
        "fixture_only": False,
        "features_version": FEATURES_VERSION,
        "data_range": data_range,
        "logistic_hyperparameters": dict(LOGISTIC_HYPERS),
        "horizons": {},
    }
    calibration_report = {
        "schema_version": "phase3-calibration-v2-live",
        "generated_at": trained_at,
        "fixture_only": False,
        "method": "chronological holdout: calibrators fit on first 60% of "
                  "OOF stream, metrics on last 40%",
        "horizons": {},
    }
    sample_rows: list[dict] = []
    h_results_by_horizon: dict[str, dict] = {}

    for horizon in HORIZONS_ALL:
        include_logistic = horizon in HORIZONS_ML
        print(f"— horizon {horizon} (logistic={include_logistic}) —",
              flush=True)
        h_results = run_horizon(frame, horizon, include_logistic,
                                args.n_folds)
        h_results_by_horizon[horizon] = h_results
        if h_results.get("skipped"):
            validation_report["horizons"][horizon] = {
                "skipped": True, "reason": h_results.get("reason")}
            continue
        calibration_report["horizons"][horizon] = run_calibration_holdout(
            h_results["models"])
        slim_models = {}
        for name, r in h_results["models"].items():
            slim_models[name] = {
                k: v for k, v in r.items()
                if k not in ("oof_probs", "oof_y", "oof_regimes")
            }
        validation_report["horizons"][horizon] = {
            k: (slim_models if k == "models" else v)
            for k, v in h_results.items()
        }
        for name, r in h_results["models"].items():
            kind = "logistic" if name == "logistic" else "baseline"
            agg = dict(r["aggregate_metrics"] or {})
            entry = {
                "model_id": f"shadow-{name}-{horizon}-{SHADOW_VERSION}",
                "kind": kind,
                "horizon": horizon,
                "features_version": FEATURES_VERSION,
                "trained_at": trained_at,
                "n_train": None,
                "n_train_note": "walk-forward; per-fold n_train in report",
                "n_test_total": sum(
                    fm["n_test"] for fm in r.get("fold_metrics", [])),
                "walkforward": {
                    "n_folds": h_results["n_folds"],
                    "purge_bars": h_results["purge_bars"],
                    "embargo_bars": h_results["embargo_bars"],
                    "aggregate_metrics": agg,
                    "pooled_majority_rate": r.get("pooled_majority_rate"),
                    "vs_majority_pp": r.get("vs_majority_pp"),
                    "economics": r.get("economics"),
                },
                "calibration": None,
                "shadow_status": "active",
                "skip_reason": None,
                "promoted_at": None,
                "fixture_only": False,
                "notes": ["Phase 3 LIVE walk-forward on real candle history"],
            }
            add_or_replace_model(registry, entry)

    # Pre-specified selection on 24h.
    decision = decide_candidate(h_results_by_horizon.get("24h", {}))
    frozen = None
    if decision["selected"]:
        logi = h_results_by_horizon["24h"]["models"]["logistic"]
        frozen = freeze_candidate(
            frame, "24h", out_dir / "phase3_live" / "candidate_v0.4.0.json",
            logi["oof_probs"], logi["oof_y"], data_range, trained_at)
        # 12h is NOT auto-selected; record its evidence for the report.
    decision["generated_at"] = trained_at
    (out_dir / "phase3_live").mkdir(parents=True, exist_ok=True)
    (out_dir / "phase3_live" / "selection_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    # Sample shadow rows (schema demo only, never appended to the ledger).
    last_close = frame.meta["closes"][-1]
    last_regime = frame.meta["regimes"][-1]
    for horizon in HORIZONS_ML:
        sample_rows.append(build_shadow_forecast_row(
            model_id=f"shadow-logistic-{horizon}-{SHADOW_VERSION}",
            horizon=horizon,
            p_up=0.5,
            entry_price=last_close,
            regime=last_regime,
            confidence_reason="schema demo row — p_up fixed at 0.5, "
                              "not a model output",
            invalidation="shadow only — not actionable",
        ))

    write_registry(out_dir / "registry.json", registry)
    (out_dir / "validation_report.json").write_text(
        json.dumps(validation_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (out_dir / "calibration_report.json").write_text(
        json.dumps(calibration_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (out_dir / "sample_shadow_forecasts.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in sample_rows),
        encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "fixture_only": False,
        "selected": decision["selected"],
        "candidate": decision.get("candidate_model"),
        "reasons": decision["reasons"],
        "out_dir": str(out_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
