#!/usr/bin/env python3
"""
archive.py — append-only historical retention for BTC Brain snapshots.

The hourly snapshotter overwrites btc-brain/data/public/*.json in place,
so on its own the repo retains ~200 bars of candles and zero history of
derivatives / sentiment. This script runs right after each snapshot and
appends the new data to append-only JSONL files under
btc-brain/data/history/, giving Phase 3 ML training a real corpus.

Outputs (one JSON object per line, sorted, deduped, idempotent):

  history/candles_1h.jsonl
      {open_time_ms, open, high, low, close, volume, source}
      Only CLOSED candles are archived (close_time_ms <= fetched_at of
      the snapshot). The in-progress bar is never written.

  history/derivatives_history.jsonl
      {snapshot_at, source, status, funding_rate, open_interest_btc,
       long_short_ratio, mark_price, next_funding_time_ms}
      One row per snapshot, deduped by snapshot_at.

  history/sentiment_history.jsonl
      {snapshot_at, source, status, fear_greed_value, fear_greed_label,
       indicator, sample_timestamp}
      One row per snapshot, deduped by snapshot_at.

Defensive by design: this runs inside the snapshot workflow and must
NEVER fail it. A missing or corrupt snapshot file logs a warning and is
skipped; the script always exits 0 unless invoked with --strict.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLIC = REPO_ROOT / "btc-brain" / "data" / "public"
DEFAULT_HISTORY = REPO_ROOT / "btc-brain" / "data" / "history"

CANDLE_FIELDS = ("open_time_ms", "open", "high", "low", "close", "volume", "source")


def warn(msg: str) -> None:
    print(f"[archive] WARNING: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"[archive] {msg}")


def load_snapshot(path: Path) -> dict | None:
    """Load a snapshot artifact; None (with warning) on any problem."""
    if not path.exists():
        warn(f"snapshot missing: {path}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        warn(f"snapshot unreadable ({e.__class__.__name__}): {path}")
        return None
    if not isinstance(doc, dict):
        warn(f"snapshot is not an object: {path}")
        return None
    return doc


def parse_iso_ms(ts: str | None) -> int | None:
    """ISO-8601 string → epoch ms, or None."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def read_jsonl(path: Path) -> list[dict]:
    """Read existing JSONL rows; skip (and count) corrupt lines."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    bad = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                bad += 1
    if bad:
        warn(f"{path.name}: skipped {bad} corrupt line(s)")
    return rows


def write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    """Write rows atomically (tmp + rename) so a crash never truncates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


# ── Candles ──────────────────────────────────────────────────────────
def extract_closed_candles(doc: dict) -> list[dict]:
    """Pull CLOSED candles out of a candles_1h.json snapshot."""
    fetched_ms = parse_iso_ms(doc.get("fetched_at"))
    source = doc.get("source") or "unknown"
    data = doc.get("data")
    if not isinstance(data, dict):
        warn("candles snapshot has no data object")
        return []
    candles = data.get("candles")
    if not isinstance(candles, list):
        warn("candles snapshot has no candles list")
        return []

    out: list[dict] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        try:
            open_ms = int(c["open_time_ms"])
            row = {
                "open_time_ms": open_ms,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
                "source": source,
            }
        except (KeyError, TypeError, ValueError):
            continue
        # Closed = the bar's close time is at/before the snapshot moment.
        close_ms = c.get("close_time_ms")
        try:
            close_ms = int(close_ms)
        except (TypeError, ValueError):
            close_ms = open_ms + 3_600_000
        if fetched_ms is not None and close_ms > fetched_ms:
            continue  # in-progress bar — never archive
        out.append(row)
    return out


def merge_candles(history_path: Path, new_rows: list[dict]) -> tuple[int, int]:
    """Merge candle rows into history, dedupe by open_time_ms, sort.

    Returns (added, total). Existing rows win on duplicate keys so the
    archive is stable across re-runs (idempotent).
    """
    existing = read_jsonl(history_path)
    by_key: dict[int, dict] = {}
    for row in existing:
        try:
            by_key[int(row["open_time_ms"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    before = len(by_key)
    for row in new_rows:
        by_key.setdefault(row["open_time_ms"], row)
    added = len(by_key) - before
    merged = [by_key[k] for k in sorted(by_key)]
    if added or len(merged) != len(existing):
        write_jsonl_atomic(history_path, merged)
    return added, len(merged)


# ── Derivatives / sentiment ──────────────────────────────────────────
def extract_derivatives_row(doc: dict) -> dict | None:
    snapshot_at = doc.get("fetched_at")
    if not snapshot_at:
        warn("derivatives snapshot has no fetched_at")
        return None
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    return {
        "snapshot_at": snapshot_at,
        "source": doc.get("source"),
        "status": doc.get("status"),
        "funding_rate": data.get("funding_rate"),
        "open_interest_btc": data.get("open_interest_btc"),
        "long_short_ratio": data.get("long_short_ratio"),
        "mark_price": data.get("mark_price"),
        "next_funding_time_ms": data.get("next_funding_time_ms"),
    }


def extract_sentiment_row(doc: dict) -> dict | None:
    snapshot_at = doc.get("fetched_at")
    if not snapshot_at:
        warn("sentiment snapshot has no fetched_at")
        return None
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    return {
        "snapshot_at": snapshot_at,
        "source": doc.get("source"),
        "status": doc.get("status"),
        "fear_greed_value": data.get("fear_greed_value"),
        "fear_greed_label": data.get("fear_greed_label"),
        "indicator": data.get("indicator"),
        "sample_timestamp": data.get("sample_timestamp"),
    }


def merge_timestamped(history_path: Path, new_row: dict | None) -> tuple[int, int]:
    """Append a snapshot row, deduped by snapshot_at, sorted. Idempotent."""
    existing = read_jsonl(history_path)
    by_key: dict[str, dict] = {}
    for row in existing:
        key = row.get("snapshot_at")
        if isinstance(key, str):
            by_key[key] = row
    before = len(by_key)
    if new_row is not None:
        by_key.setdefault(new_row["snapshot_at"], new_row)
    added = len(by_key) - before
    merged = [by_key[k] for k in sorted(by_key)]
    if added or len(merged) != len(existing):
        write_jsonl_atomic(history_path, merged)
    return added, len(merged)


# ── Main ─────────────────────────────────────────────────────────────
def run(public_dir: Path, history_dir: Path) -> int:
    """Archive one snapshot cycle. Returns count of problems seen."""
    problems = 0

    doc = load_snapshot(public_dir / "candles_1h.json")
    if doc is None:
        problems += 1
    else:
        closed = extract_closed_candles(doc)
        added, total = merge_candles(history_dir / "candles_1h.jsonl", closed)
        info(f"candles_1h: {len(closed)} closed in snapshot, +{added} new, {total} total")

    doc = load_snapshot(public_dir / "derivatives.json")
    if doc is None:
        problems += 1
    else:
        added, total = merge_timestamped(
            history_dir / "derivatives_history.jsonl", extract_derivatives_row(doc)
        )
        info(f"derivatives: +{added} new, {total} total")

    doc = load_snapshot(public_dir / "sentiment.json")
    if doc is None:
        problems += 1
    else:
        added, total = merge_timestamped(
            history_dir / "sentiment_history.jsonl", extract_sentiment_row(doc)
        )
        info(f"sentiment: +{added} new, {total} total")

    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--public", type=Path, default=DEFAULT_PUBLIC,
                   help="snapshot artifacts directory (default: btc-brain/data/public)")
    p.add_argument("--history", type=Path, default=DEFAULT_HISTORY,
                   help="history output directory (default: btc-brain/data/history)")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero if any snapshot was skipped (default: always 0)")
    args = p.parse_args(argv)

    try:
        problems = run(args.public, args.history)
    except Exception as e:  # noqa: BLE001 — never fail the snapshot workflow
        warn(f"unexpected error: {e.__class__.__name__}: {e}")
        problems = 1

    if problems and args.strict:
        return 1
    if problems:
        warn(f"{problems} snapshot(s) skipped — exiting 0 (non-strict)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
