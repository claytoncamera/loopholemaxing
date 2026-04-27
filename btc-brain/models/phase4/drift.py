"""
Phase 4 — Lightweight drift detectors.

Implements three detectors. All are stateful but pure-stdlib — they read
one observation at a time and expose ``alarm`` flags / summary state.

  1. ``PageHinkley``   — concept drift on a scalar error / loss stream.
  2. ``EWMADriftDetector`` — exponential moving-average error drift with a
     simple sigma-band alarm. Lightweight ADWIN-style cousin (size-1 windows
     of varying weight rather than two adaptive windows).
  3. ``KSWindow``      — Kolmogorov-Smirnov-style two-window distribution
     shift detector. Compares a reference window to a recent window and
     fires when the empirical-CDF gap exceeds the chosen alpha threshold.

None of these auto-promote anything. They produce *alerts*, which the
retrain candidate pipeline (``btc-brain/models/phase4/retrain.py``)
collects into a candidate report. Promotion remains manual and gated by
``btc-brain/models/phase4/promotion_gates.py``.

References (informational):
  Page (1954)             — sequential change detection / Page-Hinkley.
  Bifet & Gavaldà (2007)  — ADWIN.
  Bifet & Gavaldà (2009)  — KSWIN ideas.
We re-derive simple, dependency-free variants here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


DRIFT_VERSION = "phase4-drift-v0.1.0"


# ── Page-Hinkley ────────────────────────────────────────────────────────────
@dataclass
class PageHinkleyState:
    n: int = 0
    mean: float = 0.0
    cumulative: float = 0.0
    min_cumulative: float = 0.0
    max_cumulative: float = 0.0
    last_alarm_at: Optional[int] = None
    alarm_count: int = 0


class PageHinkley:
    """Page-Hinkley change detector for a scalar loss / error stream.

    Tracks the running mean and a cumulative deviation. Fires when the gap
    between the running cumulative and its min (drift up) — or its max
    (drift down) — exceeds ``threshold``. ``alpha`` is a small forgetting
    factor: it nudges the cumulative back toward zero so a slow regime
    shift can re-arm the detector once the new mean is learned.

    Use the same instance per (model, horizon) — never share across
    horizons or models. Reset with ``.reset()`` after handling an alarm.
    """

    def __init__(self, threshold: float = 50.0, alpha: float = 1e-4,
                 min_n: int = 30, direction: str = "both"):
        if direction not in ("up", "down", "both"):
            raise ValueError(f"direction must be up|down|both, got {direction}")
        self.threshold = float(threshold)
        self.alpha = float(alpha)
        self.min_n = int(min_n)
        self.direction = direction
        self.state = PageHinkleyState()

    def reset(self) -> None:
        self.state = PageHinkleyState()

    def update(self, x: float) -> bool:
        """Feed one observation. Returns True if an alarm fires *this* step."""
        s = self.state
        s.n += 1
        # Streaming mean.
        s.mean += (x - s.mean) / s.n
        # Page-Hinkley cumulative deviation with a small forgetting term.
        delta = x - s.mean - self.alpha
        s.cumulative += delta
        if s.cumulative < s.min_cumulative:
            s.min_cumulative = s.cumulative
        if s.cumulative > s.max_cumulative:
            s.max_cumulative = s.cumulative
        if s.n < self.min_n:
            return False
        alarmed = False
        if self.direction in ("up", "both") and (s.cumulative - s.min_cumulative) > self.threshold:
            alarmed = True
        if self.direction in ("down", "both") and (s.max_cumulative - s.cumulative) > self.threshold:
            alarmed = True
        if alarmed:
            s.alarm_count += 1
            s.last_alarm_at = s.n
        return alarmed

    def snapshot(self) -> dict:
        s = self.state
        return {
            "n": s.n,
            "mean": s.mean,
            "cumulative": s.cumulative,
            "min_cumulative": s.min_cumulative,
            "max_cumulative": s.max_cumulative,
            "last_alarm_at": s.last_alarm_at,
            "alarm_count": s.alarm_count,
            "config": {
                "threshold": self.threshold,
                "alpha": self.alpha,
                "min_n": self.min_n,
                "direction": self.direction,
            },
            "version": DRIFT_VERSION,
        }


# ── EWMA error / ADWIN-lite ─────────────────────────────────────────────────
@dataclass
class EWMADriftState:
    n: int = 0
    ewma: float = 0.0
    ewma_var: float = 0.0
    last_alarm_at: Optional[int] = None
    alarm_count: int = 0


class EWMADriftDetector:
    """EWMA mean + EWMA variance on the error stream.

    Fires when ``|ewma - long_run_mean| > k_sigma * sqrt(ewma_var)``. The
    ``long_run_mean`` is itself updated via a slower EWMA with a much
    smaller alpha so the alarm captures *recent* deviation from baseline.
    Lightweight cousin of ADWIN.
    """

    def __init__(
        self,
        fast_alpha: float = 0.1,
        slow_alpha: float = 0.005,
        k_sigma: float = 3.0,
        min_n: int = 30,
    ):
        self.fast_alpha = float(fast_alpha)
        self.slow_alpha = float(slow_alpha)
        self.k_sigma = float(k_sigma)
        self.min_n = int(min_n)
        self.state = EWMADriftState()
        self._slow_mean = 0.0

    def reset(self) -> None:
        self.state = EWMADriftState()
        self._slow_mean = 0.0

    def update(self, x: float) -> bool:
        s = self.state
        s.n += 1
        if s.n == 1:
            s.ewma = x
            self._slow_mean = x
            s.ewma_var = 0.0
            return False
        # Fast EWMA.
        prev = s.ewma
        s.ewma = self.fast_alpha * x + (1 - self.fast_alpha) * prev
        # Variance of the residual against the prior fast mean.
        diff = x - prev
        s.ewma_var = (
            self.fast_alpha * (diff * diff) + (1 - self.fast_alpha) * s.ewma_var
        )
        # Slow baseline mean.
        self._slow_mean = (
            self.slow_alpha * x + (1 - self.slow_alpha) * self._slow_mean
        )
        if s.n < self.min_n:
            return False
        sigma = math.sqrt(max(s.ewma_var, 0.0))
        gap = abs(s.ewma - self._slow_mean)
        if sigma <= 0:
            return False
        if gap > self.k_sigma * sigma:
            s.alarm_count += 1
            s.last_alarm_at = s.n
            return True
        return False

    def snapshot(self) -> dict:
        s = self.state
        return {
            "n": s.n,
            "fast_ewma": s.ewma,
            "slow_mean": self._slow_mean,
            "ewma_var": s.ewma_var,
            "last_alarm_at": s.last_alarm_at,
            "alarm_count": s.alarm_count,
            "config": {
                "fast_alpha": self.fast_alpha,
                "slow_alpha": self.slow_alpha,
                "k_sigma": self.k_sigma,
                "min_n": self.min_n,
            },
            "version": DRIFT_VERSION,
        }


# ── KS-window distribution shift ────────────────────────────────────────────
@dataclass
class KSWindowState:
    seen_total: int = 0
    last_alarm_at: Optional[int] = None
    alarm_count: int = 0
    last_d: float = 0.0
    last_p_approx: float = 1.0


class KSWindow:
    """Two-window Kolmogorov-Smirnov distribution shift detector.

    Maintains a fixed-size ``reference_window`` (the historical baseline)
    and a sliding ``recent_window``. Once both windows are full, a fresh
    observation pushes the oldest reference value out, the oldest recent
    value into the reference, and the new value into the recent buffer.

    Each step we compute the empirical CDF gap ``D`` and the
    Kolmogorov-Smirnov critical value ``c(alpha) * sqrt((m+n)/(m*n))``.
    Alarm fires when ``D > critical``. We never use SciPy — we implement
    the two-sample KS statistic ourselves.

    Notes
    -----
    The reference window is intentionally NOT static-forever. We let it
    slowly absorb the incoming distribution so the detector re-arms after
    a regime change, instead of firing forever once it crossed.
    """

    # Standard KS critical-value coefficients.
    _ALPHA_TO_C = {
        0.10: 1.224, 0.05: 1.358, 0.025: 1.480, 0.01: 1.628, 0.005: 1.731,
    }

    def __init__(
        self,
        reference_size: int = 200,
        recent_size: int = 50,
        alpha: float = 0.01,
        min_recent: int = 30,
    ):
        if reference_size < recent_size:
            raise ValueError("reference_size must be >= recent_size")
        if alpha not in self._ALPHA_TO_C:
            raise ValueError(
                f"alpha must be one of {sorted(self._ALPHA_TO_C)} (got {alpha})"
            )
        self.reference_size = int(reference_size)
        self.recent_size = int(recent_size)
        self.alpha = float(alpha)
        self.min_recent = int(min_recent)
        self.reference: list[float] = []
        self.recent: list[float] = []
        self.state = KSWindowState()

    def reset(self) -> None:
        self.reference = []
        self.recent = []
        self.state = KSWindowState()

    @staticmethod
    def _ks_d(a: list[float], b: list[float]) -> float:
        """Two-sample KS statistic ``D`` — sup |F_a(x) - F_b(x)|."""
        if not a or not b:
            return 0.0
        sa = sorted(a)
        sb = sorted(b)
        i = j = 0
        d = 0.0
        na, nb = len(sa), len(sb)
        while i < na and j < nb:
            if sa[i] <= sb[j]:
                i += 1
            else:
                j += 1
            cdf_a = i / na
            cdf_b = j / nb
            gap = abs(cdf_a - cdf_b)
            if gap > d:
                d = gap
        # Tail check.
        gap = abs(1.0 - (j / nb)) if i == na else abs((i / na) - 1.0)
        if gap > d:
            d = gap
        return d

    def _critical(self) -> float:
        c = self._ALPHA_TO_C[self.alpha]
        m, n = len(self.reference), len(self.recent)
        if m == 0 or n == 0:
            return float("inf")
        return c * math.sqrt((m + n) / (m * n))

    def update(self, x: float) -> bool:
        self.state.seen_total += 1
        if len(self.reference) < self.reference_size:
            # Fill reference first.
            self.reference.append(float(x))
            return False
        # Reference is full — feed the recent window.
        self.recent.append(float(x))
        if len(self.recent) > self.recent_size:
            # Roll the oldest recent observation into the reference,
            # and drop the oldest reference value to keep ``m`` fixed.
            roll = self.recent.pop(0)
            self.reference.pop(0)
            self.reference.append(roll)
        if len(self.recent) < self.min_recent:
            return False
        d = self._ks_d(self.reference, self.recent)
        crit = self._critical()
        self.state.last_d = d
        self.state.last_p_approx = (
            0.0 if (d > crit and crit < float("inf")) else self.alpha
        )
        if d > crit:
            self.state.alarm_count += 1
            self.state.last_alarm_at = self.state.seen_total
            return True
        return False

    def snapshot(self) -> dict:
        s = self.state
        return {
            "seen_total": s.seen_total,
            "reference_n": len(self.reference),
            "recent_n": len(self.recent),
            "last_d": s.last_d,
            "last_alarm_at": s.last_alarm_at,
            "alarm_count": s.alarm_count,
            "config": {
                "reference_size": self.reference_size,
                "recent_size": self.recent_size,
                "alpha": self.alpha,
                "min_recent": self.min_recent,
            },
            "version": DRIFT_VERSION,
        }


# ── Convenience runner ──────────────────────────────────────────────────────
def run_detectors(
    error_stream: Iterable[float],
    feature_stream: Optional[Iterable[float]] = None,
    page_hinkley: Optional[PageHinkley] = None,
    ewma: Optional[EWMADriftDetector] = None,
    kswin: Optional[KSWindow] = None,
) -> dict:
    """Run a batch of observations through the supplied detectors.

    ``error_stream`` is fed into the error-domain detectors (Page-Hinkley,
    EWMA). ``feature_stream`` (if provided) is fed into the distribution
    shift detector (KS-window). The streams are independent — each is
    consumed once, in order. Returns a summary dict suitable for embedding
    in the retrain candidate report.
    """
    ph = page_hinkley or PageHinkley()
    ew = ewma or EWMADriftDetector()
    ks = kswin or KSWindow()

    ph_alarms: list[int] = []
    ew_alarms: list[int] = []
    ks_alarms: list[int] = []

    for i, x in enumerate(error_stream):
        if ph.update(float(x)):
            ph_alarms.append(i)
        if ew.update(float(x)):
            ew_alarms.append(i)

    if feature_stream is not None:
        for i, x in enumerate(feature_stream):
            if ks.update(float(x)):
                ks_alarms.append(i)

    return {
        "page_hinkley": {
            "alarms_at": ph_alarms,
            "snapshot": ph.snapshot(),
        },
        "ewma": {
            "alarms_at": ew_alarms,
            "snapshot": ew.snapshot(),
        },
        "kswin": {
            "alarms_at": ks_alarms,
            "snapshot": ks.snapshot(),
        },
        "version": DRIFT_VERSION,
    }
