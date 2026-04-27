"""
Compute public accuracy metrics from the ledger and write accuracy.json.

Buckets: by horizon, by model_version, plus rolling 7d / 30d / 90d windows.
For every bucket we report:
  - n (sample size)
  - hit_rate
  - brier (mean of brier_component, lower is better)
  - logloss (mean of logloss_component, lower is better)
  - ece if there are enough probability buckets (n>=20 and >=3 non-empty bins)
  - baseline_brier  (always-predict-base-rate-of-up, computed in-bucket)
  - baseline_hit_rate
  - last_updated

A `display_ready` flag tells the frontend whether the bucket meets the
minimum sample size for public display (default min_n_display=20).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger import Ledger, parse_iso_utc, utc_now_iso  # noqa: E402

METRICS_VERSION = "metrics-v0.1.0"
DEFAULT_MIN_N_DISPLAY = 20
ECE_BINS = 10


def _outcome_for(forecast: dict, resolution: dict) -> int:
    return 1 if resolution["direction_correct"] else 0


def _prob_for_direction(forecast: dict) -> float:
    # Probability is *already* the prob assigned to the forecasted direction.
    return float(forecast["probability"])


def _ece(pairs: list[tuple[float, int]], bins: int = ECE_BINS) -> float | None:
    """Expected calibration error.

    pairs: list of (predicted_prob, outcome ∈ {0,1}).
    Returns None if not enough non-empty bins (<3) or n<20.
    """
    if len(pairs) < 20:
        return None
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, o in pairs:
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, o))
    nonempty = [b for b in buckets if b]
    if len(nonempty) < 3:
        return None
    n = len(pairs)
    ece = 0.0
    for b in nonempty:
        avg_p = sum(p for p, _ in b) / len(b)
        avg_o = sum(o for _, o in b) / len(b)
        ece += (len(b) / n) * abs(avg_p - avg_o)
    return ece


def _baseline(pairs: list[tuple[float, int]]) -> dict:
    """Baseline = predict the in-bucket base rate of `up=correct` for every row.

    Brier and hit_rate of always-predicting the base rate.
    """
    if not pairs:
        return {"baseline_hit_rate": None, "baseline_brier": None, "base_rate": None}
    base_rate = sum(o for _, o in pairs) / len(pairs)
    # If we always predict the majority class, hit_rate = max(base_rate, 1-base_rate).
    baseline_hit_rate = max(base_rate, 1 - base_rate)
    # Brier of always predicting `base_rate`:
    baseline_brier = sum((base_rate - o) ** 2 for _, o in pairs) / len(pairs)
    return {
        "baseline_hit_rate": baseline_hit_rate,
        "baseline_brier": baseline_brier,
        "base_rate": base_rate,
    }


def _bucket_metrics(rows: list[dict], min_n_display: int) -> dict:
    """rows: list of joined dicts with non-null resolution and status==resolved."""
    pairs: list[tuple[float, int]] = []
    briers: list[float] = []
    losses: list[float] = []
    hits = 0
    for r in rows:
        f, res = r["forecast"], r["resolution"]
        o = _outcome_for(f, res)
        p = _prob_for_direction(f)
        pairs.append((p, o))
        briers.append(float(res["brier_component"]))
        losses.append(float(res["logloss_component"]))
        hits += o
    n = len(rows)
    base = _baseline(pairs)
    return {
        "n": n,
        "hit_rate": (hits / n) if n else None,
        "brier": (statistics.fmean(briers) if briers else None),
        "logloss": (statistics.fmean(losses) if losses else None),
        "ece": _ece(pairs),
        **base,
        "display_ready": n >= min_n_display,
    }


def _filter_resolved(joined: list[dict]) -> list[dict]:
    return [r for r in joined
            if r["resolution"] and r["resolution"].get("status") == "resolved"]


def _within(window_days: int, now: datetime, joined: list[dict]) -> list[dict]:
    cutoff = now - timedelta(days=window_days)
    out = []
    for r in joined:
        res = r["resolution"]
        if not res:
            continue
        ra = parse_iso_utc(res["resolved_at"])
        if ra >= cutoff:
            out.append(r)
    return out


def build(root: Path, min_n_display: int = DEFAULT_MIN_N_DISPLAY) -> dict:
    ledger = Ledger.at(root)
    joined_all = ledger.joined()
    resolved = _filter_resolved(joined_all)
    now = datetime.now(timezone.utc)

    # Group helpers
    by_horizon: dict[str, list] = defaultdict(list)
    by_model: dict[str, list] = defaultdict(list)
    for r in resolved:
        by_horizon[r["forecast"]["horizon"]].append(r)
        by_model[r["forecast"]["model_version"]].append(r)

    out = {
        "schema_version": "1",
        "metrics_version": METRICS_VERSION,
        "generated_at": utc_now_iso(),
        "min_n_display": min_n_display,
        "total_forecasts": sum(1 for _ in ledger.iter_forecasts()),
        "total_resolved": len(resolved),
        "by_horizon": {
            h: _bucket_metrics(rows, min_n_display)
            for h, rows in sorted(by_horizon.items())
        },
        "by_model_version": {
            m: _bucket_metrics(rows, min_n_display)
            for m, rows in sorted(by_model.items())
        },
        "rolling": {
            "7d": _bucket_metrics(_within(7, now, resolved), min_n_display),
            "30d": _bucket_metrics(_within(30, now, resolved), min_n_display),
            "90d": _bucket_metrics(_within(90, now, resolved), min_n_display),
        },
        "global": _bucket_metrics(resolved, min_n_display),
    }
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--out", required=True, help="output accuracy.json path")
    ap.add_argument("--min-n-display", type=int, default=DEFAULT_MIN_N_DISPLAY)
    args = ap.parse_args(argv)
    metrics = build(Path(args.root), min_n_display=args.min_n_display)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {out_path} (resolved={metrics['total_resolved']}, "
          f"forecasts={metrics['total_forecasts']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
