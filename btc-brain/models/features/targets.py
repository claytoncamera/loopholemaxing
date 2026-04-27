"""
Target builders.

Direction targets for horizons 1h / 4h / 12h / 24h. The horizon is expressed
in *bars* relative to the input candle series. For a 1h candle series:
  H=1  → 1h target
  H=4  → 4h target
  H=12 → 12h target
  H=24 → 24h target

Target rule (binary):
  y_t = 1 if close[t+H] > close[t] else 0
The pair (X[t], y_t) is dropped when t+H is out of range. This guarantees
no same-bar lookahead — features at t never use bar t+H, and targets at t
are only retained if a *future* close is available *now*.
"""
from __future__ import annotations

from dataclasses import dataclass


HORIZON_BARS = {
    "1h": 1,
    "4h": 4,
    "12h": 12,
    "24h": 24,
}


@dataclass
class TargetVector:
    horizon: str
    h_bars: int
    y: list[int]                     # length matches valid_indices
    valid_indices: list[int]         # indices into the source feature frame
    target_close_idx: list[int]      # index of close used to resolve the label

    def n(self) -> int:
        return len(self.y)


def build_direction_target(closes: list[float], horizon: str) -> TargetVector:
    """Build (y, valid_indices) for the named horizon.

    Drops the trailing H bars (no future close available).
    """
    if horizon not in HORIZON_BARS:
        raise ValueError(f"unknown horizon: {horizon}")
    h = HORIZON_BARS[horizon]
    y: list[int] = []
    valid: list[int] = []
    target_idx: list[int] = []
    for t in range(len(closes) - h):
        c0 = closes[t]
        c1 = closes[t + h]
        if c0 <= 0 or c1 <= 0:
            continue
        y.append(1 if c1 > c0 else 0)
        valid.append(t)
        target_idx.append(t + h)
    return TargetVector(
        horizon=horizon,
        h_bars=h,
        y=y,
        valid_indices=valid,
        target_close_idx=target_idx,
    )
