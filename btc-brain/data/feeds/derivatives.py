"""
Derivatives feed: funding rate, open interest, long/short ratio.

Primary: Binance USDT-margined futures public endpoints.
Fallback: OKX public endpoints.

We never synthesize. If a sub-field is missing the result is `degraded` and
that field is null.
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


def _safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


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
        try:
            fetched[k] = fetcher(u)
            any_ok = True
        except HttpError as e:
            fetched[k] = None
            notes.append(f"{k}:fail:{e}")
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
    status = STATUS_OK if not missing else STATUS_DEGRADED
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
    """OKX BTC-USDT-SWAP funding rate and open interest fallback."""
    urls = {
        "funding": "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        "open_interest": "https://www.okx.com/api/v5/public/open-interest?instId=BTC-USDT-SWAP",
    }
    fetched = {}
    notes = []
    any_ok = False
    for k, u in urls.items():
        try:
            fetched[k] = fetcher(u)
            any_ok = True
        except HttpError as e:
            fetched[k] = None
            notes.append(f"{k}:fail:{e}")
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
    funding_row = funding_data[0] if funding_data else {}
    oi_row = oi_data[0] if oi_data else {}

    data = {
        "funding_rate": _safe_float(funding_row.get("fundingRate")),
        "next_funding_time_ms": (
            int(funding_row.get("nextFundingTime"))
            if funding_row.get("nextFundingTime") not in (None, "") else None
        ),
        "mark_price": None,
        # OKX returns OI in contracts; oiCcy is in BTC.
        "open_interest_btc": _safe_float(oi_row.get("oiCcy")),
        "long_short_ratio": None,
        "long_account_pct": None,
        "short_account_pct": None,
    }
    missing = [k for k, v in data.items() if v is None]
    status = STATUS_OK if not missing else STATUS_DEGRADED
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


def default_provider_chain(fetcher: Callable = http_get_json):
    chain = [
        lambda: fetch_binance_derivatives(fetcher=fetcher),
        lambda: fetch_okx_derivatives(fetcher=fetcher),
    ]
    chain[0].__name__ = "binance"  # type: ignore[attr-defined]
    chain[1].__name__ = "okx"      # type: ignore[attr-defined]
    return chain
