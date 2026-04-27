"""
Synthetic 1h candle generator with weakly predictable structure so that
logistic regression can plausibly beat the random/majority baselines on
walk-forward folds. The signal is deliberately small.

NOT REAL DATA. Used for tests and example registry/calibration artifacts.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone


def make_synthetic_candles(
    n: int = 1200,
    start_ms: int = 1735689600000,  # 2025-01-01T00:00:00Z
    interval_ms: int = 60 * 60 * 1000,
    seed: int = 42,
    base_price: float = 30000.0,
    drift: float = 0.0001,
    vol: float = 0.004,
    autocorr: float = 0.10,
) -> list[dict]:
    """Random walk with small positive autocorrelation — so momentum
    baselines and logistic regression should *slightly* beat majority on
    average. The signal is small and the variance is high — we never claim
    these results transfer to real BTC.
    """
    rng = random.Random(seed)
    candles = []
    log_price = math.log(base_price)
    prev_r = 0.0
    for i in range(n):
        # Autocorrelated log-return: mean = drift + autocorr * prev_r.
        mean = drift + autocorr * prev_r
        r = mean + rng.gauss(0.0, vol)
        log_price += r
        close = math.exp(log_price)
        # Synthesize OHLC from close ± noise.
        high = close * (1 + abs(rng.gauss(0, vol)))
        low = close * (1 - abs(rng.gauss(0, vol)))
        open_p = close * (1 + rng.gauss(0, vol / 4))
        volume = max(0.001, rng.gauss(100.0, 25.0))
        ot = start_ms + i * interval_ms
        ct = ot + interval_ms
        candles.append({
            "open_time_ms": ot,
            "close_time_ms": ct,
            "open": float(open_p),
            "high": float(max(open_p, high, close)),
            "low": float(min(open_p, low, close)),
            "close": float(close),
            "volume": float(volume),
        })
        prev_r = r
    return candles


def make_synthetic_aux_series(candles: list[dict], seed: int = 99) -> dict:
    """Return aligned derivatives, sentiment, freshness, and regime series."""
    rng = random.Random(seed)
    n = len(candles)
    derivs = []
    senti = []
    fresh = []
    regime = []
    last_oi = 50000.0
    for i, c in enumerate(candles):
        derivs.append({
            "funding_rate": rng.gauss(0.0001, 0.0003),
            "open_interest_btc": last_oi + rng.gauss(0, 200),
        })
        last_oi = derivs[-1]["open_interest_btc"]
        senti.append({"fear_greed_value": int(50 + rng.gauss(0, 12))})
        fresh.append(int(max(0, rng.gauss(60, 20))))
        # Crude regime cycling.
        if i % 240 < 80:
            regime.append("bull")
        elif i % 240 < 160:
            regime.append("chop")
        else:
            regime.append("bear")
    return {
        "derivatives": derivs,
        "sentiment": senti,
        "freshness": fresh,
        "regime": regime,
    }
