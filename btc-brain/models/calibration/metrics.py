"""
Metric helpers shared across baselines and the logistic model.

All metrics here are pure stdlib and work on (probabilities, outcomes ∈ {0,1})
pairs. They are re-derivations of the same definitions used in the Phase 1
ledger metrics (`btc-brain/ledger/scripts/metrics.py`) — duplicated here to
keep the model layer free of upward imports.
"""
from __future__ import annotations

import math
from typing import Optional

EPS = 1e-6


def _clip(p: float) -> float:
    return min(max(p, EPS), 1 - EPS)


def hit_rate(probs: list[float], y: list[int], threshold: float = 0.5) -> float:
    if not probs:
        return 0.0
    correct = 0
    for p, o in zip(probs, y):
        pred = 1 if p >= threshold else 0
        if pred == o:
            correct += 1
    return correct / len(probs)


def brier(probs: list[float], y: list[int]) -> float:
    if not probs:
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(probs, y)) / len(probs)


def log_loss(probs: list[float], y: list[int]) -> float:
    if not probs:
        return 0.0
    s = 0.0
    for p, o in zip(probs, y):
        p = _clip(p)
        s += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return s / len(probs)


def reliability_diagram(
    probs: list[float], y: list[int], bins: int = 10
) -> list[dict]:
    """Per-bin (avg_prob, avg_outcome, count). Empty bins included as zeros."""
    if not probs:
        return []
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, o in zip(probs, y):
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, o))
    out = []
    for k, b in enumerate(buckets):
        if not b:
            out.append({
                "bin": k,
                "lower": k / bins,
                "upper": (k + 1) / bins,
                "count": 0,
                "avg_prob": None,
                "avg_outcome": None,
            })
            continue
        out.append({
            "bin": k,
            "lower": k / bins,
            "upper": (k + 1) / bins,
            "count": len(b),
            "avg_prob": sum(p for p, _ in b) / len(b),
            "avg_outcome": sum(o for _, o in b) / len(b),
        })
    return out


def expected_calibration_error(
    probs: list[float], y: list[int], bins: int = 10, min_n: int = 20
) -> Optional[float]:
    """ECE — None if too few samples or fewer than 3 non-empty bins."""
    if len(probs) < min_n:
        return None
    rd = reliability_diagram(probs, y, bins=bins)
    nonempty = [b for b in rd if b["count"] > 0]
    if len(nonempty) < 3:
        return None
    n = len(probs)
    ece = 0.0
    for b in nonempty:
        ece += (b["count"] / n) * abs(b["avg_prob"] - b["avg_outcome"])
    return ece


def baseline_delta(
    model_brier: float,
    baseline_brier: float,
) -> float:
    """Brier improvement vs baseline. Positive = model better."""
    return baseline_brier - model_brier


def base_rate(y: list[int]) -> float:
    if not y:
        return 0.5
    return sum(y) / len(y)


def regime_sliced(
    probs: list[float],
    y: list[int],
    regimes: list[str],
) -> dict:
    """Hit-rate / brier sliced by regime label."""
    out: dict = {}
    by: dict[str, list[tuple[float, int]]] = {}
    for p, o, r in zip(probs, y, regimes):
        by.setdefault(r or "unknown", []).append((p, o))
    for r, rows in by.items():
        ps = [p for p, _ in rows]
        os_ = [o for _, o in rows]
        out[r] = {
            "n": len(rows),
            "hit_rate": hit_rate(ps, os_),
            "brier": brier(ps, os_),
            "log_loss": log_loss(ps, os_),
            "base_rate": base_rate(os_),
        }
    return out


def evaluate(
    probs: list[float],
    y: list[int],
    regimes: Optional[list[str]] = None,
    baseline_briers: Optional[dict[str, float]] = None,
) -> dict:
    """Full metric pack for one (probs, y) set."""
    rd = reliability_diagram(probs, y)
    out = {
        "n": len(probs),
        "hit_rate": hit_rate(probs, y),
        "brier": brier(probs, y),
        "log_loss": log_loss(probs, y),
        "ece": expected_calibration_error(probs, y),
        "base_rate": base_rate(y),
        "reliability": rd,
    }
    if regimes is not None:
        out["regime_sliced"] = regime_sliced(probs, y, regimes)
    if baseline_briers:
        out["baseline_delta"] = {
            name: baseline_delta(out["brier"], b) for name, b in baseline_briers.items()
        }
    return out
