"""
Price source for the resolver.

Default: Binance public klines (1h candle close).
Strategy: pick the candle whose openTime <= target_time < closeTime,
and use that candle's CLOSE price. This is the canonical "price at close
of horizon" rule.

We refuse incomplete candles: if `closeTime` > now, we raise NotYet.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from ledger import parse_iso_utc, utc_now_iso


PRICE_SOURCE_VERSION = "binance:BTCUSDT:1h"


class NotYet(Exception):
    """Target candle has not closed yet."""


class PriceFetchError(Exception):
    pass


@dataclass
class Candle:
    open_time: datetime  # UTC
    close_time: datetime  # UTC (exclusive end)
    close_price: float
    source: str = PRICE_SOURCE_VERSION


def _binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "btc-brain-ledger/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise PriceFetchError(f"binance fetch failed: {e}")


def fetch_close_for_target(
    target_time_iso: str,
    now: Optional[datetime] = None,
    fetcher=_binance_klines,
) -> Candle:
    """Return the 1h Binance candle whose interval contains target_time.

    We fetch a small window around target_time and pick the candle where
    open_time <= target_time < close_time.
    """
    target = parse_iso_utc(target_time_iso)
    now = now or datetime.now(timezone.utc)

    # +1s makes the boundary inclusive on the right exactly at hour rollover.
    candle_close_min = target + timedelta(seconds=1)
    if candle_close_min > now:
        raise NotYet(
            f"target_time {target_time_iso} not yet past; now={now.isoformat()}"
        )

    start_ms = int((target - timedelta(hours=1)).timestamp() * 1000)
    end_ms = int((target + timedelta(hours=2)).timestamp() * 1000)
    klines = fetcher("BTCUSDT", "1h", start_ms, end_ms)
    if not klines:
        raise PriceFetchError("no klines returned")

    for k in klines:
        ot = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        ct = datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc)
        # Binance closeTime is the last ms of the candle; treat as exclusive end.
        if ot <= target < ct:
            # Refuse incomplete candle.
            if ct > now:
                raise NotYet(
                    f"candle {ot.isoformat()} not yet closed at {now.isoformat()}"
                )
            return Candle(open_time=ot, close_time=ct, close_price=float(k[4]))

    raise PriceFetchError(
        f"no candle covers target_time={target_time_iso}; "
        f"got {len(klines)} candles in window"
    )


# ── Test/offline fixture fetcher ─────────────────────────────────────────────
def make_fixture_fetcher(candles: list[tuple[int, int, float]]):
    """Build a fetcher closure for tests.

    `candles` is a list of (open_ms, close_ms, close_price).
    """
    def _f(symbol, interval, start_ms, end_ms):
        out = []
        for o, c, px in candles:
            if c < start_ms or o > end_ms:
                continue
            out.append([o, "0", "0", "0", str(px), "0", c, "0", 0, "0", "0", "0"])
        return out
    return _f
