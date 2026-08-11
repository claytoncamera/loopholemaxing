# Phase 6 promotion decision — 2026-08-10

**Candidate:** `v0.2.0-shadow-policy24` (dual-shadow since 2026-07-21, 21 shadow days)
**Decision:** **KILL** — stop candidate issuance. Successor `v0.3.0-shadow-guard24` is in build (parallel agent).
**Machine record:** `models/public/phase4/live_promotion_decision.json`
**Criteria:** `research/upgrade_master_plan_2026-07-21.md` → Phase 6 (DEFAULT_GATES + thesis gates + kill rule).

## The numbers (recomputed live from the ledger, 2026-08-10)

| Slice | n | hit | maker exp (bps) | Wilson LB 95 | brier |
|---|---|---|---|---|---|
| candidate × 24h (all-time) | 21 | 0.476 | **−29.90** | 0.283 | 0.2490 |
| candidate × 12h (all-time) | 41 | 0.415 | −17.62 | 0.278 | — |
| candidate pooled 12h+24h | 62 | 0.435 | −21.78 | 0.319 | 0.2509 |
| baseline × 24h (all-time) | 105 | 0.600 | +38.30 | 0.504 | 0.2495 |
| pooled 24h (both models) | 126 | 0.579 | +26.93 | 0.492 | — |
| pooled 24h rolling-30d (issued_at) | 50 | 0.480 | −21.46 | — | — |

Figure note: the 08-10 audit brief called n=62 / 0.435 / −21.8 bps the candidate's "24h record" — that is
actually its **pooled 12h+24h** record (41+21). The true 24h-only bucket (n=21, −29.9 bps) is worse per
trade. Either way the verdict is identical.

## Gate scorecard (candidate × 24h)

- min_resolved ≥ 30 — **FAIL** (21)
- Wilson LB > 0.52 at n ≥ 100 — **FAIL** (0.283 at n=21)
- maker expectancy > 20 bps — **FAIL** (−29.9)
- brier ≤ 0.245 — **FAIL** (0.2490)
- beat baseline — **FAIL** (baseline 24h: 0.600 hit, +38.3 bps)
- ECE ≤ 0.08 — not computable at n=21 (needs n ≥ 50)

Kill rule ("24h maker < 0 over 60d rolling with n ≥ 40"): strictly untriggerable at n=21, but the
model-level record (n=62, maker −21.8 < 0) already clears the n bar with negative expectancy, every
promotion gate fails, and nothing is trending toward passing. Waiting ~19 more resolutions to satisfy
the letter of the rule would just extend a failing public record.

## What this changes

1. **Candidate issuance stops** (kill). Ledger history is append-only and stays.
2. The signal gate bug that let this model publish `actionable_paper` off the pooled 24h bucket is fixed
   in `signal-v0.2.0`: gates now evaluate the emitting model's own (model × horizon) record. Live
   `signal.json` is now honestly **shadow** with the failing conditions enumerated.
3. Promotion remains manual-approval-only; `promoted_at` stays null.

*Paper/shadow only. No live capital. Not financial advice.*
