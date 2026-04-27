"""
Candle providers with fallback: Binance → Coinbase → Kraken → CoinGecko.

Each provider returns a FeedResult whose `data` (when not None) is a dict:
  {
    "interval": "1h",
    "candles": [
        {"open_time_ms": int, "close_time_ms": int,
         "open": float, "high": float, "low": float,
         "close": float, "volume": float},
        ...
    ]
  }

Coinbase and Kraken sometimes return only an open_time and an interval; we
compute close_time_ms = open_time_ms + interval_ms. CoinGecko's
market_chart endpoint does NOT return real OHLC for short intervals, so we
ONLY use it for *daily* candle bars (where it is genuinely OHLC) and
explicitly mark sub-daily as `failed` rather than fabricate.
"""
from __future__ import annotations

from typing import Callable, Optional

from .base import (
    FeedResult,
    HttpError,
    STATUS_FAILED,
    STATUS_OK,
    drop_incomplete_candle,
    http_get_json,
    utc_now,
    utc_now_iso,
)


# ── Interval mapping ───────────────────────────────────────────────────────
SUPPORTED_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


# ── Binance (primary) ──────────────────────────────────────────────────────
def fetch_binance_candles(
    interval: str,
    limit: int = 200,
    fetcher: Callable = http_get_json,
) -> FeedResult:
    """Binance public klines."""
    if interval not in SUPPORTED_INTERVALS:
        return FeedResult(
            source="binance",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"unsupported interval: {interval}",
        )
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit={limit}"
    )
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="binance",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    if not isinstance(raw, list) or not raw:
        return FeedResult(
            source="binance",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="empty klines",
        )
    candles = []
    for k in raw:
        candles.append({
            "open_time_ms": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            # Binance closeTime is the last ms of the candle. Treat as
            # exclusive end by adding 1ms — this is what the Phase 1
            # resolver also does.
            "close_time_ms": int(k[6]) + 1,
        })
    return FeedResult(
        source="binance",
        kind=f"candles_{interval}",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={"interval": interval, "candles": candles},
    )


# ── Coinbase Exchange (fallback 1) ─────────────────────────────────────────
_COINBASE_GRANULARITY = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "4h": 14400,  # 4h not natively supported, marked failed below
    "1d": 86400,
}


def fetch_coinbase_candles(
    interval: str,
    limit: int = 200,
    fetcher: Callable = http_get_json,
) -> FeedResult:
    """Coinbase Exchange public candles. Returns most-recent-first; we sort."""
    g = _COINBASE_GRANULARITY.get(interval)
    # Coinbase only supports {60,300,900,3600,21600,86400}. 4h not supported.
    if interval == "4h" or g is None or g == 14400:
        return FeedResult(
            source="coinbase",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"coinbase has no {interval} candle granularity",
        )
    url = (
        f"https://api.exchange.coinbase.com/products/BTC-USD/candles"
        f"?granularity={g}"
    )
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="coinbase",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    if not isinstance(raw, list) or not raw:
        return FeedResult(
            source="coinbase",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="empty candles",
        )
    # Coinbase: [time, low, high, open, close, volume], sec timestamps,
    # newest first. Sort ascending and convert.
    raw_sorted = sorted(raw, key=lambda r: int(r[0]))[-limit:]
    candles = []
    interval_ms = INTERVAL_MS[interval]
    for r in raw_sorted:
        ot = int(r[0]) * 1000
        candles.append({
            "open_time_ms": ot,
            "low": float(r[1]),
            "high": float(r[2]),
            "open": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
            "close_time_ms": ot + interval_ms,
        })
    return FeedResult(
        source="coinbase",
        kind=f"candles_{interval}",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={"interval": interval, "candles": candles},
    )


# ── Kraken (fallback 2) ────────────────────────────────────────────────────
_KRAKEN_INTERVAL_MIN = {
    "1m": 1, "5m": 5, "15m": 15,
    "1h": 60, "4h": 240, "1d": 1440,
}


def fetch_kraken_candles(
    interval: str,
    limit: int = 200,
    fetcher: Callable = http_get_json,
) -> FeedResult:
    """Kraken public OHLC."""
    mins = _KRAKEN_INTERVAL_MIN.get(interval)
    if mins is None:
        return FeedResult(
            source="kraken",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"unsupported interval: {interval}",
        )
    url = f"https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={mins}"
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="kraken",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    if not isinstance(raw, dict) or raw.get("error"):
        return FeedResult(
            source="kraken",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"kraken error payload: {raw.get('error') if isinstance(raw, dict) else 'malformed'}",
        )
    result = raw.get("result") or {}
    # The OHLC array is keyed by Kraken's pair name (e.g. "XXBTZUSD").
    series = None
    for k, v in result.items():
        if k == "last":
            continue
        if isinstance(v, list):
            series = v
            break
    if not series:
        return FeedResult(
            source="kraken",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="no OHLC array in kraken response",
        )
    candles = []
    interval_ms = INTERVAL_MS[interval]
    for r in series[-limit:]:
        # [time, open, high, low, close, vwap, volume, count]
        ot = int(r[0]) * 1000
        candles.append({
            "open_time_ms": ot,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[6]),
            "close_time_ms": ot + interval_ms,
        })
    return FeedResult(
        source="kraken",
        kind=f"candles_{interval}",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={"interval": interval, "candles": candles},
    )


# ── CoinGecko (fallback 3 — daily only) ────────────────────────────────────
def fetch_coingecko_candles(
    interval: str,
    limit: int = 200,
    fetcher: Callable = http_get_json,
) -> FeedResult:
    """CoinGecko OHLC. Public endpoint only returns daily/4h coarse OHLC.

    We restrict to `1d` and `4h` for honesty: no synthesizing OHLC from
    market_chart's price-only series.
    """
    if interval not in ("4h", "1d"):
        return FeedResult(
            source="coingecko",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"coingecko OHLC only used for 4h/1d (got {interval})",
        )
    days_map = {"4h": "30", "1d": "180"}
    days = days_map[interval]
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
        f"?vs_currency=usd&days={days}"
    )
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="coingecko",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    if not isinstance(raw, list) or not raw:
        return FeedResult(
            source="coingecko",
            kind=f"candles_{interval}",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="empty coingecko ohlc",
        )
    candles = []
    interval_ms = INTERVAL_MS[interval]
    for r in raw[-limit:]:
        # [time_ms, open, high, low, close]
        ot = int(r[0])
        # CoinGecko gives no volume; mark None and let consumers ignore.
        candles.append({
            "open_time_ms": ot,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": None,
            "close_time_ms": ot + interval_ms,
        })
    return FeedResult(
        source="coingecko",
        kind=f"candles_{interval}",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={"interval": interval, "candles": candles},
    )


# ── Default provider chains by interval ────────────────────────────────────
def default_provider_chain(interval: str, fetcher: Callable = http_get_json):
    """Return ordered list of zero-arg callables for the fallback runner."""
    chain = [
        lambda: fetch_binance_candles(interval, fetcher=fetcher),
        lambda: fetch_coinbase_candles(interval, fetcher=fetcher),
        lambda: fetch_kraken_candles(interval, fetcher=fetcher),
    ]
    if interval in ("4h", "1d"):
        chain.append(lambda: fetch_coingecko_candles(interval, fetcher=fetcher))
    # Annotate names for debugging.
    chain[0].__name__ = "binance"      # type: ignore[attr-defined]
    chain[1].__name__ = "coinbase"     # type: ignore[attr-defined]
    chain[2].__name__ = "kraken"       # type: ignore[attr-defined]
    if len(chain) > 3:
        chain[3].__name__ = "coingecko"  # type: ignore[attr-defined]
    return chain


def closed_candles(result: FeedResult, now=None) -> list[dict]:
    """Return result.data['candles'] with the in-progress candle dropped.

    Returns [] if the result has no usable data.
    """
    if result.status != STATUS_OK or not result.data:
        return []
    return drop_incomplete_candle(result.data["candles"], now=now)
