"""
Probability calibrators — Platt scaling and isotonic regression.

Both are fit on out-of-fold (OOF) predictions only — the caller is
responsible for collecting those across the walk-forward folds, never
across rows that leaked into training.

  * PlattScaler          fits a 1-D logistic regression on (logit(p_raw), y)
  * IsotonicRegressor    fits a non-decreasing step function on (p_raw, y)
                         using the pool-adjacent-violators algorithm.

`fit(p_raw, y)` learns the mapping. `transform(p)` applies it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-6


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class PlattScaler:
    a: float = 1.0
    b: float = 0.0
    n_iters: int = 200
    lr: float = 0.1
    name: str = "platt"

    def fit(self, p_raw: list[float], y: list[int]) -> "PlattScaler":
        if not p_raw:
            return self
        zs = [_logit(p) for p in p_raw]
        a, b = 1.0, 0.0
        n = len(zs)
        for _ in range(self.n_iters):
            ga, gb = 0.0, 0.0
            for z, t in zip(zs, y):
                p = _sigmoid(a * z + b)
                err = p - t
                ga += err * z
                gb += err
            a -= self.lr * ga / n
            b -= self.lr * gb / n
        self.a = a
        self.b = b
        return self

    def transform(self, p_raw: list[float]) -> list[float]:
        if not p_raw:
            return []
        return [_sigmoid(self.a * _logit(p) + self.b) for p in p_raw]


@dataclass
class IsotonicRegressor:
    """Pool-adjacent-violators isotonic (non-decreasing) regression."""

    xs: list[float] | None = None
    ys: list[float] | None = None
    name: str = "isotonic"

    def fit(self, p_raw: list[float], y: list[int]) -> "IsotonicRegressor":
        if not p_raw:
            self.xs = []
            self.ys = []
            return self
        # Sort by p_raw.
        pairs = sorted(zip(p_raw, y), key=lambda r: r[0])
        xs = [p for p, _ in pairs]
        targets = [float(t) for _, t in pairs]
        weights = [1.0 for _ in pairs]
        # PAV.
        i = 0
        n = len(xs)
        # Use lists as a stack of (value, weight, lo_idx, hi_idx).
        stack: list[list] = []
        for k in range(n):
            cur = [targets[k], weights[k], k, k]
            while stack and stack[-1][0] >= cur[0]:
                top = stack.pop()
                # merge
                tot_w = top[1] + cur[1]
                merged_val = (top[0] * top[1] + cur[0] * cur[1]) / tot_w
                cur = [merged_val, tot_w, top[2], cur[3]]
            stack.append(cur)
        # Flatten back into ys aligned to xs.
        ys = [0.0] * n
        for val, _w, lo, hi in stack:
            for j in range(lo, hi + 1):
                ys[j] = val
        self.xs = xs
        self.ys = ys
        return self

    def transform(self, p_raw: list[float]) -> list[float]:
        if self.xs is None or not self.xs:
            return list(p_raw)
        xs = self.xs
        ys = self.ys or []
        out = []
        for p in p_raw:
            # Binary search for first xs[i] >= p
            lo, hi = 0, len(xs) - 1
            if p <= xs[0]:
                out.append(ys[0])
                continue
            if p >= xs[-1]:
                out.append(ys[-1])
                continue
            while lo < hi:
                mid = (lo + hi) // 2
                if xs[mid] < p:
                    lo = mid + 1
                else:
                    hi = mid
            # Linear interpolate between (xs[lo-1], ys[lo-1]) and (xs[lo], ys[lo]).
            x1, y1 = xs[lo - 1], ys[lo - 1]
            x2, y2 = xs[lo], ys[lo]
            if x2 == x1:
                out.append(y2)
            else:
                t = (p - x1) / (x2 - x1)
                out.append(y1 + t * (y2 - y1))
        # Clip to [0,1].
        return [min(max(p, 0.0), 1.0) for p in out]
