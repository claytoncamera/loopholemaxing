"""
Feature builder for the BTC Brain shadow models.

Inputs:
  * `closed_candles`: list of OHLCV dicts (already filtered through the
    Phase 2 `drop_incomplete_candle` helper). Strictly ordered ascending
    by `open_time_ms`. Each candle has keys:
      open_time_ms, close_time_ms, open, high, low, close, volume
  * `derivatives_series`: optional list of dicts aligned by `open_time_ms`
    with keys `funding_rate`, `open_interest_btc` (None allowed).
  * `sentiment_series`: optional list of dicts aligned by `open_time_ms`
    with keys `fear_greed_value` (None allowed).
  * `source_freshness_seconds`: optional list of ints (seconds-since-fetch
    for each row). Used as a feature so the model can learn to discount
    when its inputs are stale.
  * `regime_series`: optional list of regime strings (`bull`/`bear`/`chop`/
    `unknown`). Encoded one-hot.

Outputs a `FeatureFrame` with:
  * `index`: list[int] — open_time_ms of the source bar
  * `feature_names`: list[str]
  * `X`: list[list[float]]  (rows aligned to `index`)
  * `meta`: dict with raw close prices and regimes for downstream use.

All features at row `i` are computed from candles[0..i] inclusive. Targets
are *separate* (see `targets.py`) and use `i+H` close, never the same bar.

No NaN. Missing optional inputs become 0.0 with a flag column where
appropriate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

FEATURES_VERSION = "phase3-features-v0.1.0"


@dataclass
class FeatureFrame:
    feature_names: list[str]
    index: list[int]                  # open_time_ms per row
    X: list[list[float]]              # rows of feature values
    meta: dict = field(default_factory=dict)
    version: str = FEATURES_VERSION

    def n_rows(self) -> int:
        return len(self.X)

    def n_cols(self) -> int:
        return len(self.feature_names)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "feature_names": list(self.feature_names),
            "index": list(self.index),
            "X": [list(row) for row in self.X],
            "meta": dict(self.meta),
        }


# ── Numeric helpers (pure stdlib) ──────────────────────────────────────────
def _safe_log(x: float) -> float:
    if x <= 0:
        return 0.0
    return math.log(x)


def _ema(values: list[float], n: int) -> list[float]:
    """Standard EMA. Output length == input. First n-1 values use SMA seed."""
    if n <= 1:
        return list(values)
    out: list[float] = []
    if not values:
        return out
    k = 2.0 / (n + 1.0)
    seed = values[0]
    for i, v in enumerate(values):
        if i == 0:
            out.append(seed)
        else:
            out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi(closes: list[float], n: int = 14) -> list[float]:
    """Wilder RSI. Output length == input. Pre-period values = 50.0."""
    out = [50.0] * len(closes)
    if len(closes) <= n:
        return out
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # Wilder smoothing
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    if avg_l == 0:
        out[n] = 100.0
    else:
        rs = avg_g / avg_l
        out[n] = 100.0 - (100.0 / (1 + rs))
    for i in range(n + 1, len(closes)):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - (100.0 / (1 + rs))
    return out


def _realized_vol(log_returns: list[float], window: int) -> list[float]:
    """Std of trailing window of log returns. Insufficient → 0.0."""
    out = [0.0] * len(log_returns)
    for i in range(len(log_returns)):
        lo = max(0, i - window + 1)
        seg = log_returns[lo : i + 1]
        if len(seg) < 2:
            continue
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / (len(seg) - 1)
        out[i] = math.sqrt(var)
    return out


def _volume_ratio(volumes: list[float], window: int) -> list[float]:
    """Current volume / SMA(volumes, window). Missing volume becomes 0."""
    out = [1.0] * len(volumes)
    for i in range(len(volumes)):
        lo = max(0, i - window + 1)
        seg = [v for v in volumes[lo : i + 1] if v is not None and v > 0]
        if not seg:
            out[i] = 1.0
            continue
        avg = sum(seg) / len(seg)
        cur = volumes[i] if (volumes[i] is not None and volumes[i] > 0) else avg
        out[i] = cur / avg if avg > 0 else 1.0
    return out


# ── Builder ────────────────────────────────────────────────────────────────
REGIME_ONEHOT = ("bull", "bear", "chop", "unknown")


def build_features(
    closed_candles: list[dict],
    derivatives_series: Optional[list[dict]] = None,
    sentiment_series: Optional[list[dict]] = None,
    source_freshness_seconds: Optional[list[Optional[int]]] = None,
    regime_series: Optional[list[Optional[str]]] = None,
    rsi_period: int = 14,
    ema_period: int = 20,
    vol_window: int = 24,
    vol_ratio_window: int = 24,
) -> FeatureFrame:
    """Return a FeatureFrame from the given closed-candle series.

    `closed_candles` MUST come from `drop_incomplete_candle` — this builder
    does not re-check, but it is a Phase 0/2 invariant for callers.
    """
    n = len(closed_candles)
    if n == 0:
        return FeatureFrame(
            feature_names=[],
            index=[],
            X=[],
            meta={"empty": True},
        )

    closes = [float(c["close"]) for c in closed_candles]
    volumes = [
        (float(c["volume"]) if c.get("volume") is not None else None)
        for c in closed_candles
    ]
    open_time_ms = [int(c["open_time_ms"]) for c in closed_candles]

    # Log returns: r_t = log(close_t / close_{t-1}); first row = 0.
    log_returns = [0.0]
    for i in range(1, n):
        prev = closes[i - 1]
        cur = closes[i]
        if prev > 0 and cur > 0:
            log_returns.append(math.log(cur / prev))
        else:
            log_returns.append(0.0)

    rv = _realized_vol(log_returns, vol_window)
    vol_ratio = _volume_ratio(volumes, vol_ratio_window)
    rsi = _rsi(closes, rsi_period)
    ema = _ema(closes, ema_period)
    ema_dist = [
        (closes[i] - ema[i]) / ema[i] if ema[i] > 0 else 0.0 for i in range(n)
    ]

    # Optional aligned series: pad with None to match n.
    def _align(series: Optional[list], default=None) -> list:
        if series is None:
            return [default] * n
        if len(series) < n:
            return [default] * (n - len(series)) + list(series)
        return list(series[-n:])

    derivs = _align(derivatives_series, default={})
    senti = _align(sentiment_series, default={})
    fresh = _align(source_freshness_seconds, default=None)
    regime = _align(regime_series, default="unknown")

    funding = []
    funding_present = []
    oi_delta = []
    oi_present = []
    prev_oi = None
    for i, d in enumerate(derivs):
        d = d or {}
        fr = d.get("funding_rate")
        funding.append(float(fr) if fr is not None else 0.0)
        funding_present.append(1.0 if fr is not None else 0.0)
        oi = d.get("open_interest_btc")
        if oi is None or prev_oi is None or prev_oi == 0:
            oi_delta.append(0.0)
        else:
            oi_delta.append((float(oi) - prev_oi) / prev_oi)
        oi_present.append(1.0 if oi is not None else 0.0)
        if oi is not None:
            prev_oi = float(oi)

    fng = []
    fng_present = []
    for i, s in enumerate(senti):
        s = s or {}
        v = s.get("fear_greed_value")
        if v is None:
            fng.append(0.5)  # neutral mid (rescaled)
            fng_present.append(0.0)
        else:
            # Normalize 0..100 → 0..1
            fng.append(float(v) / 100.0)
            fng_present.append(1.0)

    fresh_secs = []
    fresh_present = []
    for f in fresh:
        if f is None:
            fresh_secs.append(0.0)
            fresh_present.append(0.0)
        else:
            # Log-scale to keep gradient sane.
            fresh_secs.append(_safe_log(1.0 + float(f)))
            fresh_present.append(1.0)

    # Regime one-hot.
    regime_cols = {r: [] for r in REGIME_ONEHOT}
    for r in regime:
        r = r if r in REGIME_ONEHOT else "unknown"
        for k in REGIME_ONEHOT:
            regime_cols[k].append(1.0 if k == r else 0.0)

    feature_names = [
        "log_return_1",
        "realized_vol",
        "volume_ratio",
        "rsi_14",
        "ema_distance",
        "funding_rate",
        "funding_present",
        "open_interest_delta",
        "open_interest_present",
        "fear_greed_norm",
        "fear_greed_present",
        "source_freshness_log",
        "source_freshness_present",
    ] + [f"regime_{r}" for r in REGIME_ONEHOT]

    X: list[list[float]] = []
    for i in range(n):
        row = [
            log_returns[i],
            rv[i],
            vol_ratio[i],
            rsi[i] / 100.0,         # normalized 0..1 for stability
            ema_dist[i],
            funding[i],
            funding_present[i],
            oi_delta[i],
            oi_present[i],
            fng[i],
            fng_present[i],
            fresh_secs[i],
            fresh_present[i],
        ] + [regime_cols[r][i] for r in REGIME_ONEHOT]
        X.append(row)

    return FeatureFrame(
        feature_names=feature_names,
        index=open_time_ms,
        X=X,
        meta={
            "closes": closes,
            "regimes": [r if r in REGIME_ONEHOT else "unknown" for r in regime],
            "candle_count": n,
        },
    )
