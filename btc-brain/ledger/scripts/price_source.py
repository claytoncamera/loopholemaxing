"""
Price source for the resolver.

Default: Binance public klines (1h candle close). Fallbacks (keyless):
CoinGecko, then Kraken. All three resolve the SAME quantity — the close of
the 1h candle whose interval *ends at* target_time, i.e. the candle that
CLOSES at the horizon boundary — so accuracy math stays consistent no matter
which source answered.

Correctness note (resolver off-by-one fix):
Forecasts are issued on the hour grid and their target_time lands on an
exact hour boundary (e.g. issued 05:00Z, 1h horizon -> target 06:00Z). The
price that resolves a 1h forecast is the close of the 05:00->06:00 candle
(Binance closeTime ~= 05:59:59.999Z, i.e. close_time ~= target). The
previous rule `open_time <= target < close_time` instead selected the
06:00->07:00 candle and returned its 07:00 close — one full candle late,
which corrupted actual_close / direction / Brier / logloss for every
horizon. We now match the candle whose close_time == target (to the
second), the bar that finalizes exactly at the horizon end.

We refuse incomplete candles: if the matched candle's `closeTime` > now,
we raise NotYet.

Batching (resolver-never-times-out fix):
Resolving a backlog of N forecasts used to cost N Binance round-trips, which
blew past the workflow's 5-minute timeout. `fetch_closes_for_targets` now
fetches the whole covering range of 1h klines in as few requests as possible
(Binance allows 1000 candles/request; we page) and builds an in-memory map
keyed by candle close_time, so every target resolves by lookup — not a fresh
request.
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

from ledger import parse_iso_utc


PRICE_SOURCE_VERSION = "binance:BTCUSDT:1h"

# Provenance tags written to the resolution record's `price_source` field.
SOURCE_BINANCE = "binance"
SOURCE_COINGECKO = "coingecko"
SOURCE_KRAKEN = "kraken"

_HOUR = timedelta(hours=1)
_HOUR_MS = 3_600_000
# Candle-match tolerance: Binance closeTime is the last ms of the bar
# (…:59.999), so a bar that finalizes at `target` has close_time within one
# second below it. One second absorbs that and any sub-second jitter.
_MATCH_TOL_S = 1.0


class NotYet(Exception):
    """Target candle has not closed yet."""


class PriceFetchError(Exception):
    pass


@dataclass
class Candle:
    open_time: datetime  # UTC
    close_time: datetime  # UTC (exclusive end; ~target for the resolving bar)
    close_price: float
    source: str = PRICE_SOURCE_VERSION


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


# ── Binance ──────────────────────────────────────────────────────────────────
# Hosts tried in order. api.binance.com is frequently geo-blocked from cloud
# CI runners (HTTP 451); data-api.binance.vision is Binance's public
# market-data mirror that serves the same klines without that restriction.
_BINANCE_HOSTS = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0
_BINANCE_PAGE_LIMIT = 1000  # max candles Binance returns per klines request.


def _http_get_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "btc-brain-ledger/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch one page of klines with host fallback and exponential backoff.

    Empty/transient failures (network errors, 5xx, geo-blocks) are retried
    across both hosts. Only a total failure across every host+attempt raises
    PriceFetchError — so a single blocked request no longer leaves forecasts
    permanently unresolved.
    """
    path = (
        f"/api/v3/klines?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit={_BINANCE_PAGE_LIMIT}"
    )
    last_err: Optional[Exception] = None
    for attempt in range(_MAX_ATTEMPTS):
        for host in _BINANCE_HOSTS:
            try:
                return _http_get_json(host + path)
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


def _binance_range_map(start_ms: int, end_ms: int, fetcher) -> dict[int, Candle]:
    """Fetch [start_ms, end_ms] of 1h klines, paging past the 1000-candle cap.

    Returns {close_time_epoch_s: Candle}. Binance's startTime/endTime are
    inclusive on the candle's open; each page returns up to 1000 candles, so
    for a range wider than 1000 hours we advance the cursor past the last
    open_time and fetch again until the page is short (fewer than the cap) or
    the cursor crosses end_ms.
    """
    out: dict[int, Candle] = {}
    cursor = start_ms
    while cursor <= end_ms:
        page = fetcher("BTCUSDT", "1h", cursor, end_ms)
        if not page:
            break
        last_open_ms = cursor
        for k in page:
            ot = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            ct = datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc)
            out[round(ct.timestamp())] = Candle(
                open_time=ot,
                close_time=ct,
                close_price=float(k[4]),
                source=PRICE_SOURCE_VERSION,
            )
            last_open_ms = k[0]
        # Short page → no more data in range.
        if len(page) < _BINANCE_PAGE_LIMIT:
            break
        # Advance one hour past the last open we saw; guard against no progress.
        nxt = last_open_ms + _HOUR_MS
        if nxt <= cursor:
            break
        cursor = nxt
    return out


# ── CoinGecko (fallback 1) ────────────────────────────────────────────────────
# /coins/bitcoin/ohlc?vs_currency=usd&days=1 returns [[open_ms,o,h,l,c],...]
# as 30-minute bars whose timestamp is the bar's OPEN, aligned to :00/:30.
# The bar that CLOSES at hour boundary H is the one opening at H-30min; its
# close is the hourly-boundary close we want. CoinGecko's free OHLC only
# yields sub-hourly bars for days=1 (≈ last 24h); older/ wider granularities
# (4h at days≥2) cannot align to an arbitrary hour, so CoinGecko only answers
# targets within the last ~24h. Cross-exchange price differs from Binance by
# ~0.1%, acceptable only when Binance is fully unavailable.
_COINGECKO_OHLC_URL = (
    "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=1"
)
_CG_BAR_MS = 1_800_000  # 30 minutes


def _coingecko_fetch(url: str = _COINGECKO_OHLC_URL):
    return _http_get_json(url, timeout=20)


def _coingecko_range_map(
    start_ms: int, end_ms: int, fetcher=_coingecko_fetch
) -> dict[int, Candle]:
    """Map {close_time_epoch_s: Candle} for hour-aligned CoinGecko closes.

    Only 30-min bars whose open is on a :30 mark contribute an hour-boundary
    close (open+30min lands on :00). We index by that close second so callers
    can look up an exact target hour.
    """
    rows = fetcher()
    out: dict[int, Candle] = {}
    for row in rows:
        open_ms = int(row[0])
        close_ms = open_ms + _CG_BAR_MS
        # Keep only bars that close exactly on an hour boundary.
        if close_ms % _HOUR_MS != 0:
            continue
        if close_ms < start_ms or close_ms > end_ms + _HOUR_MS:
            continue
        ot = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
        ct = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
        out[round(ct.timestamp())] = Candle(
            open_time=ot, close_time=ct, close_price=float(row[4]),
            source=SOURCE_COINGECKO,
        )
    return out


# ── Kraken (fallback 2) ───────────────────────────────────────────────────────
# /0/public/OHLC?pair=XBTUSD&interval=60&since=<sec> returns
# result[pair] = [[time, o,h,l,c,vwap,vol,count],...] where `time` is the bar's
# OPEN in SECONDS, aligned to the hour. The bar that CLOSES at hour H is the
# one with time == H-3600; its close (index 4) is the hourly-boundary close.
# Kraken caps at ~720 bars per response and `since` is inclusive on open, so we
# page forward by advancing `since` past the last open we received. Kraken can
# serve arbitrarily old hours, making it the deep historical fallback.
_KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60&since={since}"


def _kraken_fetch(since_s: int):
    return _http_get_json(_KRAKEN_URL.format(since=since_s), timeout=20)


def _kraken_range_map(
    start_ms: int, end_ms: int, fetcher=_kraken_fetch
) -> dict[int, Candle]:
    """Map {close_time_epoch_s: Candle} from Kraken 1h OHLC, paging by `since`."""
    out: dict[int, Candle] = {}
    # `since` is inclusive on open; the first bar we need opens at start-1h
    # (it closes at start). Step back one hour to be safe.
    since_s = max(0, start_ms // 1000 - 3600)
    end_s = end_ms // 1000
    guard = 0
    while since_s <= end_s and guard < 100:
        guard += 1
        payload = fetcher(since_s)
        if payload.get("error"):
            raise PriceFetchError(f"kraken error: {payload['error']}")
        result = payload.get("result", {})
        rows = None
        for key, val in result.items():
            if key == "last":
                continue
            rows = val
            break
        if not rows:
            break
        last_open_s = since_s
        for row in rows:
            open_s = int(row[0])
            close_s = open_s + 3600
            ct = datetime.fromtimestamp(close_s, tz=timezone.utc)
            ot = datetime.fromtimestamp(open_s, tz=timezone.utc)
            out[close_s] = Candle(
                open_time=ot, close_time=ct, close_price=float(row[4]),
                source=SOURCE_KRAKEN,
            )
            last_open_s = open_s
        if last_open_s <= since_s:
            break
        since_s = last_open_s + 3600
    return out


# ── Source registry (Binance -> CoinGecko -> Kraken) ──────────────────────────
def _default_sources():
    """(tag, range_map_fn) in fallback order. Each fn: (start_ms,end_ms)->map."""
    return [
        (SOURCE_BINANCE, lambda s, e: _binance_range_map(s, e, _binance_klines)),
        (SOURCE_COINGECKO, lambda s, e: _coingecko_range_map(s, e)),
        (SOURCE_KRAKEN, lambda s, e: _kraken_range_map(s, e)),
    ]


def _lookup(cmap: dict[int, Candle], target: datetime) -> Optional[Candle]:
    """Return the candle whose close_time == target (within tolerance)."""
    ts = round(target.timestamp())
    for delta in (0, -1, 1):
        c = cmap.get(ts + delta)
        if c is not None and abs((c.close_time - target).total_seconds()) <= _MATCH_TOL_S:
            return c
    return None


def fetch_closes_for_targets(
    target_time_isos: Iterable[str],
    now: Optional[datetime] = None,
    sources=None,
    stats: Optional[dict] = None,
) -> dict[str, Candle]:
    """Batch-resolve many targets to their hour-boundary closes.

    Returns {target_iso: Candle} for every target whose closing candle has
    finalized and was found in *some* source. Targets whose candle is not yet
    closed (closeTime > now) are omitted with no error — the caller treats a
    missing key as NotYet. Targets no source can supply are also omitted.

    The fallback chain runs once over the whole covering range, not per
    target: we fetch Binance for the full [min,max] span (paged), resolve
    every target we can from that map, and only hit CoinGecko/Kraken for the
    targets still unresolved. `stats` (if given) is populated with request and
    per-source counts for observability.
    """
    now = now or datetime.now(timezone.utc)
    sources = sources or _default_sources()

    # Parse + keep only targets whose closing candle has finalized.
    parsed: dict[str, datetime] = {}
    for iso in target_time_isos:
        t = parse_iso_utc(iso)
        # The candle closes at `t`; it is final once now has reached t.
        if t <= now:
            parsed[iso] = t
    if not parsed:
        return {}

    span_start_ms = int((min(parsed.values()) - _HOUR).timestamp() * 1000)
    span_end_ms = int(max(parsed.values()).timestamp() * 1000)

    resolved: dict[str, Candle] = {}
    pending = dict(parsed)
    if stats is not None:
        stats.setdefault("source_hits", {})
        stats.setdefault("source_errors", {})

    for tag, range_fn in sources:
        if not pending:
            break
        try:
            cmap = range_fn(span_start_ms, span_end_ms)
        except (PriceFetchError, urllib.error.URLError, ValueError, KeyError) as e:
            if stats is not None:
                stats["source_errors"][tag] = str(e)
            continue
        hit = 0
        for iso, t in list(pending.items()):
            c = _lookup(cmap, t)
            if c is None:
                continue
            # Defensive: never accept a not-yet-final candle.
            if c.close_time > now:
                continue
            resolved[iso] = c
            del pending[iso]
            hit += 1
        if stats is not None and hit:
            stats["source_hits"][tag] = stats["source_hits"].get(tag, 0) + hit

    return resolved


def fetch_close_for_target(
    target_time_iso: str,
    now: Optional[datetime] = None,
    fetcher=_binance_klines,
) -> Candle:
    """Return the 1h Binance candle that CLOSES at target_time (single-target).

    Preserved for callers/tests that resolve a single target. Uses Binance
    only (with host fallback + backoff via `fetcher`). The off-by-one rule is
    identical to the batched path: match the candle whose close_time ==
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
        if abs((ct - target).total_seconds()) <= _MATCH_TOL_S:
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
    """Build a Binance-shaped fetcher closure for tests.

    `candles` is a list of (open_ms, close_ms, close_price). The closure
    respects the [start_ms, end_ms] window and the 1000-candle page cap so
    paging logic is exercised the same way the real API would drive it.
    """
    rows = sorted(candles, key=lambda c: c[0])

    def _f(symbol, interval, start_ms, end_ms):
        out = []
        for o, c, px in rows:
            if c < start_ms or o > end_ms:
                continue
            out.append([o, "0", "0", "0", str(px), "0", c, "0", 0, "0", "0", "0"])
            if len(out) >= _BINANCE_PAGE_LIMIT:
                break
        return out
    return _f
