"""
Sentiment feed: alternative.me Fear & Greed (primary) → CoinGecko global
sentiment indicator (fallback). Both are public, no-key endpoints.
"""
from __future__ import annotations

from typing import Callable

from .base import (
    FeedResult,
    HttpError,
    STATUS_FAILED,
    STATUS_OK,
    http_get_json,
    utc_now_iso,
)


def fetch_fng_sentiment(fetcher: Callable = http_get_json) -> FeedResult:
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="alternative.me",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    arr = (raw or {}).get("data") or []
    if not arr:
        return FeedResult(
            source="alternative.me",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="empty fng response",
        )
    row = arr[0]
    try:
        value = int(row["value"])
    except (KeyError, ValueError, TypeError) as e:
        return FeedResult(
            source="alternative.me",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=f"malformed fng row: {e}",
        )
    return FeedResult(
        source="alternative.me",
        kind="sentiment",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={
            "fear_greed_value": value,
            "fear_greed_label": row.get("value_classification"),
            "sample_timestamp": row.get("timestamp"),
            "indicator": "fear_greed_btc_crypto",
        },
    )


def fetch_coingecko_sentiment(fetcher: Callable = http_get_json) -> FeedResult:
    """Use CoinGecko coin sentiment up/down votes as a fallback indicator.

    Mapped to a 0..100 scale via `up_pct` so consumers can keep one schema.
    """
    url = "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=false&community_data=true&developer_data=false&sparkline=false"
    try:
        raw = fetcher(url)
    except HttpError as e:
        return FeedResult(
            source="coingecko",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error=str(e),
        )
    if not isinstance(raw, dict):
        return FeedResult(
            source="coingecko",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="non-dict response",
        )
    up = raw.get("sentiment_votes_up_percentage")
    down = raw.get("sentiment_votes_down_percentage")
    if up is None or down is None:
        return FeedResult(
            source="coingecko",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="no sentiment fields",
        )
    try:
        up_pct = float(up)
    except (ValueError, TypeError):
        return FeedResult(
            source="coingecko",
            kind="sentiment",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="bad sentiment value",
        )
    return FeedResult(
        source="coingecko",
        kind="sentiment",
        status=STATUS_OK,
        fetched_at=utc_now_iso(),
        data={
            "fear_greed_value": int(round(up_pct)),
            "fear_greed_label": "coingecko_up_pct_proxy",
            "sample_timestamp": None,
            "indicator": "coingecko_sentiment_up_pct",
        },
    )


def default_provider_chain(fetcher: Callable = http_get_json):
    chain = [
        lambda: fetch_fng_sentiment(fetcher=fetcher),
        lambda: fetch_coingecko_sentiment(fetcher=fetcher),
    ]
    chain[0].__name__ = "alternative.me"  # type: ignore[attr-defined]
    chain[1].__name__ = "coingecko"        # type: ignore[attr-defined]
    return chain
