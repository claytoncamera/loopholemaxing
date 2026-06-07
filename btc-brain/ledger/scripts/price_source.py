"""
Price source for the resolver.

Default: Binance public klines (1h candle close).
Strategy: pick the candle whose interval *ends at* target_time — i.e. the
candle that CLOSES at the horizon boundary — and use that candle's CLOSE
price. This is the canonical "price at close of horizon" rule.

Correctness note (resolver off-by-one fix):
Forecasts are issued on the hour grid and their target_time lands on an
exact hour boundary (e.g. issued 05:00Z, 1h horizon -> target 06:00Z).
The price that resolves a 1h forecast is the close of the 05:00->06:00
candle (Binance closeTime ~= 05:59:59.999Z, i.e. close_time ~= target).
The previous rule `open_time <= target < close_time` instead selected the
06:00->07:00 candle and returned its 07:00 close — one full candle late,
which corrupted actual_close / direction / Brier / logloss for every
horizon. We now match the candle whose close_time == target (to the
second), which is the bar that finalizes exactly at the horizon end.

We refuse incomplete candles: if the matched candle's `closeTime` > now,
we raise NotYet.
"""
from __future__ import annotations

import json
import time
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


# Hosts tried in order. api.binance.com is frequently geo-blocked from cloud
# CI runners (HTTP 451); data-api.binance.vision is Binance's public
# market-data mirror that serves the same klines without that restriction.
_BINANCE_HOSTS = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


def _binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch klines with host fallback and exponential backoff.

    Empty/transient failures (network errors, 5xx, geo-blocks) are retried
    across both hosts. Only a total failure across every host+attempt raises
    PriceFetchError — so a single blocked request no longer leaves forecasts
    permanently unresolved.
    """
    path = (
        f"/api/v3/klines?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    last_err: Optional[Exception] = None
    for attempt in range(_MAX_ATTEMPTS):
        for host in _BINANCE_HOSTS:
            req = urllib.request.Request(
                host + path, headers={"User-Agent": "btc-brain-ledger/1"}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, ValueError) as e:
                last_err = e
                continue
        # Backoff between full host sweeps; skip the wait after the last one.
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
    raise PriceFetchError(
        f"binance fetch failed after {_MAX_ATTEMPTS} attempts "
        f"across {len(_BINANCE_HOSTS)} hosts: {last_err}"
    )


def fetch_close_for_target(
    target_time_iso: str,
    now: Optional[datetime] = None,
    fetcher=_binance_klines,
) -> Candle:
    """Return the 1h Binance candle that CLOSES at target_time.

    Forecasts target an exact hour boundary (e.g. issued 05:00Z, 1h horizon
    -> target 06:00Z). The resolving price is the close of the candle whose
    interval *ends* at the horizon — the 05:00->06:00 bar, whose Binance
    closeTime is ~05:59:59.999Z. We therefore match the candle whose
    close_time == target (to the second), not the bar that merely opens at
    target. See the module docstring for the off-by-one this fixes.
    """
    target = parse_iso_utc(target_time_iso)
    now = now or datetime.now(timezone.utc)

    # +1s makes the boundary inclusive on the right exactly at hour rollover.
    candle_close_min = target + timedelta(seconds=1)
    if candle_close_min > now:
        raise NotYet(
            f"target_time {target_time_iso} not yet past; now={now.isoformat()}"
        )

    start_ms = int((target - timedelta(hours=2)).timestamp() * 1000)
    end_ms = int((target + timedelta(hours=1)).timestamp() * 1000)
    klines = fetcher("BTCUSDT", "1h", start_ms, end_ms)
    if not klines:
        raise PriceFetchError("no klines returned")

    for k in klines:
        ot = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        ct = datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc)
        # Binance closeTime is the last ms of the candle (e.g. ...:59.999),
        # so the candle that finalizes at `target` has close_time within one
        # second below it. Match on that bar — its close is the horizon price.
        if abs((ct - target).total_seconds()) <= 1.0:
            # Refuse incomplete candle.
            if ct > now:
                raise NotYet(
                    f"candle {ot.isoformat()} not yet closed at {now.isoformat()}"
                )
            return Candle(open_time=ot, close_time=ct, close_price=float(k[4]))

    raise PriceFetchError(
        f"no candle closes at target_time={target_time_iso}; "
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
