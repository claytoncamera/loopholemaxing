#!/usr/bin/env python3
"""
backfill_git_history.py — one-time reconstruction of hourly candle
history from the git log of btc-brain/data/public/candles_1h.json.

The snapshot workflow has committed a fresh 200-bar candles_1h.json
every 30 minutes since 2026-06-29, then overwritten it. The bars are
still recoverable: every historical version lives in git. This script
walks `git log --format=%H -- <snapshot>`, extracts each version via
`git cat-file --batch`, pulls the CLOSED candles out of each, and
merges them into btc-brain/data/history/candles_1h.jsonl using the
same dedupe/sort/idempotent merge as archive.py.

Run from anywhere inside the repo:

    python3 btc-brain/data/scripts/backfill_git_history.py

Safe to re-run; duplicates are dropped by open_time_ms (first writer
wins, and bars never change once closed).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive import (  # noqa: E402
    DEFAULT_HISTORY,
    REPO_ROOT,
    extract_closed_candles,
    merge_candles,
    warn,
)

SNAPSHOT_RELPATH = "btc-brain/data/public/candles_1h.json"


def list_versions() -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%H", "--", SNAPSHOT_RELPATH],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def read_versions(shas: list[str]) -> list[bytes]:
    """Fetch every historical blob in one `git cat-file --batch` pass."""
    batch_input = "".join(f"{sha}:{SNAPSHOT_RELPATH}\n" for sha in shas)
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=REPO_ROOT, input=batch_input.encode(), capture_output=True, check=True,
    )
    blobs: list[bytes] = []
    buf = proc.stdout
    pos = 0
    while pos < len(buf):
        nl = buf.index(b"\n", pos)
        header = buf[pos:nl].decode()
        pos = nl + 1
        parts = header.split()
        if len(parts) == 3 and parts[1] == "blob":
            size = int(parts[2])
            blobs.append(buf[pos:pos + size])
            pos += size + 1  # trailing newline
        else:
            blobs.append(b"")  # missing at that revision
    return blobs


def main() -> int:
    shas = list_versions()
    print(f"[backfill-git] {len(shas)} historical versions of {SNAPSHOT_RELPATH}")
    if not shas:
        return 0

    blobs = read_versions(shas)
    all_rows: list[dict] = []
    parsed = skipped = 0
    for sha, blob in zip(shas, blobs):
        if not blob:
            skipped += 1
            continue
        try:
            doc = json.loads(blob)
        except json.JSONDecodeError:
            warn(f"unparseable snapshot at {sha[:12]} — skipped")
            skipped += 1
            continue
        if not isinstance(doc, dict):
            skipped += 1
            continue
        all_rows.extend(extract_closed_candles(doc))
        parsed += 1

    history_path = DEFAULT_HISTORY / "candles_1h.jsonl"
    added, total = merge_candles(history_path, all_rows)
    print(f"[backfill-git] parsed {parsed} versions ({skipped} skipped), "
          f"{len(all_rows)} candle rows seen, +{added} new, {total} total in "
          f"{history_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
