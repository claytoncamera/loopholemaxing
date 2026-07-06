/* PNP TRACKER DATA — edit this file to add work, costs, or AI accounts, then reload the page. */
window.PNP_DATA = {
  "_readme": "THIS FILE IS THE DATABASE. The site renders whatever is here \u2014 edit it to add work, costs, or AI accounts, then reload. Every entry needs: date, title, type, tool, status, summary. Optional: version, hours, commits, loc, cost, tags. Types: build|feature|bugfix|deploy|affiliate|infra|content|research|ops. Keep hours honest \u2014 they roll up into the totals. Add new AI accounts under ai_accounts and their subscription cost under costs.",
  "meta": {
    "project": "Practically Natty Peptides \u2014 Command Center 2 (CC2)",
    "owner": "Clayton Camera",
    "role": "CTO & Managing Partner",
    "site": "practicallynatty.com",
    "tagline": "Informational tracker \u2014 what's been built, what it would have cost, how that cost was avoided, and what's in flight now.",
    "period_start": "2026-05-20",
    "last_updated": "2026-07-06",
    "value_hourly_rate": 150,
    "rate_note": "Blended senior full-stack rate, used only to estimate the market value of the work. Edit or set to 0 to hide value figures.",
    "agency_rate_low": 150,
    "agency_rate_high": 225,
    "agency_rate_note": "ESTIMATE. $150\u2013225/hr is a typical 2026 US retail rate for outsourcing WordPress/WooCommerce + React/TypeScript full-stack dev to an agency or senior contractor (agency day-rates run higher than solo-contractor because of PM/QA overhead this project doesn't carry). All cost figures below use this range \u2014 they are illustrative, not invoiced amounts.",
    "hard_stats": {
      "commits": 167,
      "releases": 53,
      "loc": 97026,
      "repos": 2,
      "live_plugins": 13,
      "_note": "Verified from git 2026-07-06: pnp-command-center-2 (144 commits / 38 tags / 84,708 LOC excl. build artifacts) + pnp-affiliate-hub (23 commits / 15 tags / 12,318 LOC). live_plugins = bespoke/mu-plugins edited directly on prod with no repo: pnp-command-center (legacy v4.1.2), pnp-elite-leaders, pnp-affiliate-auto-coupons, pnp-peptide-credits-live, pnp-july4-b2g1, pnp-sales-tax, pnp-mobile-header-row, pnp-suppress-frontend-errors, pnp-crash-guard, pnp-fix-reg-renum, pnp-slicewp-fixes, pnp-elite-dashboard-team-link, pnp-a3-affiliate-redirect."
    }
  },
  "ai_accounts": [
    {
      "id": "claude-code",
      "name": "Claude Code (Anthropic)",
      "vendor": "Anthropic",
      "monthly_cost": 200,
      "role": "Primary build + deploy + ops agent",
      "active": true
    },
    {
      "id": "codex",
      "name": "Codex / OpenAI",
      "vendor": "OpenAI",
      "monthly_cost": 200,
      "role": "Parallel coding sessions + reviews",
      "active": true
    },
    {
      "id": "perplexity",
      "name": "Perplexity (skills side)",
      "vendor": "Perplexity",
      "monthly_cost": 20,
      "role": "Research + PNP ops skills",
      "active": true
    }
  ],
  "costs": [
    {
      "date": "2026-05-01",
      "item": "Claude Code subscription",
      "category": "AI tooling",
      "amount": 200,
      "recurring": "monthly",
      "account": "claude-code",
      "note": "Primary agent \u2014 NEEDS CONFIRM: adjust to your actual plan tier"
    },
    {
      "date": "2026-05-01",
      "item": "Codex / OpenAI subscription",
      "category": "AI tooling",
      "amount": 200,
      "recurring": "monthly",
      "account": "codex",
      "note": "NEEDS CONFIRM \u2014 set to your actual plan tier"
    },
    {
      "date": "2026-05-01",
      "item": "Perplexity Pro",
      "category": "AI tooling",
      "amount": 20,
      "recurring": "monthly",
      "account": "perplexity",
      "note": "NEEDS CONFIRM"
    },
    {
      "date": "2026-05-01",
      "item": "Hostinger hosting (practicallynatty.com)",
      "category": "Infrastructure",
      "amount": 0,
      "recurring": "monthly",
      "note": "NOT TRACKED HERE \u2014 amount unknown, fill in your real hosting cost. Currently excluded from all totals below."
    }
  ],
  "milestones": [
    {
      "date": "2026-05-20",
      "label": "CC2 codebase born",
      "detail": "First commit of Command Center 2 (v0.5.26.0)."
    },
    {
      "date": "2026-06-24",
      "label": "Ops cadence hits daily",
      "detail": "Shipping + revenue tooling in daily production use."
    },
    {
      "date": "2026-07-02",
      "label": "Affiliate + credits economy relaunched",
      "detail": "Override mirror, credit system, July 4th sale, HUB overhaul \u2014 8 sessions in one day."
    },
    {
      "date": "2026-07-05",
      "label": "CC2 v0.5.39.2 \u2014 schema-drift wave fixed",
      "detail": "Silently-broken write paths across Bonuses/Credits/Alerts/Email repaired."
    }
  ],
  "entries": [
    {
      "date": "2026-05-20",
      "title": "Command Center 2 \u2014 foundation build",
      "type": "build",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.26.0 \u2192 v0.5.31.x",
      "summary": "Stood up CC2 from scratch: React/Vite/TypeScript control surface + PHP backend writing directly into the live WooCommerce DB. Orders, shipping, inventory, affiliate and email modules scaffolded. 101 commits landed this month \u2014 the heaviest build stretch of the project.",
      "hours": 60,
      "commits": 101,
      "loc": 55000,
      "tags": [
        "core",
        "architecture"
      ]
    },
    {
      "date": "2026-06-07",
      "title": "Autonomy + work-phone setup, fix sweep",
      "type": "infra",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Operating layer for running PNP hands-off: work-device separation, alert routing, and a cross-cutting fix sweep.",
      "hours": 4,
      "tags": [
        "ops"
      ]
    },
    {
      "date": "2026-06-12",
      "title": "PNP team + affiliate inventory",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Full inventory of the affiliate/team structure feeding the elite-leaders and HUB systems.",
      "hours": 3,
      "tags": [
        "affiliate"
      ]
    },
    {
      "date": "2026-06-15",
      "title": "Catalog cleanup",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Product catalog normalization pass across the WooCommerce store.",
      "hours": 3,
      "tags": [
        "catalog"
      ]
    },
    {
      "date": "2026-06-17",
      "title": "CC2 v0.5.32.8 deploy + search restyle",
      "type": "deploy",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.8",
      "summary": "Shipped v0.5.32.8 and restyled the storefront search (FiboSearch) to match the brand.",
      "hours": 4,
      "commits": 6,
      "tags": [
        "deploy",
        "frontend"
      ]
    },
    {
      "date": "2026-06-24",
      "title": "PNP deep audit + CC2 v0.5.34.0 + HUB v0.3.5",
      "type": "deploy",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.34.0",
      "summary": "Deep audit of the store + CC2, shipped v0.5.34.0 and affiliate HUB v0.3.5 (fixed unpaid-commission status + payouts fallback).",
      "hours": 6,
      "commits": 8,
      "tags": [
        "deploy",
        "affiliate"
      ]
    },
    {
      "date": "2026-06-24",
      "title": "CC2 v0.5.35.0 shipping fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.35.0",
      "summary": "Fixed a shipping-label calculation bug in the Shippo integration (live in daily production use).",
      "hours": 3,
      "tags": [
        "shipping"
      ]
    },
    {
      "date": "2026-06-25",
      "title": "Revenue Intelligence \u2014 5-view dashboard",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.36.0",
      "summary": "Shipped a 5-view revenue-intelligence dashboard + daily cron with accuracy/reliability passes. Live-verified.",
      "hours": 6,
      "commits": 10,
      "tags": [
        "analytics",
        "revenue"
      ]
    },
    {
      "date": "2026-06-25",
      "title": "Samantha payout rollback",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Audited + rolled back an incorrect affiliate payout safely (no double-pay).",
      "hours": 2,
      "tags": [
        "affiliate",
        "payouts"
      ]
    },
    {
      "date": "2026-06-26",
      "title": "Debug-noise + AJAX notice leak fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Root-caused a prod debug.log leak (admin-ajax notice bleed) \u2014 mu-plugin v2.2 + removed a stray diagnostic block; reclaimed ~1.6GB of log. Closed a git\u21c4prod version drift.",
      "hours": 4,
      "tags": [
        "ops",
        "hygiene"
      ]
    },
    {
      "date": "2026-06-26",
      "title": "CC2 view-label polish",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "summary": "UI labeling pass across CC2 views.",
      "hours": 2,
      "tags": [
        "frontend"
      ]
    },
    {
      "date": "2026-06-27",
      "title": "Email-tab ease-of-use (insert-block palette)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.37.0",
      "summary": "Added an 11-block insert palette to the email template editor + wired the 'Send test to me' endpoint. PR #98.",
      "hours": 5,
      "tags": [
        "email",
        "frontend"
      ]
    },
    {
      "date": "2026-06-27",
      "title": "Branch hygiene + Phase-7 WPCode inventory",
      "type": "infra",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Pruned 29 stale remote branches (CC2 now develop+main only, zero functionality lost) and produced a full read-only inventory of the 26 active WPCode snippets for the legacy-cutover plan.",
      "hours": 5,
      "tags": [
        "hygiene",
        "cutover"
      ]
    },
    {
      "date": "2026-06-28",
      "title": "A3 affiliate cutover + HUB v0.3.6",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.6",
      "summary": "Cutover: 36 affiliates now land on the rich HUB instead of the bare SliceWP page (reversible mu-plugin redirect). Expanded FAQ, verified QR generation, fixed the doctor false-negative.",
      "hours": 5,
      "commits": 3,
      "tags": [
        "affiliate",
        "cutover"
      ]
    },
    {
      "date": "2026-06-29",
      "title": "Affiliate dashboard upgrades \u2014 HUB v0.3.7",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.7",
      "summary": "4 affiliate-facing wins live for all 36 affiliates: fixed the Earn-tab CSS bug, fixed a broken Apply link, added a payout-clarity balance widget, added one-tap recruiting-link copy. Verified click-tracking (1,056 visits) + commission attribution.",
      "hours": 6,
      "commits": 5,
      "tags": [
        "affiliate",
        "frontend"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Catalog +10% price raise (64 products)",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Applied a +10% raise across 64 products (nearest even dollar, 2 excluded), with rollback CSVs and live math verification incl. B2G1 + tax fee.",
      "hours": 3,
      "tags": [
        "catalog",
        "pricing"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Logo redraw + single-line mobile header",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Vector-redrew the logo (deep-metallic gradient) and rebuilt the mobile header into a single clean line \u2014 solved through a load-bearing Elementor widget-width discovery (CSS-only overrides are impossible; DOM-move the inner container).",
      "hours": 6,
      "tags": [
        "frontend",
        "brand"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "July 4th sale \u2014 3-tier engine",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.4.0",
      "summary": "Built a live-only sale plugin: Buy-2-Get-1 on 10 products + 20% off best-sellers + 30% off everything else, three disjoint taxable cart fees, coupon-blocking, banner + popup + per-deal badges. Prod suites 15/15.",
      "hours": 8,
      "tags": [
        "sales",
        "promo"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Affiliate/credits audit + double-pay fix",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "elite-leaders v3.2.0",
      "summary": "Neutralized a payout double-pay risk (voided 2 pending batches, gated the auto-batch cron) and wired the credit-rewards drip engine (1 credit / $10 sales, all affiliates). First run: 1,466 credits to 7 affiliates, idempotent.",
      "hours": 6,
      "tags": [
        "affiliate",
        "credits"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Override mirror \u2014 payable leader overrides",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "elite-leaders v3.3.0",
      "summary": "Shipped the override-mirror engine so leader L1/L2 overrides (5%/2%) mirror into SliceWP and become payable via the normal flow. Built recon\u2192implement\u2192adversarial-review with 3 agents; review caught a NOT-NULL strict-mode landmine pre-deploy. Prod E2E passed.",
      "hours": 7,
      "tags": [
        "affiliate",
        "commissions"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Credit system relaunch + 34-affiliate broadcast",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Final credit economics (1cr = $0.20 cash / $1 product; 1,000cr = $200 cash-out; earn 1cr/$10). Product-spend live via a new plugin (FIFO + ledger, 50% cap, auto-restore on refund). Sent an approved 34/34 broadcast with per-affiliate links + QR codes.",
      "hours": 6,
      "tags": [
        "affiliate",
        "credits",
        "email"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "HPOS sales-aggregate fix (v0.5.37.1)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.37.1",
      "summary": "Fixed the Overview 'errors every morning' bug \u2014 the net-sales fallback referenced HPOS columns that don't exist; now LEFT JOINs the operational-data table. Verified per-order vs wc_order_stats.",
      "hours": 4,
      "tags": [
        "analytics",
        "hpos"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "HUB 'Cookie check failed' fix (v0.4.1/.2)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.4.2",
      "summary": "Fixed logged-out affiliates seeing a broken shell + raw error: boot guard, silent nonce refresh + retry, friendly session-expired banner, real logout URL. Added the credits card full breakdown.",
      "hours": 5,
      "tags": [
        "affiliate",
        "frontend"
      ]
    },
    {
      "date": "2026-07-02",
      "title": "Coupon\u00d7sale stacking + Andrew reattribution",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v1.5.0",
      "summary": "Let affiliate coupons stack with the July-4th sale (others blocked), and reattributed order 2932 to the right affiliate via an audited preview\u2192commit.",
      "hours": 3,
      "tags": [
        "affiliate",
        "coupons"
      ]
    },
    {
      "date": "2026-07-03",
      "title": "Calendar tab overhaul (v0.5.38.0/.1)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.38.1",
      "summary": "Made the Calendar tab work end-to-end: fixed approve-&-send (every approval had 400'd), rebuilt recurrence natively (old engine died after 30 days), repaired the tick state machine, added the first Edit flow, UTC display fix. Prod E2E 10/10.",
      "hours": 8,
      "tags": [
        "feature",
        "calendar"
      ]
    },
    {
      "date": "2026-07-04",
      "title": "UTC timestamp sweep (v0.5.38.2)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.38.2",
      "summary": "Swept UTC display handling across CC2 so timestamps stop showing shifted by the offset. Deployed + 10/10 verified.",
      "hours": 4,
      "tags": [
        "bugfix"
      ]
    },
    {
      "date": "2026-07-05",
      "title": "SMS console + Customer Contact Library (v0.5.39.0)",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.39.0",
      "summary": "New Contacts tab (customer DB with checkout auto-capture) + an SMS console behind a fail-safe gate (zero texts sendable until a provider is wired). DB migration 8\u21929.",
      "hours": 6,
      "commits": 6,
      "tags": [
        "feature",
        "sms",
        "crm"
      ]
    },
    {
      "date": "2026-07-05",
      "title": "Schema-drift bugfix wave (v0.5.39.1/.2) + HUB v0.4.3",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.39.2",
      "summary": "Found + fixed writes that had been silently no-op'ing while reporting success: Bonuses/Credits (wrong tables + wrong write endpoints), Alerts/Email-Ops (500'd since 06-27). HUB v0.4.3 fixed 11 affiliate rate/payment lookups + a silently-failing payment-email save. Live-verified with a real $200 credit.",
      "hours": 7,
      "tags": [
        "bugfix",
        "affiliate",
        "schema"
      ]
    },
    {
      "date": "2026-07-05",
      "title": "25-affiliate 5% coupon rollout",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Created + linked personal LASTNAME5 codes for the 25 affiliates who lacked one, matched to the auto-plugin's attribution meta, and sent 24 personalized onboarding emails.",
      "hours": 3,
      "tags": [
        "affiliate",
        "coupons",
        "email"
      ]
    }
  ],
  "open_items": [
    {
      "title": "Phase 7 \u2014 retire dual-firing WPCode snippets",
      "priority": "medium",
      "status": "in-progress",
      "now": true,
      "note": "Inventory done (26 active snippets: 18 PHP / 7 CSS / 1 trivial). Next: per-snippet dual-fire proof \u2192 staging deactivation \u2192 prod retirement. HIGH RISK, staging first."
    },
    {
      "title": "pnp-elite-leaders tier-decay cron fix",
      "priority": "high",
      "status": "plan-ready \u2014 awaiting go",
      "now": false,
      "note": "reference_amount \u2192 order_total rename (5 files) + mute tier-change notifications during catch-up recalc. Erroring 12\u00d7/day since 06-27, silently zeroing tier-decay math. Live-only plugin, no repo \u2014 fully specified, needs Clayton's final go to execute."
    },
    {
      "title": "Verify coupon-affiliate commission rates",
      "priority": "high",
      "status": "blocked on Clayton/SSH",
      "now": false,
      "note": "Reported live rates: elite=15% / regular=13%, base after all discounts. No git trace (live-only plugin, no repo) and no SSH/wp-cli reach \u2014 needs Clayton to confirm live rates directly or authorize SSH before this is written as brain-truth."
    },
    {
      "title": "Wire an SMS provider",
      "priority": "medium",
      "status": "blocked on provider choice",
      "now": false,
      "note": "SMS console shipped (v0.5.39.0) but no provider configured \u2014 zero texts sendable until one is added. Needs Clayton to pick a provider (Twilio, etc.)."
    },
    {
      "title": "v0.6.0.0 \u2014 legacy cutover",
      "priority": "medium",
      "status": "queued, blocked on Phase 7",
      "now": false,
      "note": "Retire legacy pnp-command-center v4.1.2 + dead one-off plugins; port the coupon-affiliate crediting class first. Requires Phase 7 done."
    },
    {
      "title": "Affiliate creative/banner pack",
      "priority": "low",
      "status": "queued, blocked on assets",
      "now": false,
      "note": "HUB creatives gallery empty \u2014 needs real brand assets from Clayton (no AI-slop, per standing rule)."
    },
    {
      "title": "debug.log rotation",
      "priority": "low",
      "status": "deferred",
      "now": false,
      "note": "1.1GB of benign notices \u2014 needs truncate/rotate. No blocker, just not prioritized."
    },
    {
      "title": "Real Stripe payments",
      "priority": "low",
      "status": "future",
      "now": false,
      "note": "Zelle/Venmo manual verify is the current real flow. Not started."
    }
  ]
};
