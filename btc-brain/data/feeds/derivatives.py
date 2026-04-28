"""
Derivatives feed: funding rate, open interest, long/short ratio.

Provider chain (all public, no-secret endpoints):

  1. Binance USDT-margined futures (often returns HTTP 451 from cloud
     hosts, so this slot is best-effort).
  2. OKX BTC-USDT-SWAP — funding-rate, open-interest, mark-price and
     (best-effort) long/short account ratio via the rubik stat endpoint.
  3. Bybit linear BTCUSDT — funding, OI, mark and long/short ratio.
  4. Deribit BTC-PERPETUAL — funding + mark fallback.

We never synthesize. If a sub-field is missing the result is `degraded`
or `partial_ok` (see status semantics) and that field is null.
"""
from __future__ import annotations

from typing import Callable

from .base import (
    FeedResult,
    HttpError,
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_OK,
    http_get_json,
    utc_now_iso,
)


# Sub-field categories used to decide ok / partial_ok / degraded.
_CORE_FIELDS = ("funding_rate", "open_interest_btc")
_RICH_FIELDS = ("mark_price", "long_short_ratio", "long_account_pct", "short_account_pct")


# A "partial_ok" status: core fields present but some rich fields missing.
# Treated as a soft-degraded variant — UI shows the data without flagging
# the whole pipeline as broken.
STATUS_PARTIAL_OK = "partial_ok"


def _safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _classify(data: dict) -> str:
    """Return ok / partial_ok / degraded based on which fields are present."""
    core_missing = [f for f in _CORE_FIELDS if data.get(f) is None]
    rich_missing = [f for f in _RICH_FIELDS if data.get(f) is None]
    if core_missing:
        return STATUS_DEGRADED
    if rich_missing:
        return STATUS_PARTIAL_OK
    return STATUS_OK


def _try_fetch(fetcher: Callable, url: str, notes: list, key: str):
    """Fetch a URL, swallow HttpError, append a note, return (data_or_None, ok)."""
    try:
        return fetcher(url), True
    except HttpError as e:
        notes.append(f"{key}:fail:{e}")
        return None, False


def fetch_binance_derivatives(fetcher: Callable = http_get_json) -> FeedResult:
    """Binance funding + OI + long/short."""
    urls = {
        "funding": "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
        "open_interest": "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
        "long_short": (
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
            "?symbol=BTCUSDT&period=5m&limit=1"
        ),
    }
    fetched = {}
    notes = []
    any_ok = False
    for k, u in urls.items():
        v, ok = _try_fetch(fetcher, u, notes, k)
        fetched[k] = v
        any_ok = any_ok or ok
    if not any_ok:
        return FeedResult(
            source="binance",
            kind="derivatives",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="all binance derivatives endpoints failed",
            notes=notes,
        )
    funding = fetched.get("funding") or {}
    oi = fetched.get("open_interest") or {}
    ls = fetched.get("long_short") or []
    ls_row = ls[0] if isinstance(ls, list) and ls else {}

    data = {
        "funding_rate": _safe_float(funding.get("lastFundingRate")),
        "next_funding_time_ms": (
            int(funding.get("nextFundingTime"))
            if funding.get("nextFundingTime") is not None else None
        ),
        "mark_price": _safe_float(funding.get("markPrice")),
        "open_interest_btc": _safe_float(oi.get("openInterest")),
        "long_short_ratio": _safe_float(ls_row.get("longShortRatio")),
        "long_account_pct": _safe_float(ls_row.get("longAccount")),
        "short_account_pct": _safe_float(ls_row.get("shortAccount")),
    }
    missing = [k for k, v in data.items() if v is None]
    status = _classify(data)
    if missing:
        notes.append(f"missing:{','.join(missing)}")
    return FeedResult(
        source="binance",
        kind="derivatives",
        status=status,
        fetched_at=utc_now_iso(),
        data=data,
        notes=notes,
    )


def fetch_okx_derivatives(fetcher: Callable = http_get_json) -> FeedResult:
    """OKX BTC-USDT-SWAP — funding, OI, mark, and best-effort long/short."""
    urls = {
        "funding": "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        "open_interest": "https://www.okx.com/api/v5/public/open-interest?instId=BTC-USDT-SWAP",
        "mark_price": "https://www.okx.com/api/v5/public/mark-price?instId=BTC-USDT-SWAP",
        # Public rubik long/short ratio. May be unavailable from some
        # regions — best effort, never required.
        "long_short": (
            "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio"
            "?ccy=BTC&period=5m"
        ),
    }
    fetched = {}
    notes = []
    any_ok = False
    for k, u in urls.items():
        v, ok = _try_fetch(fetcher, u, notes, k)
        fetched[k] = v
        any_ok = any_ok or ok
    if not any_ok:
        return FeedResult(
            source="okx",
            kind="derivatives",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="all okx derivatives endpoints failed",
            notes=notes,
        )
    funding_data = ((fetched.get("funding") or {}).get("data") or [])
    oi_data = ((fetched.get("open_interest") or {}).get("data") or [])
    mark_data = ((fetched.get("mark_price") or {}).get("data") or [])
    funding_row = funding_data[0] if funding_data else {}
    oi_row = oi_data[0] if oi_data else {}
    mark_row = mark_data[0] if mark_data else {}

    # Rubik long/short payload looks like:
    #   {"code":"0","data":[[ts, ratio], [ts, ratio], ...]}
    # The most recent entry is the last item. Each "ratio" is the
    # long-account divided by short-account ratio (a single scalar).
    ls_payload = fetched.get("long_short") or {}
    ls_rows = ls_payload.get("data") or []
    ls_ratio = None
    if ls_rows:
        last = ls_rows[-1]
        if isinstance(last, list) and len(last) >= 2:
            ls_ratio = _safe_float(last[1])

    data = {
        "funding_rate": _safe_float(funding_row.get("fundingRate")),
        "next_funding_time_ms": (
            int(funding_row.get("nextFundingTime"))
            if funding_row.get("nextFundingTime") not in (None, "") else None
        ),
        "mark_price": _safe_float(mark_row.get("markPx")),
        # OKX returns OI in contracts; oiCcy is in BTC.
        "open_interest_btc": _safe_float(oi_row.get("oiCcy")),
        "long_short_ratio": ls_ratio,
        # OKX rubik does not expose absolute long/short percentages on this
        # endpoint — only the ratio. We never fabricate the breakdown.
        "long_account_pct": None,
        "short_account_pct": None,
    }
    missing = [k for k, v in data.items() if v is None]
    status = _classify(data)
    if missing:
        notes.append(f"missing:{','.join(missing)}")
    return FeedResult(
        source="okx",
        kind="derivatives",
        status=status,
        fetched_at=utc_now_iso(),
        data=data,
        notes=notes,
    )


def fetch_bybit_derivatives(fetcher: Callable = http_get_json) -> FeedResult:
    """Bybit linear BTCUSDT — public market endpoints, no auth."""
    urls = {
        # Tickers gives funding rate, mark price, open interest in BTC,
        # and last price in one call.
        "tickers": "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT",
        # Public account long/short ratio for retail traders. Period
        # values: 5min, 15min, 30min, 1h, 4h, 1d.
        "long_short": (
            "https://api.bybit.com/v5/market/account-ratio"
            "?category=linear&symbol=BTCUSDT&period=5min&limit=1"
        ),
    }
    fetched = {}
    notes = []
    any_ok = False
    for k, u in urls.items():
        v, ok = _try_fetch(fetcher, u, notes, k)
        fetched[k] = v
        any_ok = any_ok or ok
    if not any_ok:
        return FeedResult(
            source="bybit",
            kind="derivatives",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="all bybit derivatives endpoints failed",
            notes=notes,
        )

    tickers = fetched.get("tickers") or {}
    rows = (tickers.get("result") or {}).get("list") or []
    row = rows[0] if rows else {}

    ls_payload = fetched.get("long_short") or {}
    ls_rows = (ls_payload.get("result") or {}).get("list") or []
    ls_row = ls_rows[0] if ls_rows else {}

    funding_rate = _safe_float(row.get("fundingRate"))
    # Bybit nextFundingTime is a string of epoch ms.
    nft_raw = row.get("nextFundingTime")
    next_funding_time_ms = None
    if nft_raw not in (None, "", "0"):
        try:
            next_funding_time_ms = int(nft_raw)
        except (TypeError, ValueError):
            next_funding_time_ms = None

    long_pct = _safe_float(ls_row.get("buyRatio"))
    short_pct = _safe_float(ls_row.get("sellRatio"))
    long_short_ratio = None
    if long_pct is not None and short_pct not in (None, 0, 0.0):
        long_short_ratio = long_pct / short_pct

    data = {
        "funding_rate": funding_rate,
        "next_funding_time_ms": next_funding_time_ms,
        "mark_price": _safe_float(row.get("markPrice")),
        "open_interest_btc": _safe_float(row.get("openInterest")),
        "long_short_ratio": long_short_ratio,
        "long_account_pct": long_pct,
        "short_account_pct": short_pct,
    }
    missing = [k for k, v in data.items() if v is None]
    status = _classify(data)
    if missing:
        notes.append(f"missing:{','.join(missing)}")
    return FeedResult(
        source="bybit",
        kind="derivatives",
        status=status,
        fetched_at=utc_now_iso(),
        data=data,
        notes=notes,
    )


def fetch_deribit_derivatives(fetcher: Callable = http_get_json) -> FeedResult:
    """Deribit BTC-PERPETUAL — funding, mark, OI fallback."""
    url = (
        "https://www.deribit.com/api/v2/public/get_book_summary_by_instrument"
        "?instrument_name=BTC-PERPETUAL"
    )
    notes = []
    payload, ok = _try_fetch(fetcher, url, notes, "book_summary")
    if not ok:
        return FeedResult(
            source="deribit",
            kind="derivatives",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="deribit book_summary failed",
            notes=notes,
        )

    rows = (payload or {}).get("result") or []
    row = rows[0] if rows else {}

    # Deribit funding_8h is a fraction (e.g. 0.0001 = 0.01%). Open
    # interest is in USD contracts on Deribit BTC-PERPETUAL — the
    # contract size is $10. We do NOT convert that to BTC because we'd
    # need a mark price expressed in the right denomination and we
    # never want to fabricate a unit conversion.
    funding_rate = _safe_float(row.get("funding_8h"))
    mark_price = _safe_float(row.get("mark_price"))

    data = {
        "funding_rate": funding_rate,
        "next_funding_time_ms": None,  # Deribit funds continuously
        "mark_price": mark_price,
        "open_interest_btc": None,
        "long_short_ratio": None,
        "long_account_pct": None,
        "short_account_pct": None,
    }
    missing = [k for k, v in data.items() if v is None]
    status = _classify(data)
    if missing:
        notes.append(f"missing:{','.join(missing)}")
    return FeedResult(
        source="deribit",
        kind="derivatives",
        status=status,
        fetched_at=utc_now_iso(),
        data=data,
        notes=notes,
    )


def default_provider_chain(fetcher: Callable = http_get_json):
    chain = [
        lambda: fetch_binance_derivatives(fetcher=fetcher),
        lambda: fetch_okx_derivatives(fetcher=fetcher),
        lambda: fetch_bybit_derivatives(fetcher=fetcher),
        lambda: fetch_deribit_derivatives(fetcher=fetcher),
    ]
    chain[0].__name__ = "binance"  # type: ignore[attr-defined]
    chain[1].__name__ = "okx"      # type: ignore[attr-defined]
    chain[2].__name__ = "bybit"    # type: ignore[attr-defined]
    chain[3].__name__ = "deribit"  # type: ignore[attr-defined]
    return chain
