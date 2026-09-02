"""
Compute public accuracy metrics from the ledger and write accuracy.json.

Buckets: by horizon, by model_version, by (model_version × horizon), by
direction, by regime, plus rolling 7d / 30d / 90d windows.

For every bucket we report:
  - n, hit_rate, brier, logloss, ece, wilson_lb_95
  - baseline_hit_rate  (majority-direction baseline: max(always_up_rate,
    always_down_rate) on realized moves — what "always call the majority
    direction" would score in this bucket)
  - baseline_brier / base_rate  (climatology Brier baseline over the model's
    own hit/miss outcome sequence — Brier-skill reference, NOT a directional
    baseline)
  - vs_majority_pp  ((hit_rate − max(always_up, always_down)) × 100 —
    real percentage points, matching the _pp suffix)
  - expectancy_bps / expectancy_maker_2bps / expectancy_taker_10bps
  - hit_up / hit_down / n_up / n_down
  - always_up_rate / always_down_rate
  - display_ready

A `display_ready` flag tells the frontend whether the bucket meets the
minimum sample size for public display (default min_n_display=20).

v0.3.0 additions (all additive — every v0.2.0 field is preserved):
  - wilson_lb_95 in every bucket (95% Wilson lower bound on hit_rate)
  - top-level `by_model_horizon` all-time buckets keyed "model|horizon"
  - `rolling.by_horizon` and `rolling.by_model_horizon`: per-slice 7d/30d/90d
    compact windows keyed on **issued_at** (the legacy rolling.7d/30d/90d
    global windows stay keyed on resolved_at, unchanged)
  - ECE fixed: 5 quantile bins over predicted probability, n>=50 (the old
    fixed-decile binning was structurally always null on our narrow
    ~[0.50, 0.55] probability range)
  - side artifacts `recent.json` (last 50 joined rows) and `trades.json`
    (the paper trade tape, one group per model|horizon), written next to
    accuracy.json.

v0.3.1 fixes (2026-09-01 — semantics only, no fields added or removed):
  - vs_majority_pp now emits real percentage points. It held a raw fraction
    despite the _pp suffix (-0.0681 meant -6.81pp), so any renderer trusting
    the name showed a ~100× flattering gap (-0.07pp on the NOC wall).
  - baseline_hit_rate is now the majority-direction baseline. It was
    max(base_rate, 1 - base_rate) over the model's OWN hit/miss outcomes,
    which equals hit_rate whenever hit_rate >= 0.5 — a "baseline" that could
    never be beaten and implied a permanent 0.00pp gap. base_rate and
    baseline_brier keep their outcome-sequence (Brier-skill) semantics.
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

METRICS_VERSION = "metrics-v0.3.1"
DEFAULT_MIN_N_DISPLAY = 20
ECE_QUANTILE_BINS = 5
ECE_MIN_N = 50
MAKER_RT = 0.0002   # 2 bps round-trip
TAKER_RT = 0.0010   # 10 bps round-trip
MAKER_RT_BPS = MAKER_RT * 10000.0
RECENT_SCHEMA_VERSION = "recent-v0.1.0"
TRADES_SCHEMA_VERSION = "trades-v0.1.0"
RECENT_ROWS = 50
TRADES_MIN_N = 5
TRADES_LAST_N = 30
ROLLING_WINDOWS_DAYS = (7, 30, 90)


def wilson_lb(p: float, n: int, z: float = 1.96) -> float:
    """95% Wilson score lower bound for a binomial proportion.

    Same math as edge_hunter._wilson_lower — kept here so the metrics module
    has no import edge on the hunter.
    """
    if n <= 0:
        return 0.0
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def model_horizon_key(model_version: str, horizon: str) -> str:
    return f"{model_version}|{horizon}"


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


def _ece(pairs: list[tuple[float, int]],
         bins: int = ECE_QUANTILE_BINS,
         min_n: int = ECE_MIN_N) -> float | None:
    """Expected calibration error over QUANTILE bins of predicted probability.

    Our issued probabilities live in a narrow band (~[0.50, 0.55]), so fixed
    decile bins collapse into a single bucket and ECE was structurally null.
    Quantile bins split the sorted probabilities into `bins` equal-count
    chunks, which is always computable once n >= min_n.
    """
    n = len(pairs)
    if n < min_n:
        return None
    # Group identical probabilities so a tie never straddles two bins —
    # otherwise ECE would depend on the arbitrary order of tied rows.
    groups: dict[float, list[int]] = defaultdict(list)
    for p, o in pairs:
        groups[p].append(o)
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    cum = 0
    for p in sorted(groups):
        outcomes = groups[p]
        idx = min(bins - 1, (cum * bins) // n)
        buckets[idx].extend((p, o) for o in outcomes)
        cum += len(outcomes)
    ece = 0.0
    for chunk in buckets:
        if not chunk:
            continue
        avg_p = sum(p for p, _ in chunk) / len(chunk)
        avg_o = sum(o for _, o in chunk) / len(chunk)
        ece += (len(chunk) / n) * abs(avg_p - avg_o)
    return ece


def _baseline(pairs: list[tuple[float, int]]) -> dict:
    """Climatology Brier baseline over the hit/miss outcome sequence.

    baseline_hit_rate does NOT belong here: pairs carry the model's own
    direction_correct outcomes, so max(base_rate, 1-base_rate) just equals
    hit_rate whenever hit_rate >= 0.5 (the pre-v0.3.1 bug). The directional
    baseline is the majority realized-direction rate — _bucket_metrics sets
    it from always_up/always_down.
    """
    if not pairs:
        return {"baseline_brier": None, "base_rate": None}
    base_rate = sum(o for _, o in pairs) / len(pairs)
    baseline_brier = sum((base_rate - o) ** 2 for _, o in pairs) / len(pairs)
    return {
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
        vs_maj = (hit_rate - majority) * 100.0

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
        "wilson_lb_95": (wilson_lb(hit_rate, n) if hit_rate is not None else None),
        **base,
        "baseline_hit_rate": majority,
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


def dedupe_joined(joined: list[dict]) -> tuple[list[dict], int]:
    """Multi-writer safety: keep ONE forecast per (model_version, horizon,
    issued_at) bucket.

    Since 2026-08-11 the ledger has two writer families — the GitHub Actions
    crons and the Mac-mini launchd issuer (com.btcbrain.issuer). Issuance is
    idempotent against the ledger each writer SEES, but two writers issuing
    the same bucket concurrently on diverged branches can both land after a
    rebase merge, producing two rows with different forecast_ids for one
    bucket. Counting both would double-weight that bucket in every stat and
    every paper trade. Earliest wins: order by issued_at_actual when present
    (real wall-clock), else file order. Deterministic across writers because
    the merged JSONL file order is identical for all readers of a commit.
    """
    seen: dict[tuple, int] = {}
    kept: list[dict] = []
    dropped = 0
    for pos, r in enumerate(joined):
        f = r["forecast"]
        key = (f.get("model_version"), f.get("horizon"), f.get("issued_at"))
        if key not in seen:
            seen[key] = len(kept)
            kept.append(r)
            continue
        # Duplicate bucket: keep the earlier issued_at_actual (fallback:
        # first file occurrence, i.e. the row already kept).
        prev_idx = seen[key]
        prev = kept[prev_idx]["forecast"].get("issued_at_actual")
        cur = f.get("issued_at_actual")
        if prev is not None and cur is not None and cur < prev:
            kept[prev_idx] = r
        dropped += 1
    return kept, dropped


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


def _within_issued(window_days: int, now: datetime, joined: list[dict]) -> list[dict]:
    """Rows whose forecast was ISSUED inside the window (resolved rows only)."""
    cutoff = now - timedelta(days=window_days)
    return [r for r in joined
            if parse_iso_utc(r["forecast"]["issued_at"]) >= cutoff]


def _compact_bucket(rows: list[dict]) -> dict:
    """Small rolling-window bucket: n, hit_rate, brier, expectancy, wilson."""
    n = len(rows)
    if not n:
        return {"n": 0, "hit_rate": None, "brier": None,
                "expectancy_bps": None, "expectancy_maker_2bps": None,
                "wilson_lb_95": None}
    hits = 0
    briers: list[float] = []
    signed: list[float] = []
    for r in rows:
        f, res = r["forecast"], r["resolution"]
        hits += _outcome_for(f, res)
        briers.append(float(res["brier_component"]))
        signed.append(_signed_return(f, res))
    hit_rate = hits / n
    exp = statistics.fmean(signed)
    return {
        "n": n,
        "hit_rate": hit_rate,
        "brier": statistics.fmean(briers),
        "expectancy_bps": exp * 10000.0,
        "expectancy_maker_2bps": (exp - MAKER_RT) * 10000.0,
        "wilson_lb_95": wilson_lb(hit_rate, n),
    }


def _rolling_windows_issued(rows: list[dict], now: datetime) -> dict:
    """{"7d": compact, "30d": compact, "90d": compact} keyed on issued_at."""
    return {
        f"{d}d": _compact_bucket(_within_issued(d, now, rows))
        for d in ROLLING_WINDOWS_DAYS
    }


def build(root: Path, min_n_display: int = DEFAULT_MIN_N_DISPLAY) -> dict:
    ledger = Ledger.at(root)
    joined_all, duplicate_rows_ignored = dedupe_joined(ledger.joined())
    resolved = _filter_resolved(joined_all)
    now = datetime.now(timezone.utc)

    by_horizon: dict[str, list] = defaultdict(list)
    by_model: dict[str, list] = defaultdict(list)
    by_model_horizon: dict[str, list] = defaultdict(list)
    by_direction: dict[str, list] = defaultdict(list)
    by_regime: dict[str, list] = defaultdict(list)
    for r in resolved:
        f = r["forecast"]
        by_horizon[f["horizon"]].append(r)
        by_model[f["model_version"]].append(r)
        by_model_horizon[model_horizon_key(f["model_version"], f["horizon"])].append(r)
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
        # Multi-writer safety (GHA crons + mini launchd issuer): duplicate
        # (model, horizon, issued_at) buckets are counted once, earliest
        # issuance wins. Nonzero here means a concurrent-issue race landed
        # twice in the append-only file — harmless to stats, visible here.
        "duplicate_rows_ignored": duplicate_rows_ignored,
        "by_horizon": {
            h: _bucket_metrics(rows, min_n_display)
            for h, rows in sorted(by_horizon.items())
        },
        "by_model_version": {
            m: _bucket_metrics(rows, min_n_display)
            for m, rows in sorted(by_model.items())
        },
        # All-time (model_version × horizon) buckets, keyed "model|horizon".
        # This is the bucket the signal gate evaluates.
        "by_model_horizon": {
            k: _bucket_metrics(rows, min_n_display)
            for k, rows in sorted(by_model_horizon.items())
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
            # Legacy global windows — keyed on resolved_at, unchanged.
            "7d": _bucket_metrics(_within(7, now, resolved), min_n_display),
            "30d": _bucket_metrics(_within(30, now, resolved), min_n_display),
            "90d": _bucket_metrics(_within(90, now, resolved), min_n_display),
            # v0.3.0: per-slice windows keyed on issued_at (a per-horizon
            # rolling gate must not mix horizons or leak on resolve lag).
            "window_basis": {
                "7d": "resolved_at", "30d": "resolved_at", "90d": "resolved_at",
                "by_horizon": "issued_at", "by_model_horizon": "issued_at",
            },
            "by_horizon": {
                h: _rolling_windows_issued(rows, now)
                for h, rows in sorted(by_horizon.items())
            },
            "by_model_horizon": {
                k: _rolling_windows_issued(rows, now)
                for k, rows in sorted(by_model_horizon.items())
            },
        },
        "global": _bucket_metrics(resolved, min_n_display),
    }
    return out


def build_recent(root: Path, limit: int = RECENT_ROWS) -> dict:
    """Small joined tape for the site: last `limit` forecasts, newest first.

    Replaces the site's 2MB raw-JSONL download for its 25-row table.
    """
    ledger = Ledger.at(root)
    joined, _dupes = dedupe_joined(ledger.joined())
    total_issued = len(joined)
    total_resolved = sum(
        1 for r in joined
        if r["resolution"] and r["resolution"].get("status") == "resolved")
    joined.sort(key=lambda r: (r["forecast"].get("issued_at", ""),
                               r["forecast"].get("forecast_id", "")),
                reverse=True)
    rows = []
    for r in joined[:limit]:
        f, res = r["forecast"], r["resolution"]
        resolved = bool(res and res.get("status") == "resolved")
        rows.append({
            "forecast_id": f["forecast_id"],
            "issued_at": f["issued_at"],
            "model_version": f["model_version"],
            "horizon": f["horizon"],
            "direction": f["direction"],
            "probability": f["probability"],
            "entry_price": f["entry_price"],
            "target_time": f["target_time"],
            "resolved": resolved,
            "actual_close": (res["actual_close"] if resolved else None),
            "actual_return_bps": (float(res["actual_return"]) * 10000.0
                                  if resolved else None),
            "direction_correct": (res["direction_correct"] if resolved else None),
            "resolved_at": (res["resolved_at"] if resolved else None),
        })
    return {
        "schema_version": RECENT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "total_issued": total_issued,
        "total_resolved": total_resolved,
        "rows": rows,
    }


def build_trades(root: Path,
                 min_n: int = TRADES_MIN_N,
                 last_n: int = TRADES_LAST_N) -> dict:
    """Paper trade tape: every resolved forecast is one 1-unit paper trade.

    ret_bps_gross = signed return in the forecasted direction (bps);
    ret_bps_maker = ret_bps_gross − 2 bps maker round-trip.
    One group per (model_version × horizon) with n >= min_n, trades in
    issued_at order, cumulative maker curve + drawdown per group.
    """
    ledger = Ledger.at(root)
    deduped, _dupes = dedupe_joined(ledger.joined())
    resolved = _filter_resolved(deduped)

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in resolved:
        f = r["forecast"]
        grouped[(f["model_version"], f["horizon"])].append(r)

    groups = []
    for (model, horizon), rows in sorted(grouped.items()):
        if len(rows) < min_n:
            continue
        rows.sort(key=lambda r: (r["forecast"].get("issued_at", ""),
                                 r["forecast"].get("forecast_id", "")))
        trades = []
        curve = []
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        wins = 0
        for r in rows:
            f, res = r["forecast"], r["resolution"]
            gross = _signed_return(f, res) * 10000.0
            maker = gross - MAKER_RT_BPS
            win = bool(res["direction_correct"])
            wins += 1 if win else 0
            cum += maker
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
            curve.append([int(parse_iso_utc(f["issued_at"]).timestamp()),
                          round(cum, 4)])
            trades.append({
                "issued_at": f["issued_at"],
                "direction": f["direction"],
                "probability": f["probability"],
                "entry_price": f["entry_price"],
                "exit_price": res["actual_close"],
                "ret_bps_gross": round(gross, 4),
                "ret_bps_maker": round(maker, 4),
                "win": win,
            })
        n = len(rows)
        groups.append({
            "model_version": model,
            "horizon": horizon,
            "n": n,
            "wins": wins,
            "hit_rate": wins / n,
            "sum_bps_maker": round(cum, 4),
            "avg_bps_maker": round(cum / n, 4),
            "max_drawdown_bps_maker": round(max_dd, 4),
            "curve": curve,
            "last_trades": trades[-last_n:],
        })

    return {
        "schema_version": TRADES_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "fee_bps": {"maker_rt": 2, "taker_rt": 10},
        "groups": groups,
    }


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--out", required=True, help="output accuracy.json path")
    ap.add_argument("--min-n-display", type=int, default=DEFAULT_MIN_N_DISPLAY)
    ap.add_argument("--recent-out", default=None,
                    help="recent.json path (default: recent.json next to --out)")
    ap.add_argument("--trades-out", default=None,
                    help="trades.json path (default: trades.json next to --out)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    metrics = build(root, min_n_display=args.min_n_display)
    out_path = Path(args.out)
    _write_json(out_path, metrics)
    print(f"wrote {out_path} (resolved={metrics['total_resolved']}, "
          f"forecasts={metrics['total_forecasts']}, version={METRICS_VERSION})")

    recent_path = Path(args.recent_out) if args.recent_out \
        else out_path.parent / "recent.json"
    recent = build_recent(root)
    _write_json(recent_path, recent)
    print(f"wrote {recent_path} (rows={len(recent['rows'])})")

    trades_path = Path(args.trades_out) if args.trades_out \
        else out_path.parent / "trades.json"
    trades = build_trades(root)
    _write_json(trades_path, trades)
    print(f"wrote {trades_path} (groups={len(trades['groups'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
