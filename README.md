# Loopholemaxing

**Find Every Edge.** Systems, research, and tools — built by obsessive analysis.

Live at **[loopholemaxing.com](https://loopholemaxing.com)**

---

## Current Creations

### [BTC Intelligence Brain](https://loopholemaxing.com/btc-brain/)
A comprehensive, living Bitcoin research and trading intelligence system.

**14 sections across 2 categories:**

#### Research Chapters (12)
| # | Chapter | Coverage |
|---|---------|----------|
| 01 | Fundamentals | Protocol parameters, supply mechanics, genesis |
| 02 | Price History | Full era-by-era timeline 2009–2026, yearly returns |
| 03 | Halving Cycles | All 4 halvings, peak/bottom data, diminishing returns |
| 04 | Bull & Bear Markets | Every bull/bear market, Wyckoff phases, recovery times |
| 05 | Technical Analysis | Chart patterns, MA system, Fibonacci, volume behavior |
| 06 | On-Chain Metrics | MVRV, SOPR, NUPL, LTH/STH, hash ribbons, exchange flows |
| 07 | Sentiment | Fear & Greed, funding rates, behavioral psychology |
| 08 | Macro Correlations | BTC vs SPX/Gold/DXY, Fed policy, ETF flows, institutions |
| 09 | Black Swans | Mt. Gox, COVID, Luna, FTX, SVB, ETF approval |
| 10 | Trading Strategies | 5 backtested strategies, DCA analysis, composite scoring |
| 11 | Risk Management | Kelly Criterion, position sizing, leverage rules |
| 12 | Current Assessment | Live cycle position, key levels, short/medium/long outlook |

#### Live Intelligence (2)
| Tab | Description |
|-----|-------------|
| Live Market | Real-time BTC command center — live price, multi-TF trend matrix, hourly candles, alignment score. Auto-refreshes every 30s via Binance API (CoinGecko fallback) |
| IQ System | Brain intelligence dashboard — IQ score 147, 16 intelligence matrices, 12-module connectivity grid, learning state, strengths/weaknesses/active upgrades |

**Stats:**
- 5,578+ lines of research across 5 deep markdown files
- 10 analytical charts (price history, cycles, heatmap, drawdowns, etc.)
- 137KB master intelligence document
- Live market data via Binance public API with CoinGecko fallback
- Auto-deploys to loopholemaxing.com on every push to `main`

---

## Repository Structure

```
loopholemaxing/
├── index.html                          # Homepage — creation hub
├── styles.css                          # Shared stylesheet (both pages)
├── 404.html                            # Custom 404 with routing fallback
├── CNAME                               # Custom domain: loopholemaxing.com
├── .nojekyll                           # Disable Jekyll processing
├── README.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── pages.yml                   # GitHub Actions deployment
└── btc-brain/
    ├── index.html                      # BTC Brain (2,035 lines)
    ├── BTC-INTELLIGENCE-BRAIN.pplx.md  # Master knowledge base (137KB)
    ├── charts/                         # 10 analytical PNG charts
    │   ├── 01-btc-price-history-log.png
    │   ├── 02-halving-cycle-comparison.png
    │   ├── 03-monthly-returns-heatmap.png
    │   ├── 04-drawdown-history.png
    │   ├── 05-moving-averages.png
    │   ├── 06-volume-analysis.png
    │   ├── 07-volatility-regimes.png
    │   ├── 08-cycle-overlay.png
    │   ├── 09-annual-returns.png
    │   └── 10-cycle-dashboard.png
    └── research/                       # 5 deep research files (5,578 lines)
        ├── 01-macro-history-cycles.md
        ├── 02-technical-chart-structure.md
        ├── 03-onchain-sentiment-liquidity.md
        ├── 04-macro-correlations-institutional.md
        └── 05-trading-frameworks-strategies.md
```

---

## Deployment

**Automatic.** Every push to `main` triggers GitHub Actions which deploys to GitHub Pages at [loopholemaxing.com](https://loopholemaxing.com).

- Build: GitHub Actions (`pages.yml`)
- Hosting: GitHub Pages
- Domain: GoDaddy → A records → GitHub Pages IPs
- SSL: Let's Encrypt (auto-renews, valid through Jul 4, 2026)
- HTTPS: Enforced — all HTTP auto-redirects to HTTPS

## DNS Configuration

| Type | Name | Value |
|------|------|-------|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | claytoncamera.github.io |

---

## Tech Stack

- **Frontend:** Pure HTML5, CSS3, Vanilla JavaScript — no frameworks, no dependencies
- **Charts:** Matplotlib (pre-generated PNG, served statically)
- **Live Data:** Binance public REST API + CoinGecko fallback
- **Deployment:** GitHub Actions → GitHub Pages
- **Domain:** GoDaddy → loopholemaxing.com

---

## Built By

Clayton Camera — 2026

*More creations coming.*
