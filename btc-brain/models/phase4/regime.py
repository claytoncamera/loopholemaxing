"""
Phase 4 — Lightweight regime detector.

Goals
-----
* Operate on closed-candle close prices (Phase 0/2 invariant: never inspect
  an in-progress bar).
* Use *filtered/current* information only — at bar ``t`` the assigned regime
  may depend only on closes ``[0..t]``. There is no Viterbi/forward-backward
  smoothing pass that would let bar ``t``'s label peek at bars ``> t``.
* No heavy dependencies. Pure stdlib so it runs in the same environment as
  the rest of the BTC Brain Python code.

Rather than a full HMM (which needs numpy + an EM loop and pulls in
``hmmlearn`` or similar), this module implements an equivalent lightweight
regime detector built from two deterministic, rolling-window signals on
log-returns:

* **Trend score**  — the EMA of log-returns over a slow window. Positive
  values lean bull, negative values lean bear, near-zero values lean chop.
* **Volatility score** — the trailing realized std of log-returns over a
  short window, compared against the median of itself across the available
  history *up to and including bar t* (so it stays causal).

These two signals are bucketed into four regime states::

    trend_up_high_vol     trend_up_low_vol
    trend_down_high_vol   trend_down_low_vol
    chop_high_vol         chop_low_vol

The "chop" trend bucket fires when the trend score is within a small
``trend_eps`` band around zero.

Each assignment also exposes a coarse 4-class label that maps onto the
existing Phase 0/2 vocabulary (``bull``, ``bear``, ``chop``, ``unknown``)
so the rest of the pipeline (registry, ledger, calibration) keeps working
without schema changes:

* trend_up_*    → ``bull``
* trend_down_*  → ``bear``
* chop_*        → ``chop``
* unable to score (warmup) → ``unknown``

The detector is deterministic — same closes in, same regimes out. No
randomness, no fitting on test data, no future leakage. Tests in
``tests/test_phase4.py`` lock these invariants.

Lightweight substitute disclosure
---------------------------------
This is documented as a *lightweight substitute* for an HMM. We chose this
path because:

* hmmlearn / pomegranate / numpy are not currently runtime dependencies.
* The Phase 4 mission specifies "HMM/regime detector or equivalent
  lightweight regime detector" with a preference for no-heavy-dependency.
* The two-signal scheme captures the trend/chop × high/low-vol product
  the spec asks for, while remaining transparent and easy to audit.

See ``btc-brain/models/phase4/README.md`` for the governance/promotion
gates that consume regime labels.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


REGIME_DETECTOR_VERSION = "phase4-regime-v0.1.0"

# Coarse 4-class label that downstream code (ledger, features) already knows.
COARSE_LABELS = ("bull", "bear", "chop", "unknown")

# Fine 6-class label (trend × volatility).
FINE_LABELS = (
    "trend_up_high_vol",
    "trend_up_low_vol",
    "trend_down_high_vol",
    "trend_down_low_vol",
    "chop_high_vol",
    "chop_low_vol",
    "unknown",
)


@dataclass
class RegimeAssignment:
    """One causal regime label per bar in the input series."""

    coarse: list[str]                 # length == len(closes)
    fine: list[str]                   # length == len(closes)
    trend_score: list[float]          # EMA of log-returns at bar t
    vol_score: list[float]            # rolling std of log-returns at bar t
    vol_high_threshold: list[float]   # causal median(vol[0..t]) used at bar t
    warmup_n: int                     # number of bars labelled `unknown`
    version: str = REGIME_DETECTOR_VERSION
    config: dict = field(default_factory=dict)


def _log_returns(closes: list[float]) -> list[float]:
    """Bar-to-bar log returns. r[0] = 0.0 by construction."""
    n = len(closes)
    out = [0.0] * n
    for i in range(1, n):
        a = closes[i - 1]
        b = closes[i]
        if a > 0 and b > 0:
            out[i] = math.log(b / a)
        else:
            out[i] = 0.0
    return out


def _ema_causal(values: list[float], n: int) -> list[float]:
    """Causal EMA. ``out[i]`` only depends on ``values[0..i]``."""
    if n <= 1 or not values:
        return list(values)
    k = 2.0 / (n + 1.0)
    out: list[float] = []
    seed = values[0]
    for i, v in enumerate(values):
        if i == 0:
            out.append(seed)
        else:
            out.append(v * k + out[-1] * (1 - k))
    return out


def _rolling_std(values: list[float], window: int) -> list[float]:
    """Causal trailing std over ``window`` samples."""
    n = len(values)
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - window + 1)
        seg = values[lo : i + 1]
        if len(seg) < 2:
            continue
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / (len(seg) - 1)
        out[i] = math.sqrt(var)
    return out


def _causal_median(values: list[float]) -> list[float]:
    """``out[i]`` = median of ``values[0..i]`` (inclusive). Causal — never
    inspects ``values[i+1:]``."""
    n = len(values)
    out = [0.0] * n
    sorted_buf: list[float] = []
    import bisect

    for i, v in enumerate(values):
        bisect.insort(sorted_buf, v)
        m = len(sorted_buf)
        if m == 0:
            out[i] = 0.0
        elif m % 2 == 1:
            out[i] = sorted_buf[m // 2]
        else:
            out[i] = 0.5 * (sorted_buf[m // 2 - 1] + sorted_buf[m // 2])
    return out


def detect_regimes(
    closes: list[float],
    trend_window: int = 24,
    vol_window: int = 24,
    trend_eps: float = 1e-4,
    warmup_bars: int = 24,
) -> RegimeAssignment:
    """Return a per-bar causal regime assignment.

    Parameters
    ----------
    closes:
        Closed-candle close prices, ascending in time. Caller must have
        already dropped any in-progress candle (Phase 0/2 invariant).
    trend_window:
        EMA window for the trend score (in bars).
    vol_window:
        Trailing window for the realized-vol score (in bars).
    trend_eps:
        Magnitude under which the trend score is treated as "chop".
        Defaults to 1e-4 ≈ 1bp / bar.
    warmup_bars:
        Bars at the head of the series labelled ``unknown`` because their
        rolling stats haven't accumulated enough samples yet.
    """
    n = len(closes)
    if n == 0:
        return RegimeAssignment(
            coarse=[], fine=[], trend_score=[], vol_score=[],
            vol_high_threshold=[], warmup_n=0,
            config={
                "trend_window": trend_window,
                "vol_window": vol_window,
                "trend_eps": trend_eps,
                "warmup_bars": warmup_bars,
            },
        )

    log_r = _log_returns(closes)
    trend = _ema_causal(log_r, trend_window)
    vol = _rolling_std(log_r, vol_window)
    vol_thr = _causal_median(vol)

    coarse: list[str] = []
    fine: list[str] = []
    warm = 0
    for i in range(n):
        if i < warmup_bars:
            coarse.append("unknown")
            fine.append("unknown")
            warm += 1
            continue

        t = trend[i]
        if t > trend_eps:
            t_label = "trend_up"
            coarse_label = "bull"
        elif t < -trend_eps:
            t_label = "trend_down"
            coarse_label = "bear"
        else:
            t_label = "chop"
            coarse_label = "chop"

        # Use the causal median *up to t* as the high/low-vol threshold so
        # the assignment never depends on future volatility.
        v_label = "high_vol" if vol[i] >= vol_thr[i] else "low_vol"

        coarse.append(coarse_label)
        fine.append(f"{t_label}_{v_label}")

    return RegimeAssignment(
        coarse=coarse,
        fine=fine,
        trend_score=trend,
        vol_score=vol,
        vol_high_threshold=vol_thr,
        warmup_n=warm,
        config={
            "trend_window": trend_window,
            "vol_window": vol_window,
            "trend_eps": trend_eps,
            "warmup_bars": warmup_bars,
        },
    )


def regime_at(
    closes: list[float],
    **kwargs,
) -> tuple[str, str]:
    """Convenience: return the (coarse, fine) regime label for the *last*
    bar in ``closes`` only. Strictly causal — uses ``closes[0..-1]`` only.
    """
    if not closes:
        return ("unknown", "unknown")
    a = detect_regimes(closes, **kwargs)
    return (a.coarse[-1], a.fine[-1])


def summarize_distribution(assignment: RegimeAssignment) -> dict:
    """Return counts and proportions for each fine/coarse label."""
    n = len(assignment.fine)
    fine_counts: dict[str, int] = {k: 0 for k in FINE_LABELS}
    coarse_counts: dict[str, int] = {k: 0 for k in COARSE_LABELS}
    for f in assignment.fine:
        fine_counts[f] = fine_counts.get(f, 0) + 1
    for c in assignment.coarse:
        coarse_counts[c] = coarse_counts.get(c, 0) + 1
    return {
        "n": n,
        "fine_counts": fine_counts,
        "fine_proportions": (
            {k: (v / n if n else 0.0) for k, v in fine_counts.items()}
        ),
        "coarse_counts": coarse_counts,
        "coarse_proportions": (
            {k: (v / n if n else 0.0) for k, v in coarse_counts.items()}
        ),
        "warmup_n": assignment.warmup_n,
    }
