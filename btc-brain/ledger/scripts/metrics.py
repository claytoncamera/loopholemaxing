"""
Compute public accuracy metrics from the ledger and write accuracy.json.

Buckets: by horizon, by model_version, by direction, by regime, plus rolling
7d / 30d / 90d windows.

For every bucket we report:
  - n, hit_rate, brier, logloss, ece
  - baseline_brier / baseline_hit_rate / base_rate  (legacy majority-of-outcome)
  - vs_majority_pp  (hit_rate − max(always_up, always_down) on realized moves)
  - expectancy_bps / expectancy_maker_2bps / expectancy_taker_10bps
  - hit_up / hit_down / n_up / n_down
  - always_up_rate / always_down_rate
  - display_ready

A `display_ready` flag tells the frontend whether the bucket meets the
minimum sample size for public display (default min_n_display=20).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger import Ledger, parse_iso_utc, utc_now_iso  # noqa: E402

METRICS_VERSION = "metrics-v0.2.0"
DEFAULT_MIN_N_DISPLAY = 20
ECE_BINS = 10
MAKER_RT = 0.0002   # 2 bps round-trip
TAKER_RT = 0.0010   # 10 bps round-trip


def _outcome_for(forecast: dict, resolution: dict) -> int:
    return 1 if resolution["direction_correct"] else 0


def _prob_for_direction(forecast: dict) -> float:
    return float(forecast["probability"])


def _signed_return(forecast: dict, resolution: dict) -> float:
    """Return if we took the forecasted direction (no fees)."""
    ret = float(resolution["actual_return"])
    if forecast.get("direction") == "up":
        return ret
    return -ret


def _ece(pairs: list[tuple[float, int]], bins: int = ECE_BINS) -> float | None:
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
    if not pairs:
        return {"baseline_hit_rate": None, "baseline_brier": None, "base_rate": None}
    base_rate = sum(o for _, o in pairs) / len(pairs)
    baseline_hit_rate = max(base_rate, 1 - base_rate)
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
    signed: list[float] = []
    hits = 0
    n_up = n_down = hit_up = hit_down = 0
    realized_up = 0

    for r in rows:
        f, res = r["forecast"], r["resolution"]
        o = _outcome_for(f, res)
        p = _prob_for_direction(f)
        pairs.append((p, o))
        briers.append(float(res["brier_component"]))
        losses.append(float(res["logloss_component"]))
        hits += o
        s = _signed_return(f, res)
        signed.append(s)
        if float(res["actual_return"]) > 0:
            realized_up += 1
        d = f.get("direction")
        if d == "up":
            n_up += 1
            hit_up += o
        elif d == "down":
            n_down += 1
            hit_down += o

    n = len(rows)
    base = _baseline(pairs)
    always_up = (realized_up / n) if n else None
    always_down = (1.0 - always_up) if always_up is not None else None
    majority = None
    if always_up is not None and always_down is not None:
        majority = max(always_up, always_down)
    hit_rate = (hits / n) if n else None
    vs_maj = None
    if hit_rate is not None and majority is not None:
        vs_maj = hit_rate - majority

    exp = statistics.fmean(signed) if signed else None
    exp_bps = (exp * 10000.0) if exp is not None else None
    maker_bps = ((exp - MAKER_RT) * 10000.0) if exp is not None else None
    taker_bps = ((exp - TAKER_RT) * 10000.0) if exp is not None else None

    return {
        "n": n,
        "hit_rate": hit_rate,
        "brier": (statistics.fmean(briers) if briers else None),
        "logloss": (statistics.fmean(losses) if losses else None),
        "ece": _ece(pairs),
        **base,
        "always_up_rate": always_up,
        "always_down_rate": always_down,
        "vs_majority_pp": vs_maj,
        "expectancy_bps": exp_bps,
        "expectancy_maker_2bps": maker_bps,
        "expectancy_taker_10bps": taker_bps,
        "n_up": n_up,
        "n_down": n_down,
        "hit_up": (hit_up / n_up) if n_up else None,
        "hit_down": (hit_down / n_down) if n_down else None,
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

    by_horizon: dict[str, list] = defaultdict(list)
    by_model: dict[str, list] = defaultdict(list)
    by_direction: dict[str, list] = defaultdict(list)
    by_regime: dict[str, list] = defaultdict(list)
    for r in resolved:
        f = r["forecast"]
        by_horizon[f["horizon"]].append(r)
        by_model[f["model_version"]].append(r)
        by_direction[f.get("direction", "unknown")].append(r)
        by_regime[f.get("regime_at_issue") or "unknown"].append(r)

    # Product edge scoreboard: prefer horizons that clear maker fees + beat majority
    scoreboard = []
    for h, rows in sorted(by_horizon.items()):
        m = _bucket_metrics(rows, min_n_display)
        maker = m.get("expectancy_maker_2bps")
        vs = m.get("vs_majority_pp")
        tradeable = bool(
            m["n"] >= min_n_display
            and maker is not None and maker > 0
            and vs is not None and vs > 0
        )
        scoreboard.append({
            "horizon": h,
            "n": m["n"],
            "hit_rate": m["hit_rate"],
            "expectancy_maker_2bps": maker,
            "vs_majority_pp": vs,
            "tradeable": tradeable,
            "rank_key": (maker if maker is not None else -1e9),
        })
    scoreboard.sort(key=lambda x: x["rank_key"], reverse=True)

    out = {
        "schema_version": "2",
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
        "by_direction": {
            d: _bucket_metrics(rows, min_n_display)
            for d, rows in sorted(by_direction.items())
        },
        "by_regime": {
            reg: _bucket_metrics(rows, min_n_display)
            for reg, rows in sorted(by_regime.items())
        },
        "edge_scoreboard": scoreboard,
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
          f"forecasts={metrics['total_forecasts']}, version={METRICS_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
