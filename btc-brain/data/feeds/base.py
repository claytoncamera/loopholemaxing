"""
Feed abstraction primitives for the BTC Brain data layer.

Design rules (Phase 2 invariants):
  * Never fabricate OHLC. If a source fails or is incomplete, return a
    `FeedResult` with `status` of `failed` / `stale` / `degraded` and
    `data=None`. The caller decides what to do.
  * Never include the in-progress (live) candle in a list of "closed
    candles". Helpers here drop it explicitly.
  * Always preserve the source label and a fetched-at timestamp so the
    frontend / artifacts can show provenance and freshness.
  * Only public, no-secret HTTP endpoints are used.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ── Status enum ────────────────────────────────────────────────────────────
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"   # got data but missing something non-critical
STATUS_STALE = "stale"         # last good data exists but exceeds freshness budget
STATUS_FAILED = "failed"       # no usable data at all
STATUSES = {STATUS_OK, STATUS_DEGRADED, STATUS_STALE, STATUS_FAILED}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── HTTP helper ────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 15
DEFAULT_UA = "btc-brain-data/1 (+https://loopholemaxing.com/btc-brain/)"


class HttpError(Exception):
    """Wraps any HTTP / network problem from a feed call."""


def http_get_json(url: str, timeout: int = DEFAULT_TIMEOUT, ua: str = DEFAULT_UA) -> Any:
    """Fetch a public JSON endpoint. Raises HttpError on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError) as e:
        raise HttpError(f"GET {url} failed: {e}") from e
    except (ValueError, json.JSONDecodeError) as e:
        raise HttpError(f"GET {url} returned non-JSON: {e}") from e


# ── Result types ───────────────────────────────────────────────────────────
@dataclass
class FeedResult:
    """One attempt at one source.

    `data` shape depends on the feed kind. `status` is always set, even when
    `data is not None` (e.g. degraded). `latency_ms` is for source-health.
    """

    source: str                                        # e.g. "binance"
    kind: str                                          # e.g. "candles_1h"
    status: str                                        # one of STATUSES
    fetched_at: str                                    # ISO-8601 UTC
    data: Any = None                                   # provider-specific
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "kind": self.kind,
            "status": self.status,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "notes": list(self.notes),
        }


# ── Run a list of providers with fallback ──────────────────────────────────
def run_with_fallback(
    providers: list[Callable[[], FeedResult]],
    accept: Callable[[FeedResult], bool] | None = None,
) -> tuple[FeedResult, list[FeedResult]]:
    """Try each provider in order. Return (chosen, all_attempts).

    `accept` decides whether a provider's result is good enough to stop the
    fallback chain. Default: accept only `status == STATUS_OK`.

    `chosen` is always a FeedResult (never None). When everything failed it
    still has provenance about *which* sources were tried.
    """
    if accept is None:
        accept = lambda r: r.status == STATUS_OK
    attempts: list[FeedResult] = []
    chosen: FeedResult | None = None
    for fn in providers:
        t0 = time.monotonic()
        try:
            r = fn()
        except Exception as e:  # provider raised something unexpected
            r = FeedResult(
                source=getattr(fn, "__name__", "unknown"),
                kind="unknown",
                status=STATUS_FAILED,
                fetched_at=utc_now_iso(),
                error=f"provider raised: {e}",
            )
        if r.latency_ms is None:
            r.latency_ms = int((time.monotonic() - t0) * 1000)
        attempts.append(r)
        if accept(r):
            chosen = r
            break
    if chosen is None:
        last = attempts[-1] if attempts else FeedResult(
            source="none",
            kind="unknown",
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="no providers configured",
        )
        # Bubble up a synthetic "all-failed" result that still carries the
        # most recent attempt's source label so the frontend can show
        # which provider it last tried.
        chosen = FeedResult(
            source=last.source,
            kind=last.kind,
            status=STATUS_FAILED,
            fetched_at=utc_now_iso(),
            error="all providers failed",
            notes=[a.source + ":" + a.status for a in attempts],
        )
    return chosen, attempts


# ── Closed-candle helper (Phase 0 invariant) ───────────────────────────────
def drop_incomplete_candle(
    candles: list[dict],
    now: Optional[datetime] = None,
) -> list[dict]:
    """Drop the trailing in-progress candle.

    Each candle dict must carry an integer `close_time_ms` (epoch ms,
    exclusive end of the candle). A candle whose `close_time_ms` is in the
    future relative to `now` is considered live and removed.

    This is the Python mirror of the JS `closedCandlesOnly` helper enforced
    by the Phase 0 truth scan.
    """
    now = now or utc_now()
    now_ms = int(now.timestamp() * 1000)
    return [c for c in candles if int(c["close_time_ms"]) <= now_ms]
