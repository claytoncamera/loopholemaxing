"""
Baseline probability emitters.

Each baseline implements:
    fit(X_train, y_train, meta_train) -> self
    predict_proba(X_test, meta_test) -> list[float]    # P(y=1)

Where `meta_*` is a list of per-row dicts containing at least:
    {"close": float, "prev_close": float, "rsi": float, "ema_distance": float,
     "regime": "bull"|"bear"|"chop"|"unknown"}

Implementations are deterministic where possible (random uses a seeded RNG)
and never call out to the network.

Listed baselines:
  * RandomBaseline       — coin flip (seeded)
  * MajorityBaseline     — predict the train base rate of `up`
  * LastDirectionBaseline— predict P(up)=0.5 + small boost in direction of
                            the most recent observed return.
  * MomentumBaseline     — proportional to recent log-return sign+magnitude.
  * MeanReversionBaseline— inverse of momentum.
  * SIIELiteBaseline     — *defensible* extraction of the existing public
                            SIIE intuition: trend-up if close>EMA AND
                            RSI in (40, 70); trend-down if close<EMA AND
                            RSI in (30, 60); else neutral. NO browser/
                            localStorage coupling — uses only feature meta.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


def _clip(p: float, lo: float = 0.05, hi: float = 0.95) -> float:
    return max(lo, min(hi, p))


@dataclass
class _BaseModel:
    name: str = "baseline"

    def fit(self, X, y, meta):
        return self

    def predict_proba(self, X, meta):
        raise NotImplementedError


class RandomBaseline(_BaseModel):
    name = "random"

    def __init__(self, seed: int = 1337):
        self.rng = random.Random(seed)

    def predict_proba(self, X, meta):
        return [self.rng.random() for _ in X]


class MajorityBaseline(_BaseModel):
    name = "majority"

    def __init__(self):
        self.base_rate = 0.5

    def fit(self, X, y, meta):
        if y:
            self.base_rate = sum(y) / len(y)
        return self

    def predict_proba(self, X, meta):
        return [_clip(self.base_rate) for _ in X]


class LastDirectionBaseline(_BaseModel):
    name = "last_direction"

    def predict_proba(self, X, meta):
        out = []
        for m in meta:
            r = float(m.get("log_return_1", 0.0))
            if r > 0:
                out.append(_clip(0.55))
            elif r < 0:
                out.append(_clip(0.45))
            else:
                out.append(0.5)
        return out


class MomentumBaseline(_BaseModel):
    """P(up) = sigmoid(scale * recent log-return)."""

    name = "momentum"

    def __init__(self, scale: float = 25.0):
        self.scale = scale

    def predict_proba(self, X, meta):
        out = []
        for m in meta:
            r = float(m.get("log_return_1", 0.0))
            z = self.scale * r
            p = 1.0 / (1.0 + math.exp(-z))
            out.append(_clip(p))
        return out


class MeanReversionBaseline(_BaseModel):
    """P(up) = sigmoid(-scale * recent log-return)."""

    name = "mean_reversion"

    def __init__(self, scale: float = 25.0):
        self.scale = scale

    def predict_proba(self, X, meta):
        out = []
        for m in meta:
            r = float(m.get("log_return_1", 0.0))
            z = -self.scale * r
            p = 1.0 / (1.0 + math.exp(-z))
            out.append(_clip(p))
        return out


class SIIELiteBaseline(_BaseModel):
    """Decoupled, fully reproducible echo of the public SIIE intuition.

    We do NOT read browser state. We use only feature-meta values:
      * `ema_distance`: (close - EMA) / EMA
      * `rsi`: 0..1 (normalized)
      * `regime`: bull|bear|chop|unknown
    """

    name = "siie_lite"

    def predict_proba(self, X, meta):
        out = []
        for m in meta:
            ema_d = float(m.get("ema_distance", 0.0))
            rsi = float(m.get("rsi", 0.5))   # already normalized 0..1
            regime = str(m.get("regime", "unknown"))
            score = 0.5
            # Trend-following bias from EMA distance.
            score += 0.5 * math.tanh(8.0 * ema_d)  # bounded in (-0.5, +0.5)
            # RSI band tilt.
            if 0.40 < rsi < 0.70:
                score += 0.05
            elif 0.30 < rsi < 0.60:
                score -= 0.02
            # Regime tilt.
            if regime == "bull":
                score += 0.03
            elif regime == "bear":
                score -= 0.03
            out.append(_clip(score))
        return out


ALL_BASELINES = [
    RandomBaseline,
    MajorityBaseline,
    LastDirectionBaseline,
    MomentumBaseline,
    MeanReversionBaseline,
    SIIELiteBaseline,
]
