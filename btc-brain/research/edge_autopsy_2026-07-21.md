# [Trading] BTC Brain Edge Autopsy
**Date:** 2026-07-21  
**Ledger snapshot:** accuracy.json `generated_at=2026-07-21T20:37:18Z`  
**Sample:** 1,509 forecasts · 1,505 resolved · **only** `v0.1.0-baseline-shadow`  
**Method:** join forecasts.jsonl ↔ resolutions.jsonl; Wilson 95% CIs; fee stress at maker RT 2 bps / taker RT 10 bps

---

## Executive verdict

**There is a real directional edge — and it is almost entirely in the 12h/24h horizons.**

The live issuer is still a conservative SMA(24) shadow model with probabilities clamped to ~[0.50, 0.55]. Phase 3/4 model code exists in-repo but is **not wired to production issuance**. `regime_at_issue` is always `unknown`. Confidence intervals are a stub. Phase 4 report is `fixture_only=true` from 2026-04-27.

| Horizon | n | Hit | vs majority | Exp (no fee) | Maker 2bps | Taker 10bps | Tradeable? |
|---------|---|-----|-------------|--------------|------------|-------------|------------|
| **24h** | 84 | **63.1%** | **+13.1 pp** | **+56.0 bps** | +54.0 bps | +46.0 bps | **YES — primary** |
| **12h** | 169 | **57.4%** | **+5.3 pp** | **+25.7 bps** | +23.7 bps | +15.7 bps | **YES — secondary** |
| 4h | 471 | 54.8% | −2.6 pp | +7.2 bps | +5.2 bps | −2.8 bps | Research only |
| 1h | 781 | 52.9% | **−9.2 pp** | +3.5 bps | +1.5 bps | −6.5 bps | **NO — fee + majority death** |
| ALL | 1505 | 54.6% | −4.3 pp | +10.1 bps | +8.1 bps | ~0 | Diluted by 1h |

### 24h counterfactual (same sample)
- Always-up: 50% hit, **−8.3 bps** expectancy  
- Always-down: 50% hit, **+8.3 bps**  
- **SMA shadow model: 63.1% hit, +56.0 bps**  

That is not a bullish-bias artifact. On 24h the model actually separates.

---

## What the live model is

From `schedule_forecasts.py`:
- Signal: latest closed 1h close vs SMA of prior 24 closes
- Direction: above → up, below → down
- Probability: floor 0.5005 + min(rel_distance, 0.0495) → never > 0.55
- Horizons issued: 1h / 4h / 12h / 24h on bucket grid
- Label: `v0.1.0-baseline-shadow` / `scheduled-issuer/baseline-shadow`
- Cadence: GHA issue ~:17 past hour; resolve ~:07; snapshot :13/:43

---

## Where edge lives (and where it dies)

### 1. Timeframe (dominant)
Longer horizons show:
- higher hit rate
- better win/loss ratio (24h W/L ≈ 1.34)
- fee survival
- positive delta vs majority baseline

Shorter horizons are dominated by **up-bias of the sample period** (always-up on 1h = 62.1%). The SMA model underperforms just buying every 1h bar.

### 2. Direction asymmetry (critical for 1h/4h)
| Horizon | UP hit | DOWN hit |
|---------|--------|----------|
| 1h | **63.6%** (n=431) | **39.7%** (n=350) |
| 4h | 61.5% | 47.3% |
| 12h | 59.5% | 55.3% |
| 24h | 64.1% | **62.2%** |

On 24h both sides work. On 1h, DOWN forecasts are toxic.

### 3. "Confidence" is inverted
SMA divergence is mapped to higher probability — but **higher conf → worse hits**:

| Conf bucket | n | Hit | Exp |
|-------------|---|-----|-----|
| Low (near SMA) | 502 | **60.0%** | +14.9 bps |
| Mid | 502 | 56.0% | +12.9 bps |
| High (far from SMA) | 501 | **47.7%** | +2.6 bps |

High-conf × 24h: only 42.9% hit (n=28) — mean-reversion after large deviations kills momentum extension.

**Upgrade implication:** stop treating SMA distance as confidence. Prefer mild divergence / chop-exit signals; use real calibration (Platt/isotonic from Phase 3).

### 4. Calendar microstructure (exploratory, smaller n)
- **Saturday** hit 68.4% (n=247) — strongest DOW  
- Wednesday 47.3%, Sunday 47.8% — weak  
- Hour **20 UTC** toxic (39.2%, n=125); hours 08/10/21 stronger  

Treat as filters to *test in shadow*, not as locked edge yet (multiple-comparison risk).

### 5. Last-30d degradation on short horizons
Last 30d overall hit 53.7% but **−7.9 pp vs majority** (market was more one-sided up). 24h edge must be re-checked as n grows past 84.

---

## Infrastructure gaps blocking real upgrades

| Gap | Evidence | Impact |
|-----|----------|--------|
| Phase 3/4 never live-issued | Only model_version in ledger is baseline-shadow | No learned model in production |
| Regime always `unknown` | every forecast row | No regime-conditional edge tracking |
| Confidence intervals stub | `method: none`, `display_ready: false` | UI can't show calibrated bands |
| Phase 4 report fixture-only | dated 2026-04-27 | Promotion gates never evaluated on live ledger |
| Binance derivatives 451 | GHA geo block | Funding/OI/LSR incomplete |
| Bybit 403 | same | Fallback thin |
| OKX partial | missing account L/S % | Derivatives feature weak |
| SMA200 null | key_levels notes | Macro level incomplete |
| accuracy.json no by-direction / by-fee | metrics-v0.1.0 | Edge autopsy must be external script |
| ECE always null | accuracy.json | Calibration gate unmeasurable on live |

---

## Market context (2026-07-21 briefing)
- Mark ~$66,330 (OKX)
- Fear & Greed **25 Extreme Fear**
- Funding slightly negative
- OI ~32.1k BTC
- Key levels: pivot ~64,890 · R1 66,079 · recent high 66,387

Extreme fear + 24h SMA edge is a plausible regime for the next candidate, but must be tested OOS — not assumed.

---

## Edge thesis for upgrade (falsifiable)

1. **Primary product signal = 24h direction, maker-only economics.**  
   Gate: hit > 55% with Wilson lower bound > 52% at n≥100; expectancy after 2 bps > 20 bps.

2. **Secondary = 12h**, same fee gate, n≥150.

3. **1h/4h stay research-only** until a model beats always-up on Brier *and* survives taker — current SMA does not.

4. **Do not use SMA |distance| as confidence.** Invert or replace with calibrated P from logistic/features.

5. **Optional filter experiments (shadow only):** skip hour 20 UTC; prefer weekend; prefer mild rel∈[0, 0.5%]; never auto-promote filters without OOS.

6. **OpenClaw input:** only emit `signal.json` for 24h (and maybe 12h) when thesis gates pass; never for 1h.

---

## What "fully updated" means

A upgraded BTC Brain is not "more forecasts." It is:

1. Live dual-issuer: baseline shadow **plus** candidate model with distinct `model_version`
2. Real regime labels on every issue
3. accuracy.json extended: by_direction, by_regime, fee-adjusted expectancy, ECE
4. 12h/24h product path; 1h demoted in public claims
5. Derivatives feed health green without Binance dependency
6. Phase 4 promotion evaluated on **live** ledger (not fixture)
7. `signal.json` contract for OpenClaw paper trading
8. Edge autopsy script checked into repo, run on every metrics refresh

---

*Autopsy script inputs: `btc-brain/ledger/data/{forecasts,resolutions}.jsonl` from loopholemaxing@main 2026-07-21.*
