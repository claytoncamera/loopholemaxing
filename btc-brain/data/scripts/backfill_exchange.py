#!/usr/bin/env python3
"""
backfill_exchange.py — one-time deep backfill of hourly BTC-USD candles
from Coinbase Exchange public REST (Kraken OHLC as fallback), merged
into btc-brain/data/history/candles_1h.jsonl.

The snapshot pipeline only started 2026-06-29; Phase 3 ML training
wants years, not weeks. Coinbase Exchange serves unauthenticated
historical candles at 300 bars/request:

    GET api.exchange.coinbase.com/products/BTC-USD/candles
        ?granularity=3600&start=<ISO>&end=<ISO>
    → [[time_s, low, high, open, close, volume], ...]  (newest first)

We page forward in 300-hour windows from --start (default 2024-08-01)
to now, sleeping ~0.3s between calls (public rate limit is 10 req/s;
we stay far under it). Kraken's OHLC endpoint only returns the most
recent ~720 hourly bars, so it can only patch the tail — it is used as
a fallback when Coinbase errors on a window.

Rows are merged with the same dedupe/sort/idempotent merge as
archive.py; existing rows (from the live snapshotter or the git-log
reconstruction) win on duplicate open_time_ms, so provenance of
already-archived bars never changes. Backfilled rows carry
source="coinbase-backfill" (or "kraken-backfill").

Safe to re-run. Usage:

    python3 btc-brain/data/scripts/backfill_exchange.py [--start 2024-08-01]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive import DEFAULT_HISTORY, REPO_ROOT, merge_candles, warn  # noqa: E402

CB_URL = ("https://api.exchange.coinbase.com/products/BTC-USD/candles"
          "?granularity=3600&start={start}&end={end}")
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
UA = "BTC-Brain-Backfill/1.0 (+https://loopholemaxing.com/btc-brain)"
PAGE_HOURS = 300
SLEEP_S = 0.3


def http_json(url: str, retries: int = 4):
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            wait = 2 ** attempt
            if e.code == 429:
                try:
                    wait = max(wait, int((e.headers or {}).get("Retry-After", 0)))
                except (TypeError, ValueError):
                    pass
            warn(f"HTTP {e.code} attempt {attempt}/{retries} — waiting {wait}s: {url[:90]}")
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            warn(f"{e.__class__.__name__} attempt {attempt}/{retries} — waiting {wait}s")
        if attempt < retries:
            time.sleep(wait)
    return None


def coinbase_window(start: datetime, end: datetime) -> list[dict] | None:
    url = CB_URL.format(start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        end=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    raw = http_json(url)
    if not isinstance(raw, list):
        return None
    rows = []
    for c in raw:  # [time_s, low, high, open, close, volume]
        try:
            rows.append({
                "open_time_ms": int(c[0]) * 1000,
                "open": float(c[3]),
                "high": float(c[2]),
                "low": float(c[1]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "source": "coinbase-backfill",
            })
        except (TypeError, ValueError, IndexError):
            continue
    return rows


def kraken_recent() -> list[dict]:
    """Kraken fallback — only the most recent ~720 hourly bars exist."""
    raw = http_json(KRAKEN_URL)
    if not isinstance(raw, dict) or "result" not in raw:
        return []
    pair_rows = raw["result"].get("XXBTZUSD", [])
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = []
    for c in pair_rows:  # [time, open, high, low, close, vwap, volume, count]
        try:
            open_ms = int(c[0]) * 1000
            if open_ms + 3_600_000 > now_ms:
                continue  # in-progress bar
            rows.append({
                "open_time_ms": open_ms,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[6]),
                "source": "kraken-backfill",
            })
        except (TypeError, ValueError, IndexError):
            continue
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2024-08-01",
                   help="UTC date to backfill from (default 2024-08-01)")
    args = p.parse_args(argv)

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # Only closed bars: stop at the top of the current hour.
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    all_rows: list[dict] = []
    cursor = start
    pages = failures = 0
    while cursor < now:
        window_end = min(cursor + timedelta(hours=PAGE_HOURS - 1), now)
        rows = coinbase_window(cursor, window_end)
        pages += 1
        if rows is None:
            failures += 1
            warn(f"coinbase window failed: {cursor:%Y-%m-%d %H:%M} → {window_end:%Y-%m-%d %H:%M}")
        else:
            all_rows.extend(r for r in rows
                            if r["open_time_ms"] < now.timestamp() * 1000)
        if pages % 10 == 0:
            print(f"[backfill-cb] page {pages}: cursor {cursor:%Y-%m-%d}, "
                  f"{len(all_rows)} rows so far")
        cursor = window_end + timedelta(hours=1)
        time.sleep(SLEEP_S)

    print(f"[backfill-cb] coinbase: {pages} pages, {failures} failed windows, "
          f"{len(all_rows)} rows")

    if failures:
        kr = kraken_recent()
        print(f"[backfill-cb] kraken fallback: {len(kr)} recent rows")
        all_rows.extend(kr)

    history_path = DEFAULT_HISTORY / "candles_1h.jsonl"
    added, total = merge_candles(history_path, all_rows)
    print(f"[backfill-cb] merged: +{added} new, {total} total in "
          f"{history_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
