"""
Phase 4 — Retrain candidate pipeline.

This module *does not* train, register, or promote anything. It produces
a JSON artifact (the "retrain candidate report") describing:

* which model / horizon triggered a retrain candidate,
* which detectors fired (Page-Hinkley / EWMA / KSWIN),
* the regime distribution observed in the lookback window,
* per-regime metric snapshots for the existing model,
* the next steps a human operator must take.

The artifact is consumed by Phase 4 governance (see ``README.md``). It is
explicitly marked as advisory — the registry's ``promoted_at`` field is
left untouched, and the live ledger is never modified by this pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .drift import (
    PageHinkley,
    EWMADriftDetector,
    KSWindow,
    DRIFT_VERSION,
)
from .regime import detect_regimes, summarize_distribution, REGIME_DETECTOR_VERSION


RETRAIN_REPORT_VERSION = "phase4-retrain-candidate-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RetrainCandidate:
    """Container for a single retrain candidate report."""

    candidate_id: str
    model_id: str
    horizon: str
    triggered_at: str = field(default_factory=_utc_now)
    triggers: list[dict] = field(default_factory=list)
    regime_distribution: dict = field(default_factory=dict)
    regime_metrics: dict = field(default_factory=dict)
    drift_summary: dict = field(default_factory=dict)
    sample_size: int = 0
    fixture_only: bool = False
    notes: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    schema_version: str = RETRAIN_REPORT_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "model_id": self.model_id,
            "horizon": self.horizon,
            "triggered_at": self.triggered_at,
            "triggers": list(self.triggers),
            "regime_distribution": dict(self.regime_distribution),
            "regime_metrics": dict(self.regime_metrics),
            "drift_summary": dict(self.drift_summary),
            "sample_size": int(self.sample_size),
            "fixture_only": bool(self.fixture_only),
            "notes": list(self.notes),
            "next_steps": list(self.next_steps),
            # Audit references for downstream consumers.
            "regime_detector_version": REGIME_DETECTOR_VERSION,
            "drift_detector_version": DRIFT_VERSION,
        }


def _per_regime_metrics(
    coarse_labels: list[str],
    probs: list[float],
    y: list[int],
) -> dict:
    """Compute (n, hit_rate, brier, base_rate) per coarse regime label."""
    out: dict[str, dict] = {}
    for r, p, o in zip(coarse_labels, probs, y):
        b = out.setdefault(r or "unknown", {"n": 0, "hits": 0, "sse": 0.0, "pos": 0})
        b["n"] += 1
        b["hits"] += 1 if (1 if p >= 0.5 else 0) == o else 0
        b["sse"] += (p - o) ** 2
        b["pos"] += o
    final: dict[str, dict] = {}
    for r, b in out.items():
        n = max(1, b["n"])
        final[r] = {
            "n": b["n"],
            "hit_rate": b["hits"] / n,
            "brier": b["sse"] / n,
            "base_rate": b["pos"] / n,
        }
    return final


def build_retrain_candidate(
    *,
    candidate_id: str,
    model_id: str,
    horizon: str,
    closes: list[float],
    error_stream: list[float],
    feature_stream: Optional[list[float]] = None,
    probs: Optional[list[float]] = None,
    y: Optional[list[int]] = None,
    fixture_only: bool = True,
    page_hinkley: Optional[PageHinkley] = None,
    ewma: Optional[EWMADriftDetector] = None,
    kswin: Optional[KSWindow] = None,
    notes: Optional[list[str]] = None,
) -> RetrainCandidate:
    """Run the drift detectors over the supplied streams and emit a
    retrain candidate report. Does NOT train a new model and does NOT
    promote anything.
    """
    ph = page_hinkley or PageHinkley()
    ew = ewma or EWMADriftDetector()
    ks = kswin or KSWindow()

    triggers: list[dict] = []
    ph_alarms: list[int] = []
    ew_alarms: list[int] = []
    ks_alarms: list[int] = []

    for i, x in enumerate(error_stream):
        if ph.update(float(x)):
            ph_alarms.append(i)
        if ew.update(float(x)):
            ew_alarms.append(i)

    if feature_stream is not None:
        for i, x in enumerate(feature_stream):
            if ks.update(float(x)):
                ks_alarms.append(i)

    if ph_alarms:
        triggers.append({
            "detector": "page_hinkley",
            "alarms_at": ph_alarms,
            "snapshot": ph.snapshot(),
        })
    if ew_alarms:
        triggers.append({
            "detector": "ewma",
            "alarms_at": ew_alarms,
            "snapshot": ew.snapshot(),
        })
    if ks_alarms:
        triggers.append({
            "detector": "kswin",
            "alarms_at": ks_alarms,
            "snapshot": ks.snapshot(),
        })

    regime_assignment = detect_regimes(closes)
    distribution = summarize_distribution(regime_assignment)

    regime_metrics: dict = {}
    if probs is not None and y is not None and len(probs) == len(y):
        # Align coarse-regime labels to the (probs, y) stream by length.
        # Caller is responsible for passing aligned arrays — typically
        # the labels for the bars where (probs, y) were recorded.
        if len(regime_assignment.coarse) >= len(probs):
            tail_labels = regime_assignment.coarse[-len(probs):]
        else:
            tail_labels = (
                ["unknown"] * (len(probs) - len(regime_assignment.coarse))
                + regime_assignment.coarse
            )
        regime_metrics = _per_regime_metrics(tail_labels, probs, y)

    candidate = RetrainCandidate(
        candidate_id=candidate_id,
        model_id=model_id,
        horizon=horizon,
        triggers=triggers,
        regime_distribution=distribution,
        regime_metrics=regime_metrics,
        drift_summary={
            "page_hinkley": ph.snapshot(),
            "ewma": ew.snapshot(),
            "kswin": ks.snapshot(),
        },
        sample_size=len(error_stream),
        fixture_only=fixture_only,
        notes=list(notes or []),
    )

    candidate.next_steps = [
        "Investigate alarms — confirm a real distribution shift, not a feed glitch.",
        "Re-run Phase 3 walk-forward training with current data window.",
        "Inspect regime-sliced metrics for the live model — is the regression "
        "concentrated in one regime?",
        "If a candidate model beats the existing shadow on Brier across "
        "≥2 weeks of resolved shadow forecasts, run the promotion gate "
        "evaluator. Promotion remains manual.",
        "Do NOT modify live model weights or registry promotion fields based "
        "on this report. This artifact is advisory only.",
    ]

    return candidate


def write_candidate(path: Path, candidate: RetrainCandidate) -> Path:
    """Write the candidate report as pretty JSON. Returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
