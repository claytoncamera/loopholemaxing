"""
Phase 4 — Promotion gates.

A model is allowed to leave shadow mode only when *all* gates pass. This
module is the single source of truth for those gates. It evaluates a
candidate against:

  * ledger-backed sample size,
  * shadow-resolved coverage in days (≥ 14 by default),
  * Brier / log-loss / ECE thresholds,
  * "must beat baseline" on Brier,
  * "no severe drift" — no Page-Hinkley / EWMA / KSWIN alarm in the most
    recent ``no_drift_lookback`` resolutions,
  * manual approval (``approved_by`` + ``approved_at``).

Crucially this module never mutates the registry or auto-promotes.
``evaluate_promotion`` returns a ``PromotionDecision`` describing whether
each gate passed and the overall verdict. The caller decides what to do
with that verdict.

The gates are intentionally strict in Phase 4. Loosening any threshold
must be a documented, reviewed change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


PROMOTION_GATES_VERSION = "phase4-promotion-gates-v0.1.0"


# Default thresholds — overridable per-call but stable for the audit trail.
DEFAULT_GATES = {
    "min_resolved_total":            30,    # ledger-backed forecasts resolved
    "min_resolved_per_horizon":      30,    # per horizon (1h, 4h, ...)
    "min_shadow_days":               14,    # ≥ 2 weeks live shadow outcomes
    "max_brier":                     0.245, # must beat unbiased coin (0.25) by margin
    "max_log_loss":                  0.68,
    "max_ece":                       0.08,
    "must_beat_baseline_brier":      True,  # candidate brier < min(baseline_briers)
    "min_baseline_brier_margin":     0.005, # absolute brier delta required
    "no_severe_drift":               True,  # no PH / EWMA / KS alarm in lookback
    "no_drift_lookback":             100,   # most-recent N resolutions
    "require_manual_approval":       True,
    "must_have_out_of_sample":       True,  # walk-forward fold count > 0
    "min_oof_folds":                 3,
    "regime_coverage_min":           2,     # candidate has metrics in ≥2 coarse regimes
}


@dataclass
class GateOutcome:
    name: str
    passed: bool
    detail: str
    severity: str = "blocking"  # blocking | informational


@dataclass
class PromotionDecision:
    """Aggregate decision across all promotion gates."""

    candidate_id: str
    horizon: str
    gates: list[GateOutcome] = field(default_factory=list)
    ready_for_promotion: bool = False
    summary: str = ""
    config: dict = field(default_factory=dict)
    version: str = PROMOTION_GATES_VERSION

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "horizon": self.horizon,
            "ready_for_promotion": self.ready_for_promotion,
            "summary": self.summary,
            "version": self.version,
            "config": self.config,
            "gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "detail": g.detail,
                    "severity": g.severity,
                }
                for g in self.gates
            ],
        }


def evaluate_promotion(
    *,
    candidate_id: str,
    horizon: str,
    resolved_total: int,
    resolved_per_horizon: dict[str, int],
    shadow_days: float,
    metrics: dict,                       # {"brier", "log_loss", "ece", ...}
    baseline_briers: dict[str, float],   # name → brier
    drift_alarm_count: int,              # count in the lookback window
    walkforward_folds: int,
    regime_metrics: Optional[dict] = None,  # {coarse_label: {...}}
    approved_by: Optional[str] = None,
    approved_at: Optional[str] = None,
    gates_override: Optional[dict] = None,
) -> PromotionDecision:
    """Evaluate every gate and return a ``PromotionDecision``.

    Parameters
    ----------
    candidate_id, horizon:
        Identifiers used for the audit trail.
    resolved_total:
        Total resolved shadow forecasts in the live ledger that this
        candidate produced.
    resolved_per_horizon:
        Per-horizon counts; used to enforce per-horizon coverage.
    shadow_days:
        Number of distinct calendar days during which this candidate was
        emitting shadow forecasts that were later resolved.
    metrics:
        Aggregate (out-of-sample, ledger-backed) metrics for this
        candidate. Keys: ``brier``, ``log_loss``, ``ece``.
    baseline_briers:
        Mapping of baseline name to baseline brier on the same evaluation
        window. Used by the "must beat baseline" gate.
    drift_alarm_count:
        Count of severe-drift alarms in the most recent ``no_drift_lookback``
        observations across all configured drift detectors.
    walkforward_folds:
        Number of walk-forward folds the candidate was evaluated on; used
        by the "out-of-sample" gate.
    regime_metrics:
        Optional dict of per-coarse-regime metrics. Used by the
        ``regime_coverage_min`` gate.
    approved_by, approved_at:
        Manual-approval audit fields. Both must be set for the manual
        gate to pass.
    gates_override:
        Optional dict overriding ``DEFAULT_GATES`` for this evaluation.
    """
    gates = dict(DEFAULT_GATES)
    if gates_override:
        gates.update(gates_override)

    decision = PromotionDecision(
        candidate_id=candidate_id, horizon=horizon, config=gates,
    )

    # Gate 1: total resolved sample.
    decision.gates.append(GateOutcome(
        name="resolved_total",
        passed=resolved_total >= gates["min_resolved_total"],
        detail=f"resolved={resolved_total} need>={gates['min_resolved_total']}",
    ))

    # Gate 2: per-horizon resolved sample.
    per_h = resolved_per_horizon.get(horizon, 0)
    decision.gates.append(GateOutcome(
        name="resolved_per_horizon",
        passed=per_h >= gates["min_resolved_per_horizon"],
        detail=f"horizon={horizon} resolved={per_h} need>={gates['min_resolved_per_horizon']}",
    ))

    # Gate 3: shadow days.
    decision.gates.append(GateOutcome(
        name="shadow_days",
        passed=float(shadow_days) >= float(gates["min_shadow_days"]),
        detail=f"shadow_days={shadow_days} need>={gates['min_shadow_days']}",
    ))

    # Gate 4: Brier threshold.
    brier = float(metrics.get("brier", 1.0))
    decision.gates.append(GateOutcome(
        name="brier",
        passed=brier <= gates["max_brier"],
        detail=f"brier={brier:.4f} need<={gates['max_brier']}",
    ))

    # Gate 5: log-loss threshold.
    ll = float(metrics.get("log_loss", 1.0))
    decision.gates.append(GateOutcome(
        name="log_loss",
        passed=ll <= gates["max_log_loss"],
        detail=f"log_loss={ll:.4f} need<={gates['max_log_loss']}",
    ))

    # Gate 6: ECE threshold (None means insufficient sample → fail).
    ece = metrics.get("ece")
    decision.gates.append(GateOutcome(
        name="ece",
        passed=(ece is not None and float(ece) <= gates["max_ece"]),
        detail=(
            f"ece={ece} need<={gates['max_ece']}"
            if ece is not None
            else "ece=None (insufficient samples)"
        ),
    ))

    # Gate 7: must beat *every* baseline (informational margin).
    if gates["must_beat_baseline_brier"]:
        if not baseline_briers:
            decision.gates.append(GateOutcome(
                name="beats_baseline_brier",
                passed=False,
                detail="no baseline_briers supplied",
            ))
        else:
            best_baseline = min(baseline_briers.values())
            margin = best_baseline - brier  # positive => candidate beats baseline
            need = gates["min_baseline_brier_margin"]
            decision.gates.append(GateOutcome(
                name="beats_baseline_brier",
                passed=margin >= need,
                detail=(
                    f"candidate_brier={brier:.4f} best_baseline={best_baseline:.4f} "
                    f"margin={margin:.4f} need>={need}"
                ),
            ))

    # Gate 8: drift quiet.
    if gates["no_severe_drift"]:
        decision.gates.append(GateOutcome(
            name="no_severe_drift",
            passed=int(drift_alarm_count) == 0,
            detail=(
                f"alarms_in_last_{gates['no_drift_lookback']}={drift_alarm_count} need=0"
            ),
        ))

    # Gate 9: out-of-sample evidence.
    if gates["must_have_out_of_sample"]:
        decision.gates.append(GateOutcome(
            name="out_of_sample",
            passed=int(walkforward_folds) >= int(gates["min_oof_folds"]),
            detail=f"walkforward_folds={walkforward_folds} need>={gates['min_oof_folds']}",
        ))

    # Gate 10: regime coverage — candidate must have metrics in ≥N coarse regimes.
    if regime_metrics is not None:
        # Count coarse buckets (excluding "unknown") with at least one sample.
        covered = 0
        for k, v in (regime_metrics or {}).items():
            if k == "unknown":
                continue
            n = (v or {}).get("n", 0)
            if n and n > 0:
                covered += 1
        decision.gates.append(GateOutcome(
            name="regime_coverage",
            passed=covered >= int(gates["regime_coverage_min"]),
            detail=(
                f"coarse_regimes_with_samples={covered} "
                f"need>={gates['regime_coverage_min']}"
            ),
        ))

    # Gate 11: manual approval.
    if gates["require_manual_approval"]:
        approved = bool(approved_by) and bool(approved_at)
        decision.gates.append(GateOutcome(
            name="manual_approval",
            passed=approved,
            detail=(
                f"approved_by={approved_by} approved_at={approved_at}"
                if approved
                else "not_yet_approved"
            ),
        ))

    decision.ready_for_promotion = all(g.passed for g in decision.gates)
    failed = [g.name for g in decision.gates if not g.passed]
    if decision.ready_for_promotion:
        decision.summary = "all gates passed"
    else:
        decision.summary = f"NOT READY — failing gates: {failed}"

    return decision
