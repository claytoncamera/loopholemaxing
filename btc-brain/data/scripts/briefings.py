"""
Daily briefing generator and indexer.

Reads the public Phase 2 artifacts and the Phase 1 ledger accuracy
artifact and writes a single conservative, educational JSON briefing
per UTC day at:

  btc-brain/data/public/briefings/<YYYY-MM-DD>.json

It then rewrites the archive index at:

  btc-brain/data/public/briefings/index.json

so the frontend can render the static archive.

Design rules (enforced by tests/test_briefings.py):

  * No financial advice. The briefing never tells anyone to buy, sell,
    hold, enter, exit, target, stop, leverage, long, short, or take
    profit. It restates measured / observed values only.
  * No fabricated accuracy. Accuracy fields are copied straight from
    ledger/public/accuracy.json. If the ledger says display_ready is
    false (n < min_n_display), the briefing reports that explicitly and
    omits hit-rate / brier numbers.
  * No predictions. The briefing never claims a future price level or a
    probability of an outcome. It summarises source health, current key
    levels, sentiment and derivatives data — period.
  * Empty-state stays empty. If --rebuild is not passed and the
    briefings directory contains no <date>.json files, index.json is
    written as an empty stub (briefings: []), matching the pre-existing
    behaviour of the public bundle.

The script needs no secrets and no network access — it consumes the
public artifacts that snapshot.py already publishes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "briefings-v1"
INDEX_SCHEMA_VERSION = "1"
DISCLAIMER = (
    "Educational summary of public market data. Not financial advice. "
    "No buy, sell, hold, or trading instruction is given or implied. "
    "Numbers reflect observed values at generation time only."
)

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


# ── small IO helpers ───────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


# ── briefing summary builders ──────────────────────────────────────────
def _summarise_source_health(health: dict | None) -> dict:
    if not isinstance(health, dict):
        return {"available": False, "overall": None, "sources": {}}
    sources = {}
    for name, src in (health.get("sources") or {}).items():
        if not isinstance(src, dict):
            continue
        sources[name] = {
            "source": src.get("source"),
            "status": src.get("status"),
            "fetched_at": src.get("fetched_at"),
        }
    return {
        "available": True,
        "overall": health.get("overall"),
        "generated_at": health.get("generated_at"),
        "sources": sources,
    }


def _summarise_key_levels(levels: dict | None) -> dict:
    if not isinstance(levels, dict):
        return {"available": False}
    data = levels.get("data") if isinstance(levels.get("data"), dict) else {}
    fields = [
        "pivot_classic", "r1", "r2", "s1", "s2",
        "recent_high", "recent_low",
        "sma_20", "sma_50", "sma_200",
        "vwap_session",
    ]
    out = {k: data.get(k) for k in fields}
    return {
        "available": True,
        "status": levels.get("status"),
        "source": levels.get("source"),
        "fetched_at": levels.get("fetched_at"),
        "degraded": bool(data.get("degraded")),
        "values": out,
        "notes": list(data.get("notes") or []),
    }


def _summarise_sentiment(sentiment: dict | None) -> dict:
    if not isinstance(sentiment, dict):
        return {"available": False}
    data = sentiment.get("data") if isinstance(sentiment.get("data"), dict) else {}
    return {
        "available": True,
        "status": sentiment.get("status"),
        "source": sentiment.get("source"),
        "fetched_at": sentiment.get("fetched_at"),
        "fear_greed_value": data.get("fear_greed_value"),
        "fear_greed_label": data.get("fear_greed_label"),
        "indicator": data.get("indicator"),
    }


def _summarise_derivatives(derivs: dict | None) -> dict:
    if not isinstance(derivs, dict):
        return {"available": False}
    data = derivs.get("data") if isinstance(derivs.get("data"), dict) else {}
    return {
        "available": True,
        "status": derivs.get("status"),
        "source": derivs.get("source"),
        "fetched_at": derivs.get("fetched_at"),
        "funding_rate": data.get("funding_rate"),
        "open_interest_btc": data.get("open_interest_btc"),
        "mark_price": data.get("mark_price"),
        "long_short_ratio": data.get("long_short_ratio"),
        "missing": list(derivs.get("notes") or []),
    }


def _summarise_accuracy(accuracy: dict | None) -> dict:
    """Strict pass-through of the ledger accuracy artifact.

    Never invents a hit-rate / brier when the ledger says
    display_ready=false.
    """
    if not isinstance(accuracy, dict):
        return {
            "available": False,
            "display_ready": False,
            "n": 0,
            "note": "accuracy artifact missing",
        }
    glob = accuracy.get("global") if isinstance(accuracy.get("global"), dict) else {}
    display_ready = bool(glob.get("display_ready"))
    n = int(glob.get("n") or 0)
    min_n = accuracy.get("min_n_display")
    out: dict = {
        "available": True,
        "display_ready": display_ready,
        "n": n,
        "min_n_display": min_n,
        "total_forecasts": accuracy.get("total_forecasts"),
        "total_resolved": accuracy.get("total_resolved"),
        "metrics_version": accuracy.get("metrics_version"),
        "generated_at": accuracy.get("generated_at"),
    }
    if display_ready:
        for f in ("hit_rate", "brier", "logloss", "ece",
                  "baseline_hit_rate", "baseline_brier", "base_rate"):
            v = glob.get(f)
            if v is not None:
                out[f] = v
    else:
        out["note"] = (
            "Insufficient resolved forecasts for display "
            f"(n={n}, min_n_display={min_n}). "
            "No hit-rate or calibration metric is reported."
        )
    return out


# ── top-level briefing build ────────────────────────────────────────────
def build_briefing(public_dir: Path, ledger_dir: Path,
                   date: str | None = None) -> dict:
    """Build a briefing dict from the public artifacts.

    `public_dir` is btc-brain/data/public.
    `ledger_dir` is btc-brain/ledger/public.
    """
    date = date or _today_utc_date()
    health = _read_json(public_dir / "source_health.json")
    levels = _read_json(public_dir / "key_levels.json")
    sentiment = _read_json(public_dir / "sentiment.json")
    derivs = _read_json(public_dir / "derivatives.json")
    accuracy = _read_json(ledger_dir / "accuracy.json")

    briefing = {
        "schema_version": SCHEMA_VERSION,
        "id": f"briefing-{date}",
        "date": date,
        "title": f"BTC Brain daily briefing — {date}",
        "generated_at": _utc_now_iso(),
        "not_financial_advice": True,
        "disclaimer": DISCLAIMER,
        "summary": {
            "source_health": _summarise_source_health(health),
            "key_levels": _summarise_key_levels(levels),
            "sentiment": _summarise_sentiment(sentiment),
            "derivatives": _summarise_derivatives(derivs),
            "accuracy": _summarise_accuracy(accuracy),
        },
        "inputs": {
            "source_health_path": "data/public/source_health.json",
            "key_levels_path": "data/public/key_levels.json",
            "sentiment_path": "data/public/sentiment.json",
            "derivatives_path": "data/public/derivatives.json",
            "accuracy_path": "ledger/public/accuracy.json",
        },
    }
    return briefing


# ── indexer ─────────────────────────────────────────────────────────────
def list_briefing_files(briefings_dir: Path) -> list[Path]:
    if not briefings_dir.exists():
        return []
    out = []
    for child in sorted(briefings_dir.iterdir()):
        if child.is_file() and DATE_RE.match(child.name):
            out.append(child)
    return out


def build_index(briefings_dir: Path) -> dict:
    """Scan <date>.json files and emit a fresh index artifact.

    If there are no briefing files we keep the previous empty-stub
    behaviour (briefings: [] + a notes string), so the public bundle
    never silently changes contract.
    """
    files = list_briefing_files(briefings_dir)
    entries: list[dict] = []
    for path in files:
        m = DATE_RE.match(path.name)
        if not m:
            continue
        date = m.group(1)
        doc = _read_json(path) or {}
        entry = {
            "id": doc.get("id") or f"briefing-{date}",
            "date": date,
            "title": doc.get("title") or f"BTC Brain daily briefing — {date}",
            "url": f"data/public/briefings/{date}.json",
            "generated_at": doc.get("generated_at"),
            "schema_version": doc.get("schema_version") or SCHEMA_VERSION,
        }
        entries.append(entry)
    entries.sort(key=lambda e: e["date"], reverse=True)
    if entries:
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "generated_at": _utc_now_iso(),
            "briefings": entries,
            "notes": (
                "Static archive of daily briefings. Each entry links to a "
                "JSON file under data/public/briefings/. Educational only."
            ),
        }
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "briefings": [],
        "notes": (
            "Stub artifact. No daily briefings have been published yet. "
            "Frontend will render 'empty' until briefings are generated "
            "and indexed here."
        ),
    }


# ── public entrypoints ──────────────────────────────────────────────────
def generate_today(public_dir: Path, ledger_dir: Path,
                   date: str | None = None) -> Path:
    """Generate today's (or `date`'s) briefing and update the index.

    Returns the briefing file path.
    """
    briefing = build_briefing(public_dir, ledger_dir, date=date)
    briefings_dir = public_dir / "briefings"
    out_path = briefings_dir / f"{briefing['date']}.json"
    _write_json(out_path, briefing)
    _write_json(briefings_dir / "index.json", build_index(briefings_dir))
    return out_path


def reindex_only(public_dir: Path) -> Path:
    """Recompute index.json from existing <date>.json files."""
    briefings_dir = public_dir / "briefings"
    out = briefings_dir / "index.json"
    _write_json(out, build_index(briefings_dir))
    return out


# ── CLI ─────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--public",
        default="btc-brain/data/public",
        help="public artifact dir (default: btc-brain/data/public)",
    )
    ap.add_argument(
        "--ledger-public",
        default="btc-brain/ledger/public",
        help="ledger public dir (default: btc-brain/ledger/public)",
    )
    ap.add_argument(
        "--mode",
        choices=("generate", "reindex"),
        default="generate",
        help="generate=write today's briefing + reindex; reindex=index only",
    )
    ap.add_argument(
        "--date",
        default=None,
        help="UTC date YYYY-MM-DD for the briefing (default: today UTC)",
    )
    args = ap.parse_args(argv)
    public = Path(args.public)
    ledger = Path(args.ledger_public)
    if args.mode == "reindex":
        path = reindex_only(public)
        print(json.dumps({"ok": True, "mode": "reindex", "path": str(path)},
                         indent=2))
        return 0
    path = generate_today(public, ledger, date=args.date)
    print(json.dumps({"ok": True, "mode": "generate", "path": str(path)},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
