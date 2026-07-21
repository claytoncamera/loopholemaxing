# [Trading] Master Plan: BTC Brain Upgrade — Find & Lock Edge
**Date:** 2026-07-21  
**Status:** Draft  
**Phases:** 7  
**Monetization unlock:** Phase 5 (`signal.json` + paper OpenClaw path)  
**Depends on:** Edge autopsy `Trading_btc-brain-edge-autopsy_20260721.md`

## Goal
Upgrade BTC Brain from a single SMA-shadow ledger into a **horizon-aware, regime-aware, dual-model forecasting system** where the proven 12h/24h edge is measured, gated, and exported for paper trading — without polluting public claims or risking capital.

## Constraints & Assumptions
- Repo: public `claytoncamera/loopholemaxing` (Pages + GHA bots)
- Append-only ledger; never edit historical forecast rows
- Shadow models stay labeled `shadow-` / non-promoted until gates + manual two-key approval
- No live trading in this plan — paper only through Phase 6
- GHA runners geo-block Binance futures (HTTP 451) — design feeds around Coinbase/Kraken/OKX
- Current sole live model: `v0.1.0-baseline-shadow` (SMA24)
- Autopsy finding: **edge is 12h/24h; 1h is anti-edge vs majority; high SMA-divergence conf is inverted**

## Phase Overview
| Phase | Name | Goal | Unlock |
|-------|------|------|--------|
| 0 | Freeze truth | Commit autopsy + baseline metrics snapshot | Shared ground truth |
| 1 | Metrics v2 | accuracy.json grows fee/direction/regime slices | See edge continuously |
| 2 | Live regime + feed harden | regime_at_issue real; derivatives without Binance | Feature quality |
| 3 | Candidate model v0.2 | Feature+logistic (or SIIE-lite) trained walk-forward for 12h/24h | Real model |
| 4 | Dual shadow issuer | Baseline + candidate both issue; no public promote | A/B live evidence |
| 5 | Product signal path | `signal.json` + OpenClaw paper contract; 1h demoted | **Monetization unlock** |
| 6 | Promotion / kill | Evaluate gates; promote or kill candidate; optional filter pack | Production claim |

---

## Phase 0: Freeze Truth

### Objective
Lock the 2026-07-21 edge autopsy and baseline metrics as the pre-upgrade control.

### Dependencies
- Requires: live ledger on main  
- Produces: autopsy md + metrics snapshot JSON in repo or Brain

### Phase Prompt (copy-paste into new session)

> **Session context:** BTC Brain inside `claytoncamera/loopholemaxing` — Bitcoin forecast ledger + Phase 2–4 model framework.
>
> **You are executing Phase 0 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Edge autopsy already drafted at workspace `Trading_btc-brain-edge-autopsy_20260721.md` if present; regenerate from live ledger if missing.
> - Live model is only `v0.1.0-baseline-shadow`.
>
> **Your task:**
> 1. Pull latest `btc-brain/ledger/data/forecasts.jsonl`, `resolutions.jsonl`, `ledger/public/accuracy.json`.
> 2. Re-run the edge autopsy (hit/expectancy/fees by horizon, direction, conf, DOW, hour).
> 3. Write `btc-brain/research/edge_autopsy_2026-07-21.json` (machine) + ensure human md matches.
> 4. Commit to a branch `btc/phase0-edge-freeze` — do not change issuer logic.
>
> **Deliverable:**
> - `btc-brain/research/edge_autopsy_YYYYMMDD.json`
> - PR titled `[BTC] Phase 0 — freeze edge autopsy baseline`
>
> **Do not:**
> - Change schedule_forecasts.py signal logic
> - Promote any model
> - Touch OpenClaw / live trading

### Verification Checklist
- [ ] Autopsy n_resolved matches accuracy.json total_resolved (±1)
- [ ] 24h expectancy and hit rate reproduced within rounding
- [ ] PR opened, issuer unchanged

---

## Phase 1: Metrics v2 (see the edge every hour)

### Objective
Extend `metrics.py` / `accuracy.json` so edge slices are first-class public artifacts.

### Dependencies
- Requires: Phase 0 snapshot  
- Produces: `metrics-v0.2.0` accuracy schema

### Phase Prompt (copy-paste into new session)

> **Session context:** BTC Brain ledger metrics rebuild on GHA (`btc-ledger-resolve.yml`).
>
> **You are executing Phase 1 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Phase 0 autopsy established 24h/12h edge and 1h anti-edge vs majority.
> - Current `metrics-v0.1.0` only exposes by_horizon / by_model / rolling; ECE null; no fees.
>
> **Your task:**
> 1. Extend `btc-brain/ledger/scripts/metrics.py` to emit:
>    - `by_horizon.*.expectancy_bps` (signed return if taking forecast direction)
>    - `by_horizon.*.expectancy_maker_2bps` / `expectancy_taker_10bps`
>    - `by_horizon.*.hit_up` / `hit_down` / `n_up` / `n_down`
>    - `by_horizon.*.vs_majority_pp` (hit − max(always_up, always_down))
>    - `by_direction` global block
>    - `by_regime` when regime ≠ unknown (empty ok)
>    - ECE when n≥50 (otherwise null)
> 2. Add unit tests in `ledger/tests/` for fee math and direction split.
> 3. Keep schema_version bump documented in SCHEMA.md or metrics header.
> 4. Ensure GHA resolve job still commits accuracy.json.
>
> **Deliverable:**
> - PR `[BTC] Phase 1 — metrics v0.2 edge slices`
> - Sample accuracy.json artifact in PR description
>
> **Do not:**
> - Change forecast issuance
> - Remove existing fields (additive only)
> - Claim promotion readiness

### Verification Checklist
- [ ] accuracy.json includes expectancy_bps for 1h/4h/12h/24h
- [ ] 24h maker expectancy > 0 on current ledger
- [ ] Tests green in CI / local
- [ ] Old consumers still parse (additive fields)

---

## Phase 2: Live Regime + Feed Harden

### Objective
Stop writing `regime_at_issue=unknown`; fix derivatives path without Binance futures.

### Dependencies
- Requires: Phase 1 optional but preferred  
- Produces: regime labels on new forecasts; healthier derivatives.json

### Phase Prompt (copy-paste into new session)

> **Session context:** BTC Brain Phase 2 data feeds + Phase 4 regime detector.
>
> **You are executing Phase 2 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Every live forecast has `regime_at_issue: unknown`.
> - Binance futures returns HTTP 451 on GHA; Bybit 403; OKX partial_ok.
> - `btc-brain/models/phase4/regime.py` already implements causal bull/bear/chop.
>
> **Your task:**
> 1. Wire `regime.py` into `schedule_forecasts.py` (and/or snapshot path) so each new forecast gets coarse regime from closed candles only.
> 2. Harden `data/feeds/derivatives.py`: primary OKX (or Coinbase-compatible), Binance futures optional, never fail whole snapshot if Binance 451.
> 3. Extend daily candle history until sma_200 populates in key_levels (or document blocker).
> 4. Update source_health to show honest overall status.
> 5. Tests: regime causality unchanged; snapshot succeeds with Binance mocked 451.
>
> **Deliverable:**
> - PR `[BTC] Phase 2 — live regime + derivatives harden`
> - After merge, next issued forecasts show regime ≠ unknown
>
> **Do not:**
> - Change SMA direction logic yet (that is Phase 3–4)
> - Auto-promote models
> - Store API secrets in repo

### Verification Checklist
- [ ] New forecast rows include bull|bear|chop
- [ ] derivatives.json status ok or partial_ok without hard fail
- [ ] source_health overall not failed solely due to Binance 451
- [ ] sma_200 non-null OR explicit note why not

---

## Phase 3: Candidate Model v0.2 (12h/24h focus)

### Objective
Train a real shadow candidate that targets the horizons where edge can survive fees.

### Dependencies
- Requires: Phase 2 regime features available  
- Produces: `v0.2.0-shadow-h12h24` weights + walk-forward report (not live issue yet)

### Phase Prompt (copy-paste into new session)

> **Session context:** BTC Brain Phase 3 models (`features/`, `baselines/`, `calibration/`, walk-forward).
>
> **You are executing Phase 3 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Autopsy: 24h SMA shadow +56 bps expectancy, 63% hit; 12h +26 bps; 1h loses to always-up.
> - High SMA |rel| confidence is inverted — do not use distance-as-confidence.
> - Feature builder already has returns, EMA, RSI, optional funding/F&G/regime.
>
> **Your task:**
> 1. Run Phase 3 pipeline on **live** `candles_1h.json` history (not only synthetic fixture).
> 2. Train at minimum: logistic regression + SIIE-lite + momentum + mean-reversion baselines.
> 3. Optimize / evaluate primarily on **12h and 24h** targets; report 1h/4h but do not tune for them.
> 4. Walk-forward with purge ≥ horizon and embargo; fit calibrators OOF only.
> 5. Emit reports under `btc-brain/models/public/` with `shadow_only=true`, `fixture_only=false`, and clear comparison vs SMA baseline on OOS folds.
> 6. Selection rule for candidate: best OOS Brier on 24h among models that also beat majority baseline hit rate on 24h; secondary check 12h.
> 7. Document feature importances / coefficients in `btc-brain/research/candidate_v0.2_report.md`.
>
> **Deliverable:**
> - PR `[BTC] Phase 3 — candidate v0.2 walk-forward on live candles`
> - `candidate_v0.2_report.md` + registry JSON
>
> **Do not:**
> - Write to forecasts.jsonl yet
> - Claim live accuracy from walk-forward alone
> - Enable OpenClaw

### Verification Checklist
- [ ] fixture_only=false on live-data report
- [ ] 24h OOS metrics present with ≥3 folds
- [ ] Candidate beats SMA and majority on agreed metrics OR report says NO CANDIDATE
- [ ] No leakage tests still pass

---

## Phase 4: Dual Shadow Issuer

### Objective
Issue baseline + candidate side-by-side with distinct model_version tags.

### Dependencies
- Requires: Phase 3 candidate artifact (or explicit fallback: filtered SMA policy as candidate)  
- Produces: live A/B resolutions in ledger

### Phase Prompt (copy-paste into new session)

> **Session context:** `schedule_forecasts.py` + GHA `btc-ledger-issue.yml`.
>
> **You are executing Phase 4 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Phase 3 produced candidate weights/report OR concluded fallback policy.
> - Fallback candidate if ML weak: `v0.2.0-shadow-policy24` = issue **only 12h+24h**, skip 1h/4h, optional skip hour 20 UTC, clamp probs via empirical hit rates not SMA distance.
> - Baseline `v0.1.0-baseline-shadow` must keep running unchanged for control.
>
> **Your task:**
> 1. Refactor issuer to support multiple model adapters (baseline SMA + candidate).
> 2. Duplicate prevention key = (model_version, horizon, bucket) — both models can issue same bucket.
> 3. Candidate default horizons: **12h, 24h only** (configurable).
> 4. Wire candidate feature freeze URI into feature_snapshot_uri.
> 5. Update metrics to always break down by_model_version (already partially there).
> 6. Add dry-run mode coverage in tests.
> 7. Deploy via GHA; verify both versions appear in new forecast rows within 24h.
>
> **Deliverable:**
> - PR `[BTC] Phase 4 — dual shadow issuer (baseline + v0.2)`
> - Runbook note in `btc-brain/ledger/README.md`
>
> **Do not:**
> - Remove baseline issuer
> - Set promoted_at
> - Emit trading signals yet

### Verification Checklist
- [ ] New rows exist for both model_versions
- [ ] Candidate does not issue 1h (unless explicitly configured)
- [ ] Idempotent re-run creates zero duplicates
- [ ] accuracy.json shows both models after resolutions accrue

---

## Phase 5: Product Signal Path (monetization unlock)

### Objective
Publish a versioned `signal.json` for OpenClaw paper trading from the best fee-surviving horizon only.

### Dependencies
- Requires: Phase 4 dual issuer live ≥ few days preferred; can scaffold contract immediately  
- Produces: `btc-brain/ledger/public/signal.json` (+ schema)

### Phase Prompt (copy-paste into new session)

> **Session context:** BTC Brain → OpenClaw boundary. OpenClaw is designed unbuilt; consumes versioned signal.json only.
>
> **You are executing Phase 5 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - Edge thesis: primary 24h maker-only; secondary 12h; never 1h for execution.
> - Guardrails planned: kill switch, capital cap, maker-only, no leverage, withdrawal-disabled keys, ≥100 paper trades before live.
>
> **Your task:**
> 1. Define `signal.schema.json`: signal_id, issued_at, horizon, direction, probability, entry_ref, model_version, regime, invalidation, expires_at, economics={fee_assumption, expectancy_bps_7d}, status=shadow|actionable_paper|halted.
> 2. Builder script: read latest open/recent forecasts for candidate (fallback baseline 24h only); emit signal only if:
>    - horizon in {24h} (12h optional flag)
>    - rolling 30d maker expectancy > 0 and hit Wilson lower bound ≥ 0.52 when n≥40 else status=shadow
> 3. Publish to `btc-brain/ledger/public/signal.json` via metrics/issue job.
> 4. Add dashboard read-only panel or minimal HTML note on btc-brain page: paper signal only, not advice.
> 5. Write `btc-brain/research/openclaw_paper_contract.md` describing how a future agent polls signal.json.
>
> **Deliverable:**
> - PR `[BTC] Phase 5 — signal.json paper contract`
> - Example signal.json in PR
>
> **Do not:**
> - Place live orders
> - Build full OpenClaw agent (separate plan)
> - Mark signal actionable if gates fail

### Verification Checklist
- [ ] signal.json validates against schema
- [ ] 1h never appears as actionable_paper
- [ ] Halted/shadow states work when metrics weak
- [ ] Public page disclaimer present

---

## Phase 6: Promotion / Kill Decision

### Objective
Run live Phase 4 promotion gates on ledger-backed candidate; promote, iterate, or kill.

### Dependencies
- Requires: Phase 4 dual issuer with ≥14 shadow days and enough 24h resolutions (target n≥30 per gates; prefer n≥100 for 24h thesis)  
- Produces: PromotionDecision JSON + registry update OR kill note

### Phase Prompt (copy-paste into new session)

> **Session context:** `promotion_gates.py` + live accuracy by_model_version.
>
> **You are executing Phase 6 of the BTC Brain Upgrade master plan.**
>
> **Context from prior phases:**
> - DEFAULT_GATES: min_resolved 30, min_shadow_days 14, max_brier 0.245, beat baseline, ECE≤0.08, manual approval required.
> - Thesis gates (stricter for execution): 24h hit Wilson LB>0.52 at n≥100; maker expectancy>20 bps.
>
> **Your task:**
> 1. Evaluate candidate vs baseline on live ledger (not fixture).
> 2. Produce `btc-brain/models/public/phase4/live_promotion_decision.json`.
> 3. If NOT READY: list failing gates and a single next experiment (feature, filter, or horizon drop).
> 4. If READY on metrics: still require Clayton manual approval comment before any `promoted_at`.
> 5. Update public UI copy only if promoted — otherwise keep shadow labeling.
> 6. Write kill criteria: if 24h maker expectancy <0 over 60d rolling with n≥40 → stop candidate issuance.
>
> **Deliverable:**
> - PR `[BTC] Phase 6 — live promotion decision`
> - Decision JSON + short md recommendation
>
> **Do not:**
> - Auto-set promoted_at without explicit Clayton approval in-thread
> - Enable live capital trading

### Verification Checklist
- [ ] Decision references live n and dates
- [ ] Failing gates enumerated if not ready
- [ ] Kill criteria documented
- [ ] No silent promotion

---

## Recommended execution order (this session → next)

**This session (done / in progress):** autopsy + master plan.  
**Next session:** execute **Phase 1** (metrics v2) in parallel-safe with **Phase 2** (regime + feeds) — both are low-risk additive.  
**Then:** Phase 3 candidate → Phase 4 dual issue → wait for data → Phase 5 signal → Phase 6 decision.

If you want maximum speed to monetization:  
Phase 1 → Phase 4 **policy candidate** (12h/24h-only filtered SMA, no ML wait) → Phase 5 signal.json → Phase 3 ML in parallel.

---

## Reuse Notes
- Edge autopsy pattern: fee-adjusted expectancy + vs-majority delta should become standard for any Claytron forecast engine (UAE, MMS signals).
- Dual-issuer pattern mirrors OrbitRoute learning real-vs-synthetic discipline.
- Save phase prompts to inventory under Trading.

## Next Planning Trigger
- Re-plan if 24h n exceeds 150 and maker expectancy flips negative
- Re-plan when OpenClaw paper scaffold starts (new master plan)
- Re-plan if GHA minutes/cost become an issue from dense bot cadence

---

## One-line strategy

> **Stop pretending 1h is the product. Instrument the ledger, issue a 12h/24h candidate beside the SMA control, export maker-only paper signals only when the math clears — then build OpenClaw on that pipe.**
