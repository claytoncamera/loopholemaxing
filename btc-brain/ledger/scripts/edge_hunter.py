"""
BTC Brain continuous edge hunter.

Scans the live forecast ledger for slices with positive fee-adjusted expectancy
and hit-rate lift vs majority, ranks them, and writes a public edge_report.json
so the brain keeps hunting higher win rates every metrics cycle.

This does NOT auto-promote models. It only publishes ranked hypotheses and
next experiments for humans / future candidate issuers.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger import Ledger, parse_iso_utc, utc_now_iso  # noqa: E402

EDGE_HUNTER_VERSION = "edge-hunter-v0.1.0"
MAKER_RT = 0.0002
MIN_N = 20
MIN_N_EXPLORE = 12  # exploratory slices (hour/DOW) can be thinner


def _wilson_lower(p: float, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _signed(f: dict, res: dict) -> float:
    ret = float(res["actual_return"])
    return ret if f.get("direction") == "up" else -ret


def _parse_rel(reason: str | None) -> float | None:
    if not reason:
        return None
    m = re.search(r"rel=([0-9.]+)", reason)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _slice_metrics(rows: list[tuple[dict, dict]], min_n: int) -> dict | None:
    if len(rows) < min_n:
        return None
    hits = []
    signed = []
    realized_up = 0
    for f, res in rows:
        hits.append(1 if res.get("direction_correct") else 0)
        signed.append(_signed(f, res))
        if float(res["actual_return"]) > 0:
            realized_up += 1
    n = len(rows)
    hit = statistics.fmean(hits)
    always_up = realized_up / n
    majority = max(always_up, 1 - always_up)
    exp = statistics.fmean(signed)
    maker = exp - MAKER_RT
    return {
        "n": n,
        "hit_rate": hit,
        "wilson_lb_95": _wilson_lower(hit, n),
        "vs_majority_pp": hit - majority,
        "expectancy_bps": exp * 10000.0,
        "expectancy_maker_2bps": maker * 10000.0,
        "majority_rate": majority,
        "score": (maker * 10000.0) + 50.0 * (hit - majority) + 10.0 * _wilson_lower(hit, n),
    }


def hunt(root: Path) -> dict:
    ledger = Ledger.at(root)
    resolved = [
        (j["forecast"], j["resolution"])
        for j in ledger.joined()
        if j["resolution"] and j["resolution"].get("status") == "resolved"
    ]

    slices: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

    for f, res in resolved:
        h = f.get("horizon", "?")
        d = f.get("direction", "?")
        reg = f.get("regime_at_issue") or "unknown"
        mv = f.get("model_version", "?")
        slices[f"horizon={h}"].append((f, res))
        slices[f"horizon={h}|dir={d}"].append((f, res))
        slices[f"horizon={h}|regime={reg}"].append((f, res))
        slices[f"model={mv}|horizon={h}"].append((f, res))
        slices[f"dir={d}"].append((f, res))
        slices[f"regime={reg}"].append((f, res))

        try:
            issued = parse_iso_utc(f["issued_at"])
            slices[f"hour_utc={issued.hour:02d}"].append((f, res))
            slices[f"dow={issued.weekday()}"].append((f, res))
            slices[f"horizon={h}|hour_utc={issued.hour:02d}"].append((f, res))
            slices[f"horizon={h}|dow={issued.weekday()}"].append((f, res))
        except Exception:
            pass

        rel = _parse_rel(f.get("confidence_reason"))
        if rel is not None:
            if rel < 0.001:
                bucket = "rel<0.1%"
            elif rel < 0.003:
                bucket = "rel_0.1-0.3%"
            elif rel < 0.005:
                bucket = "rel_0.3-0.5%"
            elif rel < 0.01:
                bucket = "rel_0.5-1%"
            else:
                bucket = "rel>=1%"
            slices[f"sma_{bucket}"].append((f, res))
            slices[f"horizon={h}|sma_{bucket}"].append((f, res))

    # Policy filters to test as candidate edges
    for f, res in resolved:
        if f.get("horizon") not in ("12h", "24h"):
            continue
        slices["policy:h12_24_only"].append((f, res))
        try:
            hr = parse_iso_utc(f["issued_at"]).hour
            if hr != 20:
                slices["policy:h12_24_skip_hour20"].append((f, res))
        except Exception:
            pass
        rel = _parse_rel(f.get("confidence_reason"))
        if rel is not None and rel < 0.005:
            slices["policy:h12_24_mild_rel"].append((f, res))

    ranked = []
    for name, rows in slices.items():
        min_n = MIN_N_EXPLORE if ("hour_utc=" in name or "dow=" in name) else MIN_N
        m = _slice_metrics(rows, min_n=min_n)
        if not m:
            continue
        # Keep positive maker expectancy OR solid hit lift
        if m["expectancy_maker_2bps"] <= 0 and m["vs_majority_pp"] <= 0:
            continue
        ranked.append({"slice": name, **m})

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # Top tradeable: maker>0, vs_maj>0, n>=MIN_N, wilson_lb>=0.52 preferred
    tradeable = [
        r for r in ranked
        if r["n"] >= MIN_N
        and r["expectancy_maker_2bps"] > 0
        and r["vs_majority_pp"] > 0
    ]

    best = tradeable[0] if tradeable else (ranked[0] if ranked else None)

    experiments = []
    # Always push the autopsy core hypotheses
    experiments.append({
        "id": "exp-24h-primary",
        "hypothesis": "24h SMA direction is the primary fee-surviving edge",
        "action": "Keep dual-issuer policy24 on 12h/24h; never promote 1h",
        "priority": 1,
    })
    experiments.append({
        "id": "exp-invert-confidence",
        "hypothesis": "High SMA |rel| confidence is inverted — mild divergence wins more",
        "action": "policy24 uses inverted confidence mapping (already live if dual-issuer on)",
        "priority": 2,
    })
    experiments.append({
        "id": "exp-skip-toxic-hours",
        "hypothesis": "Hour 20 UTC underperforms — filter improves expectancy",
        "action": "Shadow-compare policy skip-hour20 vs baseline on rolling 30d",
        "priority": 3,
    })
    experiments.append({
        "id": "exp-regime-conditional",
        "hypothesis": "Edge concentrates in specific regimes (bull/bear/chop)",
        "action": "Once regime labels accumulate, promote regime-gated candidate if maker>0",
        "priority": 4,
    })
    experiments.append({
        "id": "exp-ml-candidate",
        "hypothesis": "Logistic/SIIE features beat SMA on 24h OOS Brier",
        "action": "Run Phase 3 walk-forward on live candles; dual-issue if beats SMA",
        "priority": 5,
    })

    # Auto-suggest top novel slices not already core
    for r in tradeable[:8]:
        if r["slice"].startswith("horizon=") and "|" not in r["slice"]:
            continue
        experiments.append({
            "id": f"auto-{abs(hash(r['slice'])) % 10_000_000:07d}",
            "hypothesis": f"Slice `{r['slice']}` shows maker={r['expectancy_maker_2bps']:.1f}bps hit={r['hit_rate']:.3f} n={r['n']}",
            "action": "Validate OOS next 14d before encoding into issuer policy",
            "priority": 10,
            "evidence": {
                "hit_rate": r["hit_rate"],
                "wilson_lb_95": r["wilson_lb_95"],
                "expectancy_maker_2bps": r["expectancy_maker_2bps"],
                "vs_majority_pp": r["vs_majority_pp"],
                "n": r["n"],
            },
        })

    # Target: always try to beat current best 24h hit
    h24 = next((r for r in ranked if r["slice"] == "horizon=24h"), None)
    target = {
        "metric": "horizon=24h hit_rate",
        "current": h24["hit_rate"] if h24 else None,
        "current_n": h24["n"] if h24 else 0,
        "stretch_goal": 0.65,
        "hard_goal": 0.70,
        "note": "Continuous improvement target — do not claim until n>=100 and wilson_lb clears 0.55",
    }

    return {
        "schema_version": "1",
        "edge_hunter_version": EDGE_HUNTER_VERSION,
        "generated_at": utc_now_iso(),
        "total_resolved_scanned": len(resolved),
        "min_n_display": MIN_N,
        "best_tradeable_slice": best,
        "improvement_target": target,
        "top_tradeable": tradeable[:25],
        "top_exploratory": ranked[:40],
        "next_experiments": experiments[:20],
        "notes": [
            "Edge hunter never auto-promotes. It ranks hypotheses for dual-issuer / Phase 3.",
            "Maker fee assumption = 2 bps round-trip.",
            "Prefer slices with vs_majority_pp>0 to avoid pure bull-bias artifacts.",
        ],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="ledger data dir")
    ap.add_argument("--out", required=True, help="output edge_report.json path")
    args = ap.parse_args(argv)
    report = hunt(Path(args.root))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    best = report.get("best_tradeable_slice")
    if best:
        print(f"wrote {out} best={best['slice']} hit={best['hit_rate']:.3f} "
              f"maker_bps={best['expectancy_maker_2bps']:.1f} n={best['n']}")
    else:
        print(f"wrote {out} (no tradeable slice yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
