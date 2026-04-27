"""
Dynamic key-level computation from real, *closed* candles.

We never use the in-progress candle. We never accept a synthesized OHLC.
Inputs are the candle dicts returned by `feeds.candles` (already closed
via `closed_candles()`).

Levels emitted:
  * recent_high / recent_low                — last N closed candles
  * pivot_classic / r1 / r2 / s1 / s2       — classic pivot from prev day
  * sma_20 / sma_50 / sma_200               — close-based moving averages
                                              (None if not enough candles)
  * vwap_session                            — running session VWAP from
                                              today's UTC closed 1h candles

Pivot point reference (canonical):
    P  = (H + L + C) / 3
    R1 = 2P - L
    S1 = 2P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Optional


KEY_LEVELS_VERSION = "key-levels-v0.1.0"


def _sma(values: list[float], n: int) -> Optional[float]:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def _vwap(candles: list[dict]) -> Optional[float]:
    """Volume-weighted average price across the given closed candles.

    Uses (h+l+c)/3 typical price * volume / total volume. Returns None if
    no candle has a real volume (e.g. coingecko-only data).
    """
    num = 0.0
    den = 0.0
    for c in candles:
        v = c.get("volume")
        if v is None:
            continue
        v = float(v)
        if v <= 0:
            continue
        tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        num += tp * v
        den += v
    if den <= 0:
        return None
    return num / den


def _todays_utc_candles(candles: list[dict], now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    day_start_ms = int(day_start.timestamp() * 1000)
    return [c for c in candles if int(c["open_time_ms"]) >= day_start_ms]


def compute_key_levels(
    closed_1h: list[dict],
    closed_1d: list[dict],
    now: Optional[datetime] = None,
) -> dict:
    """Compute the canonical level pack from real closed candles.

    Either argument may be empty: in that case the corresponding fields
    will be None, and the result reports `degraded: true`.
    """
    out: dict = {
        "version": KEY_LEVELS_VERSION,
        "computed_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "closed_1h_count": len(closed_1h),
            "closed_1d_count": len(closed_1d),
        },
        "recent_high": None,
        "recent_low": None,
        "pivot_classic": None,
        "r1": None, "r2": None, "s1": None, "s2": None,
        "sma_20": None,
        "sma_50": None,
        "sma_200": None,
        "vwap_session": None,
        "degraded": False,
        "notes": [],
    }

    # Recent high/low from last 24 closed 1h candles (true OHLC-derived).
    if closed_1h:
        window = closed_1h[-24:]
        highs = [float(c["high"]) for c in window]
        lows = [float(c["low"]) for c in window]
        out["recent_high"] = max(highs)
        out["recent_low"] = min(lows)
        out["vwap_session"] = _vwap(_todays_utc_candles(closed_1h, now=now))
    else:
        out["degraded"] = True
        out["notes"].append("no closed 1h candles — recent_high/low unavailable")

    # Classic pivots from the *previous* closed daily candle.
    if len(closed_1d) >= 1:
        prev = closed_1d[-1]
        h = float(prev["high"])
        l = float(prev["low"])
        c = float(prev["close"])
        p = (h + l + c) / 3.0
        out["pivot_classic"] = p
        out["r1"] = 2 * p - l
        out["s1"] = 2 * p - h
        out["r2"] = p + (h - l)
        out["s2"] = p - (h - l)
    else:
        out["degraded"] = True
        out["notes"].append("no closed daily candle — pivots unavailable")

    # SMAs from 1d closes (preferred — daily SMA is what the public usually
    # references). Fall back to 1h closes if no daily data and we have at
    # least 200 hourly closes (less canonical, mark in notes).
    if len(closed_1d) >= 20:
        d_closes = [float(c["close"]) for c in closed_1d]
        out["sma_20"] = _sma(d_closes, 20)
        out["sma_50"] = _sma(d_closes, 50)
        out["sma_200"] = _sma(d_closes, 200)
        if out["sma_50"] is None:
            out["notes"].append("sma_50 needs 50+ daily closes")
        if out["sma_200"] is None:
            out["notes"].append("sma_200 needs 200+ daily closes")
    else:
        out["notes"].append("insufficient daily candles for SMAs")

    return out
