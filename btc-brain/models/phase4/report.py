"""
Phase 4 — Validation report enrichment.

Reads a Phase 3 walk-forward validation report (produced by
``btc-brain/models/scripts/run_phase3.py``) and produces a Phase 4
*regime-aware* report that augments existing per-model entries with:

  * a regime distribution computed from the supplied close series, AND
  * the regime-sliced metrics already present in the Phase 3 report, AND
  * a placeholder ``promotion_gate_evaluation`` block that always
    reports NOT READY in fixture mode (no live ledger sample yet).

The Phase 3 report is *not modified*. We write a sibling artifact:
``phase4_report.json``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .regime import detect_regimes, summarize_distribution, REGIME_DETECTOR_VERSION
from .promotion_gates import evaluate_promotion, PROMOTION_GATES_VERSION


PHASE4_REPORT_VERSION = "phase4-regime-report-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_phase4_report(
    *,
    phase3_validation_report: dict,
    closes: list[float],
    horizons: Optional[list[str]] = None,
    fixture_only: bool = True,
) -> dict:
    """Build the Phase 4 enrichment report.

    ``phase3_validation_report`` is the dict already written to
    ``btc-brain/models/public/validation_report.json``. We do not modify
    it — we copy the relevant slices into our own report alongside
    regime distributions and a not-yet-promoted gate evaluation.
    """
    assignment = detect_regimes(closes)
    distribution = summarize_distribution(assignment)

    horizons = horizons or list(phase3_validation_report.get("horizons", {}).keys())
    out: dict = {
        "schema_version": PHASE4_REPORT_VERSION,
        "generated_at": _utc_now(),
        "fixture_only": bool(fixture_only),
        "regime_detector_version": REGIME_DETECTOR_VERSION,
        "promotion_gates_version": PROMOTION_GATES_VERSION,
        "regime_distribution": distribution,
        "horizons": {},
        "notes": [
            "Regime-sliced metrics are derived from the Phase 3 walk-forward "
            "OOF predictions (regime_sliced block) — *not* from live ledger "
            "outcomes. Live-ledger-backed metrics require Phase 1 ledger "
            "resolutions and are gated by promotion_gate_evaluation below.",
            "Phase 4 NEVER auto-promotes. promotion_gate_evaluation is "
            "advisory and is expected to report NOT READY in fixture mode.",
        ],
    }

    for h in horizons:
        h_block = (phase3_validation_report.get("horizons") or {}).get(h)
        if not h_block or h_block.get("skipped"):
            out["horizons"][h] = {
                "skipped": True,
                "reason": (h_block or {}).get("reason", "no phase 3 result"),
            }
            continue

        h_models = h_block.get("models", {})
        models_out = {}
        for name, mr in h_models.items():
            if mr.get("skipped"):
                models_out[name] = {
                    "skipped": True,
                    "skip_reason": mr.get("skip_reason"),
                }
                continue
            agg = mr.get("aggregate_metrics") or {}
            regime_sliced = agg.get("regime_sliced") or {}

            # Build a NOT-READY promotion gate evaluation against this model.
            #
            # We deliberately use *zero* ledger-resolved counts and zero
            # shadow days because Phase 4 (this PR) is the framework only —
            # there is no live shadow data yet. The decision MUST come back
            # NOT READY.
            decision = evaluate_promotion(
                candidate_id=f"shadow-{name}-{h}-fixture",
                horizon=h,
                resolved_total=0,
                resolved_per_horizon={h: 0},
                shadow_days=0.0,
                metrics={
                    "brier": agg.get("brier", 1.0),
                    "log_loss": agg.get("log_loss", 1.0),
                    "ece": agg.get("ece"),
                },
                baseline_briers={},  # no live baselines
                drift_alarm_count=0,
                walkforward_folds=h_block.get("n_folds", 0),
                regime_metrics=regime_sliced,
                approved_by=None,
                approved_at=None,
            )

            models_out[name] = {
                "regime_sliced_metrics": regime_sliced,
                "promotion_gate_evaluation": decision.to_dict(),
            }

        out["horizons"][h] = {
            "n_folds": h_block.get("n_folds"),
            "n_labeled": h_block.get("n_labeled"),
            "models": models_out,
        }

    return out


def write_phase4_report(path: Path, report: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
