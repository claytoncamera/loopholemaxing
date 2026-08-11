# [BTC Brain] Phase 3 Live Training Report — Candidate v0.4 Evaluation

**Date:** 2026-08-11
**Verdict:** **NO CANDIDATE** — nothing was wired into the issuer.
**Pipeline:** `models/scripts/run_phase3_live.py` (walk-forward, purge=H, embargo=24, pure-stdlib)
**Data:** `data/history/candles_1h.jsonl` — 17,753 closed 1h bars, 2024-08-01 → 2026-08-11 (Coinbase backfill + hourly snapshot archive; integrity-scanned: zero duplicates, zero OHLC violations, zero splice artifacts at all 4 source transitions; two 6h exchange-downtime gaps documented)
**Verification:** three independent adversarial audits (leakage/alignment · reproduction/determinism · power/data). Every published number reproduced **bit-exact** by from-scratch reimplementations. Full transcripts in the session workflow journal; scratch scripts referenced below.

---

## The pre-specified selection rule (written into code before results existed)

> The ML candidate is `logistic` on the 24h horizon. It is selected **iff**
> (a) its pooled out-of-sample hit rate strictly beats the pooled OOS majority rate, **and**
> (b) its pooled OOS Brier ≤ the best baseline Brier on 24h.
> Hyperparameters are fixed constants (lr=0.3, iters=250, L2=0.01). No search, no post-hoc thresholds.

This is the master plan's Phase 3 step-6 rule. The machine-readable outcome is
`models/public/phase3_live/selection_decision.json`.

## Results (pooled OOS, 5 effective folds, n=11,320 overlapping 24h rows, Apr-2025 → Aug-2026)

| Model | 24h hit | vs majority | Brier | Maker expectancy |
|---|---|---|---|---|
| **majority** (constant) | 51.5% | — | **0.2500** | −4.6 bps |
| siie_lite | 50.7% | −0.8 pp | 0.2568 | −2.1 bps |
| mean_reversion | 50.7% | −0.8 pp | 0.2504 | −2.5 bps |
| **sma24_rule** (live baseline replica) | **50.0%** | −1.5 pp | 0.2526 | +1.1 bps |
| momentum / last_direction | 49.3% | −2.2 pp | 0.2511/0.2532 | −1.5 bps |
| **logistic (the candidate)** | **48.5%** | **−3.0 pp** | 0.2541 | −7.0 bps |

Both selection criteria fail. 12h is qualitatively identical (logistic 48.9%, −2.2 pp).
The −3.0 pp logistic deficit is **within noise** for a no-edge model (effective independent n ≈ 470; SE ≈ 2.3 pp) — this is *absence of detected edge*, not evidence of anti-learning.

## The two findings that matter more than the verdict

**1. The live baseline's early "edge" does not exist at scale.** The exact SMA24 direction rule that scored 60% over its first 105 live 24h forecasts scores **49.98% over two years of out-of-sample history** (11,320 predictions). The ledger's rolling-30d collapse (48%) was the true signal; the 60% was a regime artifact — short-side alpha in a falling tape, already documented in `promotion_decision_20260810.md`. Two independent measurement systems (live ledger, historical walk-forward) now agree.

**2. This test's power floor is a +3–4 pp edge — and the interesting edges are smaller.** The adversarial power test planted synthetic causal edges through the *same* pipeline:

| Planted drift (per 24h) | Oracle hit vs majority | Pipeline outcome |
|---|---|---|
| ±15 bps | +0.06 pp — **oracle itself cannot clear the hurdle** | correctly not selected |
| ±60 bps | +1.8 pp | hit criterion **passed**, rejected on Brier alone |
| ±150 bps | +4.9 pp | **SELECTED** |
| 0 bps (null control) | — | correctly not selected |

So: the plumbing demonstrably transmits real signal, the null control behaves, and the detection floor sits between ±60 and ±150 bps/24h. **Edges of the 1–2 pp class — the size of the ledger's measured SMA-band effects — are below this test's resolving power** on 15 months of overlapping OOS data. The honest statement is: *no edge ≥ ~3 pp exists; smaller edges are undetermined by this run.*

## Methodological defects found and dispositioned

- **Fixed in code (this commit):** the sma24_rule replica was fed z-scored features, silently thresholding at the train mean instead of 0 (297/11,320 predictions flipped; corrected replica = 49.98%, matching the auditor's independent computation to the digit). Wilson LB fields now carry an explicit overlap caveat + `effective_n_approx` (n/H) — the naive bound overstates precision ~√H×.
- **Recorded for rule v2 (below), not changed post-hoc:** selection criterion (b) compares the *raw uncalibrated* logistic Brier against a near-optimal constant predictor; the power test showed it rejects a genuinely predictive +1.8 pp edge on Brier alone. Changing the rule after seeing results would be data dredging — it stays as-run, and v2 is pre-specified now.
- **Known and negligible:** two 6h data gaps (48 affected labels of 11,320); requested 6 folds → 5 effective (fold 0 refused by min-train guard; Aug-2024→Apr-2025 bull leg is train-only, never tested OOS).

## Pre-specified rule v2 — for the NEXT training run, committed before it runs

1. Criterion (b) becomes: **Platt-calibrated** (chronological-holdout) Brier ≤ majority Brier.
2. Add criterion (c): block-bootstrap 95% CI (24-bar blocks) of hit−majority must exclude 0 — replaces the overstated i.i.d. Wilson bound.
3. Evaluation adds the **non-overlapping 00 UTC subseries** as a co-primary view (clean independence, smaller n).
4. Trigger to re-run: ≥3 additional months of history (power grows with span, not just row count), or a new feature family with a causal rationale (funding/OI history is accruing hourly since 2026-08-10; sentiment likewise).

## What this means for the product

- `signal.json` stays gated on **live ledger evidence only** (per-model rolling windows + Wilson LB, D33). Nothing here loosens that.
- **guard24** (v0.3.0-shadow-guard24) remains the only active candidate: it encodes the small-edge hypotheses as abstain rules and will accumulate the live evidence this offline test cannot resolve. The hourly 12h/24h buckets accrue ~24× faster since 2026-08-10.
- The Model Lab on the site now shows these real walk-forward entries (`fixture_only: false`) instead of April's synthetic fixtures.
- This report is public by design: a forecasting site that publishes its own failed candidate search, with the power analysis that bounds what the failure means, is doing the one thing the category never does.

*Related: `edge_autopsy_2026-07-21.md` · `upgrade_master_plan_2026-07-21.md` · `promotion_decision_20260810.md` · machine artifacts under `models/public/` (`validation_report.json`, `calibration_report.json`, `phase3_live/selection_decision.json`).*
