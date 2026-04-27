"""
Phase 4 end-to-end runner.

What it does (in order):

  1. Loads (or generates) closed candles from the Phase 3 synthetic fixture.
  2. Runs the lightweight regime detector over the close series.
  3. Loads the Phase 3 validation report (or fails over to running the
     in-memory pipeline minimally).
  4. Builds a Phase 4 regime-aware report — sibling of the Phase 3 report.
  5. Builds an example retrain candidate report driven by a synthetic
     drifting error stream so reviewers can inspect the schema.
  6. Writes everything to ``--out`` (default
     ``btc-brain/models/public/phase4/``).

The script never:

  * touches the live ledger (``btc-brain/ledger/data/``),
  * mutates Phase 3 artifacts,
  * sets ``promoted_at`` on any registry entry.

Every artifact written is marked ``fixture_only=true`` when generated
from synthetic data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS_ROOT = HERE.parent
REPO_ROOT = MODELS_ROOT.parent.parent
sys.path.insert(0, str(MODELS_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from phase4.regime import detect_regimes, summarize_distribution  # noqa: E402
from phase4.drift import PageHinkley, EWMADriftDetector, KSWindow  # noqa: E402
from phase4.retrain import build_retrain_candidate, write_candidate  # noqa: E402
from phase4.report import build_phase4_report, write_phase4_report  # noqa: E402
from fixtures.synthetic import make_synthetic_candles  # noqa: E402


def _drifting_error_stream(n: int = 400, seed: int = 17) -> list[float]:
    """Synthesize an error stream that's stable for the first half then
    shifts upward. Used to produce a non-trivial example retrain report.
    """
    import random
    rng = random.Random(seed)
    out = []
    for i in range(n):
        mu = 0.25 if i < n // 2 else 0.45
        out.append(max(0.0, rng.gauss(mu, 0.1)))
    return out


def _drifting_feature_stream(n: int = 400, seed: int = 23) -> list[float]:
    """Two-mode feature: pre-shift ~ N(0, 1), post-shift ~ N(1.5, 1)."""
    import random
    rng = random.Random(seed)
    out = []
    for i in range(n):
        mu = 0.0 if i < n // 2 else 1.5
        out.append(rng.gauss(mu, 1.0))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(MODELS_ROOT / "public" / "phase4"))
    ap.add_argument("--phase3-report",
                    default=str(MODELS_ROOT / "public" / "validation_report.json"))
    ap.add_argument("--n-synth", type=int, default=1200)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Closed candles + regime assignment.
    candles = make_synthetic_candles(n=args.n_synth)
    closes = [float(c["close"]) for c in candles]
    assignment = detect_regimes(closes)
    distribution = summarize_distribution(assignment)
    (out_dir / "regime_distribution.json").write_text(
        json.dumps({
            "fixture_only": True,
            "version": assignment.version,
            "config": assignment.config,
            "distribution": distribution,
            "warmup_bars": assignment.warmup_n,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # 2) Phase 3 → Phase 4 report.
    p3_path = Path(args.phase3_report)
    if p3_path.exists():
        p3_report = json.loads(p3_path.read_text(encoding="utf-8"))
    else:
        p3_report = {"horizons": {}}
    p4_report = build_phase4_report(
        phase3_validation_report=p3_report,
        closes=closes,
        fixture_only=True,
    )
    write_phase4_report(out_dir / "phase4_report.json", p4_report)

    # 3) Example retrain candidate (drifted error + feature streams).
    err_stream = _drifting_error_stream()
    feat_stream = _drifting_feature_stream()
    candidate = build_retrain_candidate(
        candidate_id="phase4-fixture-candidate",
        model_id="shadow-logistic-1h-v0.1.0",
        horizon="1h",
        closes=closes,
        error_stream=err_stream,
        feature_stream=feat_stream,
        probs=[0.5] * len(err_stream),
        y=[(1 if e < 0.4 else 0) for e in err_stream],
        fixture_only=True,
        notes=[
            "FIXTURE ONLY — synthetic drifting streams used to demonstrate "
            "the retrain candidate report schema."
        ],
    )
    write_candidate(out_dir / "retrain_candidate.json", candidate)

    summary = {
        "ok": True,
        "fixture_only": True,
        "out_dir": str(out_dir),
        "artifacts": [
            "regime_distribution.json",
            "phase4_report.json",
            "retrain_candidate.json",
        ],
        "promotion_recommendation": "NOT READY — fixture-only Phase 4 framework",
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
