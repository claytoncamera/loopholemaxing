"""
Model registry.

Schema (JSON):

{
  "schema_version": "phase3-registry-v1",
  "generated_at": "2026-04-27T13:00:00Z",
  "shadow_only": true,
  "promotion_gate": {
     "min_shadow_resolved_per_horizon": 30,
     "min_shadow_days": 14,
     "max_ece": 0.08,
     "must_beat_baseline_brier": true
  },
  "models": [
     {
       "model_id": "shadow-logistic-1h-v0.1.0",
       "kind": "logistic",                       # logistic|baseline|tree
       "horizon": "1h",
       "features_version": "phase3-features-v0.1.0",
       "trained_at": "...",
       "n_train": 800, "n_test_total": 200,
       "walkforward": {
          "n_folds": 5,
          "purge_bars": 1,
          "embargo_bars": 1,
          "fold_metrics": [...],
          "aggregate_metrics": {...},
          "baseline_aggregate_metrics": {...}
       },
       "calibration": {
          "method": "platt",
          "fit_n": 200,
          "params": { "a": 1.02, "b": -0.05 },
          "post_calibration_metrics": {...}
       },
       "shadow_status": "active",                # active|skipped|paused
       "skip_reason": null,
       "promoted_at": null,                       # NEVER set automatically
       "fixture_only": false,                     # true if trained on fixture
       "notes": []
     },
     ...
  ]
}

`promoted_at` is intentionally NEVER auto-populated. Promotion is a manual,
out-of-band step gated by ≥ 2 weeks of live shadow resolutions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA_VERSION = "phase3-registry-v1"

DEFAULT_PROMOTION_GATE = {
    "min_shadow_resolved_per_horizon": 30,
    "min_shadow_days": 14,
    "max_ece": 0.08,
    "must_beat_baseline_brier": True,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_registry() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "shadow_only": True,
        "promotion_gate": dict(DEFAULT_PROMOTION_GATE),
        "models": [],
    }


REQUIRED_MODEL_FIELDS = (
    "model_id",
    "kind",
    "horizon",
    "features_version",
    "trained_at",
    "shadow_status",
    "fixture_only",
)


def validate_model_entry(entry: dict) -> None:
    missing = [f for f in REQUIRED_MODEL_FIELDS if f not in entry]
    if missing:
        raise ValueError(f"model entry missing fields: {missing}")
    if not str(entry["model_id"]).startswith("shadow-"):
        raise ValueError(
            f"model_id must start with 'shadow-' in Phase 3 (got {entry['model_id']})"
        )
    if entry["shadow_status"] not in ("active", "skipped", "paused"):
        raise ValueError(f"bad shadow_status: {entry['shadow_status']}")
    if entry.get("promoted_at"):
        raise ValueError(
            "promoted_at must be null in Phase 3 — promotion is a manual step"
        )


def write_registry(path: Path, registry: dict) -> None:
    if not registry.get("shadow_only", False):
        raise ValueError("Phase 3 registry must always set shadow_only=true")
    for m in registry.get("models", []):
        validate_model_entry(m)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_registry(path: Path) -> dict:
    if not path.exists():
        return empty_registry()
    return json.loads(path.read_text(encoding="utf-8"))


def add_or_replace_model(registry: dict, entry: dict) -> dict:
    validate_model_entry(entry)
    existing = registry.setdefault("models", [])
    for i, m in enumerate(existing):
        if m["model_id"] == entry["model_id"]:
            existing[i] = entry
            return registry
    existing.append(entry)
    return registry
