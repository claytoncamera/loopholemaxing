/* PNP TRACKER DATA — edit this file to add work, costs, or AI accounts, then reload the page. */
window.PNP_DATA = {
  "_readme": "THIS FILE IS THE DATABASE. The site renders whatever is here — edit it to add work, costs, or AI accounts, then reload. Every entry needs: date, title, type, tool, status, summary. Optional: version, hours, commits, loc, cost, tags. Types: build|feature|bugfix|deploy|affiliate|infra|content|research|ops. Keep hours honest — they roll up into the totals. Add new AI accounts under ai_accounts and their subscription cost under costs.",
  "meta": {
    "project": "Practically Natty Peptides — Command Center 2 (CC2)",
    "owner": "Clayton Camera",
    "role": "CTO & Managing Partner",
    "site": "practicallynatty.com",
    "tagline": "Informational tracker — what's been built, what it would have cost, how that cost was avoided, and what's in flight now.",
    "period_start": "2026-05-20",
    "last_updated": "2026-07-06",
    "value_hourly_rate": 150,
    "rate_note": "Blended senior full-stack rate, used only to estimate the market value of the work. Edit or set to 0 to hide value figures.",
    "agency_rate_low": 150,
    "agency_rate_high": 225,
    "agency_rate_note": "ESTIMATE. $150–225/hr is a typical 2026 US retail rate for outsourcing WordPress/WooCommerce + React/TypeScript full-stack dev to an agency or senior contractor (agency day-rates run higher than solo-contractor because of PM/QA overhead this project doesn't carry). All cost figures below use this range — they are illustrative, not invoiced amounts.",
    "hard_stats": {
      "commits": 167,
      "releases": 53,
      "loc": 97026,
      "repos": 2,
      "live_plugins": 13,
      "_note": "Verified from git 2026-07-06: pnp-command-center-2 (144 commits / 38 tags / 84,708 LOC excl. build artifacts) + pnp-affiliate-hub (23 commits / 15 tags / 12,318 LOC). live_plugins = bespoke/mu-plugins edited directly on prod with no repo: pnp-command-center (legacy v4.1.2), pnp-elite-leaders, pnp-affiliate-auto-coupons, pnp-peptide-credits-live, pnp-july4-b2g1, pnp-sales-tax, pnp-mobile-header-row, pnp-suppress-frontend-errors, pnp-crash-guard, pnp-fix-reg-renum, pnp-slicewp-fixes, pnp-elite-dashboard-team-link, pnp-a3-affiliate-redirect. Work log below re-derived 2026-07-06 from a full brain + git-log audit: 70 granular entries (was 29) — every tagged release plus untagged hotfix-lane deploys (HUB v0.3.3/v0.3.5, CC2 v0.5.39.1/.2) and no-repo website/WP changes (logo, mobile header, catalog pricing, WPCode inventory, branch hygiene) each get their own row, sourced from journal/*.md and git log — not fabricated. Added 2026-07-06 (same-day follow-up): COGS/Realized-P&L engine (v0.5.40.0-v0.5.40.3), shipping label cost-capture fix, and the Thymalin product launch — 4 more entries, +19h."
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
      "note": "Primary agent — NEEDS CONFIRM: adjust to your actual plan tier"
    },
    {
      "date": "2026-05-01",
      "item": "Codex / OpenAI subscription",
      "category": "AI tooling",
      "amount": 200,
      "recurring": "monthly",
      "account": "codex",
      "note": "NEEDS CONFIRM — set to your actual plan tier"
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
      "note": "NOT TRACKED HERE — amount unknown, fill in your real hosting cost. Currently excluded from all totals below."
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
      "detail": "Override mirror, credit system, July 4th sale, HUB overhaul — 8 sessions in one day."
    },
    {
      "date": "2026-07-05",
      "label": "CC2 v0.5.39.2 — schema-drift wave fixed",
      "detail": "Silently-broken write paths across Bonuses/Credits/Alerts/Email repaired."
    }
  ],
  "entries": [
    {
      "date": "2026-05-20",
      "title": "CC2 hosted-mode auth bridge + workbench proxy foundation",
      "type": "build",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.25–v0.5.25.7",
      "summary": "Initial CC2 source build: hosted-mode auth bridge for cc2.practicallynatty.com, hosted frontend packaging, temporary workbench proxy gate (server-side gate + same-origin REST proxy), proxy-secret pre-dispatch auth, v6 API route compatibility, and corrected affiliate/Elite Leader display contract. This is literally CC2's birth day — 18 commits across 7 merged PRs (#1–#7) in one day.",
      "tags": [
        "cc2",
        "foundation",
        "auth",
        "proxy"
      ],
      "hours": 10
    },
    {
      "date": "2026-05-21",
      "title": "Inventory tab (read-only) — categories, velocity, drift flags",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.26.0",
      "summary": "New read-only Inventory tab: backend extends tabs/inventory with categories, velocity, drift flags, server-side filters and facets; frontend page with category/visibility/sale filters and drift badges. Two quick follow-up hotfixes same day (v0.5.26.1: collapsible filter rail + flex layout for table scroll) and a filter-hash sync guard.",
      "tags": [
        "cc2",
        "inventory",
        "frontend"
      ],
      "hours": 4
    },
    {
      "date": "2026-05-21",
      "title": "Inventory write endpoints + drawer UI",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.27.0",
      "summary": "Five inventory write endpoints (stock-qty, stock-status, low-stock-threshold, visibility, manage-stock-toggle) with dry-run + idempotency, plus the frontend write drawer with dry-run preview and a typed write registry. Includes a same-day plugin-header Version-field hotfix.",
      "tags": [
        "cc2",
        "inventory",
        "writes"
      ],
      "hours": 4
    },
    {
      "date": "2026-05-21",
      "title": "Calendar Upgrade — Launch Preview wizard + executor forms",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.28.0",
      "summary": "Calendar backend gains preview_schema/preview_render and email/popup/audience catalog endpoints plus a merge-tag email-render preview (send-suppressed). Frontend: 3-step Launch Preview wizard (email iframe + popup preview + structured diff), a full calendar surface upgrade (event detail drawer, recent runs, approval queue, pause banner, week view, range picker), and per-executor configure forms with product/affiliate/rrule pickers.",
      "tags": [
        "cc2",
        "calendar",
        "frontend"
      ],
      "hours": 5
    },
    {
      "date": "2026-05-22",
      "title": "Email Engine — templates, editor, broadcast, ops/stats",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.29.0",
      "summary": "Full email system stood up in one day: template list view with search/New CTA, template editor drawer with sandboxed preview, 10 seed starter templates with idempotent importer, broadcast panel with dry-run + gated send (monetization unlock), and email ops/stats views with warning banners. Also fixed the affiliates-leaders query (schema-probe coupon_code column) and verified the calendar email executor.",
      "tags": [
        "cc2",
        "email",
        "monetization"
      ],
      "hours": 6
    },
    {
      "date": "2026-05-24",
      "title": "Re-attribution engine — read/write endpoints + audit",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.0 (Phase 1–2)",
      "summary": "Re-attribution read endpoint plus write controller with audit trail, so commissions can be manually reassigned between affiliates with a tracked decision log. Includes a same-day hotfix (v0.5.31.1) for a React mount-point div id regression.",
      "tags": [
        "cc2",
        "affiliate",
        "reattribution"
      ],
      "hours": 3
    },
    {
      "date": "2026-05-24",
      "title": "Coupons Center — full build (read, write, duration, audit, bulk ops)",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.2",
      "summary": "Large single-day build of the Coupons Center: read endpoint with collision-check, create/update writes (collision-gated, attribution-stamped), duration controls (schedule/expire/pause/resume), attribution audit + drift report + backfill (trust unlock), and bulk operations dashboard (stale/orphan/duplicate detection). Backend items B1/B2/B5/B6/B7 all shipped same day alongside the re-attribution frontend (Attribution sub-tab, Candidates Inbox, Decision Drawer) and a weekly Monday-8AM reattribution digest cron.",
      "tags": [
        "cc2",
        "coupons",
        "monetization"
      ],
      "hours": 8
    },
    {
      "date": "2026-05-24",
      "title": "Affiliate Payments tab — bulk-mark, rollback, effective-status",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.2",
      "summary": "Payments bulk-mark-paid with rollback and effective-status computation (backend A4), extended into the frontend AffiliatePaymentsTab with a MarkPaidModal and rollback UI — no money actually moves, this is the bookkeeping/reconciliation layer against SliceWP as the real payout source.",
      "tags": [
        "cc2",
        "affiliate",
        "payments"
      ],
      "hours": 3
    },
    {
      "date": "2026-05-25",
      "title": "Coupons Center frontend — Create/Edit drawers + batch confirm + 60s undo",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.2",
      "summary": "Frontend completion of the Coupons Center and re-attribution UI: Coupons list + detail drawer (read-only), Create/Edit drawers (monetization unlock), duration controls UI, attribution audit/drift/backfill UI, bulk-ops dashboard, plus a BatchConfirmModal with 60-second undo for re-attribution decisions. Wired DecisionDrawer enqueue into the Candidates Inbox same day.",
      "tags": [
        "cc2",
        "coupons",
        "reattribution",
        "frontend"
      ],
      "hours": 5
    },
    {
      "date": "2026-05-25",
      "title": "v0.5.31.2 stabilization hotfixes (require_once order, Canonical_Values, stripped bundle)",
      "type": "bugfix",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.3–v0.5.31.5",
      "summary": "Three same-window hotfixes after the big v0.5.31.2 push: fixed require_once load order so PNP_CC2_Write_Base class was found, corrected a Canonical_Values method/key bug in resolve_affiliate_rate, and restored the v0.5.31.2 React bundle that had been accidentally stripped during the v0.5.31.4 rebuild.",
      "tags": [
        "cc2",
        "hotfix",
        "stability"
      ],
      "hours": 2
    },
    {
      "date": "2026-05-26",
      "title": "Coupon health render fix + bulk CSV import for re-attribution",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.6–v0.5.31.8",
      "summary": "Fixed a blank-render bug in Coupon health with an ErrorBoundary backstop, then shipped bulk CSV import for re-attribution decisions with a same-day follow-up wiring commission_id_existing through the import path correctly. CI also updated to build and attach the hosted-proxy zip on release.",
      "tags": [
        "cc2",
        "coupons",
        "reattribution",
        "csv"
      ],
      "hours": 3
    },
    {
      "date": "2026-05-28",
      "title": "LiteSpeed drift-detection baseline widened",
      "type": "infra",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.31.9",
      "summary": "Widened the LiteSpeed canonical cache-exclusion baseline from 5 to 7 URIs as part of drift-detection hardening, bundled into the v0.5.31.9 release bump.",
      "tags": [
        "cc2",
        "infra",
        "caching"
      ],
      "hours": 1
    },
    {
      "date": "2026-05-28",
      "title": "Shipping Center — full build (foundation → Phase 6, MONETIZATION UNLOCK)",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.32.0",
      "summary": "Major multi-phase feature ship in a single day: Shipping Center foundation + settings UI (Phase 1/1b), Orders-to-Ship view (Phase 2), payment override + audit (Phase 3), the label creation wizard — flagged MONETIZATION UNLOCK (Phase 4), Labels Folder with download/print/regenerate/void (Phase 5), print-auth core with capability/role/token-mint/file-serve/per-print history (Phase 5b) and its UI (Phase 5c), and a customer shipping-email service (Phase 6, all toggles defaulted off same day for safety).",
      "tags": [
        "cc2",
        "shipping",
        "monetization",
        "shippo"
      ],
      "hours": 9
    },
    {
      "date": "2026-05-29",
      "title": "Shipping Center — webhooks, tracking cron, audit log, payment-verify stubs",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.0 (Phase 7–9)",
      "summary": "Completed the Shipping Center release: Shippo webhooks + tracking cron (Phase 7), shipping audit log with a failed-tab and retry/resolve actions (Phase 8), and architecture-only payment-verify modular stubs (Phase 9, deliberately inert — manual Zelle/Venmo verification stays the real flow). Version bumped to close out v0.5.32.0.",
      "tags": [
        "cc2",
        "shipping",
        "webhooks",
        "payment-verify"
      ],
      "hours": 5
    },
    {
      "date": "2026-05-29",
      "title": "Shipping Center simplification + auto-create labels",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.1",
      "summary": "Simplified the Shipping Center flow and added auto-create for labels, shipped as a fast follow the day after the Phase 1-9 Shipping Center launch.",
      "tags": [
        "cc2",
        "shipping"
      ],
      "hours": 2
    },
    {
      "date": "2026-05-30",
      "title": "Opt-in daily shipping digest",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.2",
      "summary": "Added an opt-in daily digest email for shipping status (S6), giving operators a passive daily summary instead of needing to check the Fulfill tab.",
      "tags": [
        "cc2",
        "shipping",
        "email"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-01",
      "title": "Shipping correctness pass — label idempotency, safety skip, operator drift-fix controls",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.3",
      "summary": "Fixed a NULL bug in label-create idempotency and added a fulfillment cutoff (A1/A2), shipped S7 label-safety (no-label-needed skip + external-label awareness), and added operator controls with drift-fix buttons and a read-only toggle (C1/C2).",
      "tags": [
        "cc2",
        "shipping",
        "idempotency"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-01",
      "title": "Label purchase fix — address_from.name + surfaced purchase errors",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.4",
      "summary": "Fixed a bug blocking label purchase (address_from.name wasn't populated) and surfaced Shippo purchase errors to the operator instead of failing silently.",
      "tags": [
        "cc2",
        "shipping",
        "shippo",
        "bugfix"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-01",
      "title": "Label wizard pre-fills saved package defaults",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.5",
      "summary": "Small UX improvement: the label creation wizard now pre-fills previously saved package defaults instead of requiring re-entry every time.",
      "tags": [
        "cc2",
        "shipping",
        "ux"
      ],
      "hours": 1
    },
    {
      "date": "2026-06-10",
      "title": "One-command hotfix deploy lane (scripts/deploy.sh)",
      "type": "infra",
      "tool": "claude-code",
      "status": "shipped",
      "version": "PR #91",
      "summary": "Built the rsync-over-SSH one-command deploy script replacing the manual zip-to-WP-admin upload cycle: build, bundle-sync guard, secret scans, schema guard, server backup, checksum dry-run, typed confirm, deploy, then wp-cli/sha256/curl verification. This became the standard deploy mechanism for every release after it.",
      "tags": [
        "cc2",
        "deploy",
        "tooling",
        "infra"
      ],
      "hours": 4
    },
    {
      "date": "2026-06-10",
      "title": "Team tab fix — real schema (leader_id/affiliate_user_id/status)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.6",
      "summary": "Fixed the Team tab showing 0 members for every leader: it was probing for columns that don't exist (parent_leader_id/member_user_id) instead of the real schema (leader_id/affiliate_user_id/status). Fixed to active-only membership with a generic recruit_count-drift signal, removing hardcoded Samantha/Kyle special-casing. Verified live: Samantha showed her 2 Kyles, Clayton showed his 1.",
      "tags": [
        "cc2",
        "team",
        "affiliate",
        "bugfix"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-11",
      "title": "HUB team override widget — real /team endpoint",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.2 (PR #1)",
      "summary": "Replaced the Earn-tab team placeholder in the affiliate HUB with a real /team endpoint showing PII-redacted members, L1 5%/L2 2% override rates, and per-member sales. Closed the planned 6-8h 'Team Tables' milestone in a fraction of the time — turned out to be one CC2 read-fix plus this widget.",
      "tags": [
        "hub",
        "affiliate",
        "team"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-12",
      "title": "One-click inventory apply + stock correctness fix",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.7",
      "summary": "Inventory adjust drawer became 'Save to live' in one click (no preview/confirm gate needed) with a matching one-click Undo, proving the full proxy auth write-path end to end (secret matches, promotes to admin, live stock verified 43→44→43). Also fixed 2 untracked sellable variations (Sermorelin 10mg #949, Thymosin A1 5mg #931), bringing untracked-but-sellable inventory to zero.",
      "tags": [
        "cc2",
        "inventory",
        "bugfix"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-15",
      "title": "Catalog cleanup — category moves, dedupe, BAC Water variable conversion",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Multi-round catalog cleanup on prod via wp-cli: moved 3 products to more accurate categories (SLU-PP-322, SS-31, Oxytocin), force-deleted a duplicate MT-1 product (with full backup), converted BAC Water #2687 from simple to a variable product (10mL/30mL with correct pricing and stock), fixed a mis-nested category dropdown in the main nav menu, and set a proper 301 redirect when a product slug was corrected (SLU-PP-332 typo fix).",
      "tags": [
        "catalog",
        "woocommerce",
        "content"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-17",
      "title": "Storefront search (FiboSearch) restyle — dark/gold theme fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Fixed the storefront search dropdown: suggestions were white-text-on-white-hover (invisible on hover), border/background were bulky, and it required 3 keystrokes before showing results. Restyled to match the site's real dark/gold/burgundy brand (correcting an old brain assumption that the brand was blue) — config-only change via wp eval, no deploy needed. Also reduced min_chars to 2.",
      "tags": [
        "storefront",
        "search",
        "styling",
        "wp-config"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-17",
      "title": "Shipping label-status vocab fix + Hide-visible-OOS action",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.32.8",
      "summary": "Fixed the Fulfill/ready-to-ship queue miscounting labeled orders as needing labels (only counted 'success' status, but the real label flow never writes it) by introducing a shared ACTIVE_LABEL_STATUSES vocabulary applied across the filter, daily digest, and both idempotency checks. Also shipped a one-click 'Hide visible OOS' inventory action. Live-verified: ready-to-ship dropped from ~20 false positives to the real count of 2.",
      "tags": [
        "cc2",
        "shipping",
        "inventory",
        "bugfix"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-20",
      "title": "HUB commission-status fix — 'unpaid' enum dropped from totals",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.3 (untagged)",
      "summary": "Fixed a bug where the 'unpaid' commission status enum was being dropped from earnings totals and the filter enum in the affiliate HUB, understating what affiliates were owed. This commit exists in the repo history but was never given its own git tag.",
      "tags": [
        "hub",
        "affiliate",
        "bugfix",
        "untagged"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-22",
      "title": "HUB earnings status filter + payouts fallback + orders enum fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.5 (untagged)",
      "summary": "Fixed the hub-wide earnings status filter, added a payouts-table fallback (falls back to commissions data when the payouts table is unavailable), and corrected the orders status enum. Like v0.3.3, this commit was never tagged in git.",
      "tags": [
        "hub",
        "affiliate",
        "bugfix",
        "untagged"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-24",
      "title": "PNP ecosystem deep audit + CC2 v0.5.34.0 / HUB v0.3.5 deploy + 6 retroactive tags",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.34.0",
      "summary": "Full read-only audit surfaced that CC2 develop had 23 untracked WIP files for Revenue Intelligence sitting loose, and that both CC2 prod and HUB prod had drifted ahead of GitHub. Snapshotted the WIP to a branch, deployed the (already-current) v0.5.34.0 plugin plus a stale proxy bundle, deployed HUB v0.3.5 to sync a missing analytics-tracker commit, and pushed 6 retroactive git tags (v0.5.32.6–v0.5.34.0) closing a tagging gap.",
      "tags": [
        "cc2",
        "hub",
        "audit",
        "deploy",
        "git-hygiene"
      ],
      "hours": 6
    },
    {
      "date": "2026-06-25",
      "title": "Revenue Intelligence dashboard — 6-view analytics suite",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.36.0",
      "summary": "Finished and shipped the Revenue Intelligence feature: 2 REST controllers, a daily insights cron, and a 6-tab UI with custom SVG charts (overview, products, channels, customers, forecast, insights). Fixed 4 real accuracy bugs during validation: product names were rendering as numeric IDs, affiliate-channel revenue was undercounted 8x by using commission totals as a proxy instead of full order value, a customer-cohort query had an N+1 timeout risk, and the forecast was biased by including the current partial month. Live-verified affiliate revenue corrected from ~4% to ~30% of gross.",
      "tags": [
        "cc2",
        "analytics",
        "revenue",
        "feature"
      ],
      "hours": 6
    },
    {
      "date": "2026-06-26",
      "title": "View label everywhere — Fulfill page + order drawer",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.36.1",
      "summary": "Added a direct 'View label' button to every labeled order on the Orders-to-Ship page and the order detail drawer, reusing the audited print-token mint so labels display inline in-browser instead of only being viewable from the separate Labels-folder page.",
      "tags": [
        "cc2",
        "shipping",
        "ux"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-26",
      "title": "View label mobile fix — direct label_url instead of token-mint dance",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.36.2",
      "summary": "The v0.5.36.1 View label button didn't open on mobile because its token-mint-then-redirect approach gets blocked by mobile browsers. Fixed by returning label_url directly from the shipping-orders endpoint and switching the frontend to a plain window.open, matching the already-working Labels-folder Download button's mechanism. This release also lived uncommitted on prod for days before being caught and committed as part of a later git-drift cleanup session.",
      "tags": [
        "cc2",
        "shipping",
        "bugfix",
        "mobile"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-26",
      "title": "debug.log AJAX-leak root-cause fix + 1.6GB reclaimed",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Root-caused PHP notices leaking into admin-ajax.php JSON responses: the pnp-suppress-frontend-errors mu-plugin only suppressed display when !is_admin(), but admin-ajax.php makes is_admin() true even for public/frontend AJAX calls. Patched to also treat AJAX as frontend (v2.1), then added a doing_it_wrong_trigger_error filter to kill the noisy _load_textdomain_just_in_time notice at its source (v2.2). Also found and removed a left-in per-request diagnostic block in the live-only pnp-elite-leaders plugin that was force-setting display_errors=1 and error_reporting(E_ALL) on every single request. Truncated debug.log (1.1GB→0) and deleted a 537MB debug.log.old, reclaiming ~1.6GB.",
      "tags": [
        "wp-config",
        "debug",
        "bugfix",
        "infra"
      ],
      "hours": 4
    },
    {
      "date": "2026-06-26",
      "title": "Git↔prod drift closed (v0.5.36.2) + stale backlog verified-resolved",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Committed the v0.5.36.2 hotfix that had been living uncommitted on prod, tagged and pushed it, closing a repo-misrepresents-production gap. Verified two other backlog items were already resolved and struck them: the ia.ts '?query' router bug (already fixed in committed code) and the '13 dead one-off fix plugins' cleanup (all already gone from disk, none needed deleting).",
      "tags": [
        "git-hygiene",
        "verification",
        "ops"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-27",
      "title": "Branch hygiene — 29 stale CC2 branches pruned",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Full audit and prune of CC2's remote+local branches: deleted 10 ancestry-merged branches, then git-cherry-audited 19 more, proving 16 were patch-equivalent (safe to delete) and 3 were superseded old snapshots whose features already existed expanded in develop. CC2 went from 31 remote branches down to just develop + main, with restore SHAs logged in case any pruned branch is ever needed back.",
      "tags": [
        "git-hygiene",
        "ops"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-27",
      "title": "Phase 7 WPCode snippet inventory (read-only discovery)",
      "type": "research",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Read-only inventory of the WPCode Lite snippet layer as the gating prerequisite for the v0.6.0.0 legacy cutover: found 117 total snippet posts, 26 active (18 PHP + 7 CSS + 1 trivial) — not the 10 the old backlog assumed. Mapped each active PHP snippet to its likely overlapping plugin and identified 2 slam-dunk safe-retire candidates (redundant error-suppression snippet, duplicate 'Hide Zero Activity' snippets). No prod changes made.",
      "tags": [
        "wpcode",
        "audit",
        "legacy-cutover",
        "research"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-27",
      "title": "Email tab ease-of-use — insert-block palette + send-test-to-me (PR #98)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "PR #98 (folded into v0.5.37.1)",
      "summary": "Shipped an insert-block palette to the email template editor (11 prebuilt on-brand blocks: heading/paragraph/button/coupon/image/product-card/columns/divider/spacer/footer) and wired the already-built-but-unwired write/email-test-send endpoint into both the editor footer and the broadcast preview step as 'Send test to me'. Frontend-only, no DB change. Sat as an unmerged PR for 5 days before its rebuilt bundle was finally committed and deployed as part of v0.5.37.1.",
      "tags": [
        "cc2",
        "email",
        "ux"
      ],
      "hours": 4
    },
    {
      "date": "2026-06-28",
      "title": "A3 affiliate cutover — /affiliate-account/ → /my-affiliate/",
      "type": "infra",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Made the modern HUB dashboard the affiliate front door: new mu-plugin 301-redirects the legacy /affiliate-account/ page to /my-affiliate/ (GET-only guard so login POSTs aren't mangled), repointed SliceWP's internal account-link setting, and retargeted the nav menu item URL directly. Single change covers the nav item, all Elementor button links, and bookmarks. Fully reversible.",
      "tags": [
        "affiliate",
        "cutover",
        "redirect",
        "infra"
      ],
      "hours": 3
    },
    {
      "date": "2026-06-28",
      "title": "HUB FAQ expansion (6→10) + QR code verification",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Expanded the affiliate HUB FAQ from 6 to 10 real entries (payout timing, commission-rate tiers, team overrides, 'where's my stuff'). Also proved the previously-flagged 'blank QR in preview' was only a preview-harness artifact, not a real bug — the QR encoder works correctly in production.",
      "tags": [
        "hub",
        "content",
        "faq"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-28",
      "title": "HUB v0.3.6 — LiteSpeed doctor false-negative fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.6",
      "summary": "Fixed the HUB doctor's LiteSpeed cache-exclusion check reporting a false negative: the setting is stored as a JSON string (not array) with escaped slashes, so the substring match failed on the API path. Normalized escaped slashes before matching. Also refreshed the README with the real 6-tab list and current CLI commands.",
      "tags": [
        "hub",
        "bugfix",
        "litespeed"
      ],
      "hours": 2
    },
    {
      "date": "2026-06-29",
      "title": "HUB v0.3.7 — Earn-tab CSS fix, broken Apply link, balance widget, recruiting link",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.3.7",
      "summary": "Fixed the Earn tab rendering as raw bulleted lists because its leaderboard/tier-stepper/team CSS classes were never actually defined in hub.css (hit elites hardest since tier+team is their whole dashboard). Also fixed a 404'ing elite-application link in two places, added a 'YOUR BALANCE' payout-clarity widget to Home (owed/pending/paid, minimum, hold period), and a one-tap 'copy your recruiting link' for elite team leads.",
      "tags": [
        "hub",
        "bugfix",
        "css",
        "ux"
      ],
      "hours": 6
    },
    {
      "date": "2026-07-02",
      "title": "Affiliate + credits system audit (read-only)",
      "type": "research",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Read-only audit of the full affiliate/credits system verified attribution was fair, but surfaced a dual-ledger double-pay risk (every sale credited in both wp_slicewp_commissions and wp_pnp_commissions, with pending payout batches that could double-pay if ever processed), a dead-on-arrival affiliate credit-rewards engine (listening for the wrong hook, filtering on the wrong status value), unused-but-built customer credits, and an inconsistent credit-to-dollar value across systems. No writes made — all fixes queued for Clayton's decision.",
      "tags": [
        "affiliate",
        "credits",
        "audit",
        "financial"
      ],
      "hours": 4
    },
    {
      "date": "2026-07-02",
      "title": "Affiliate fixes executed — payout-batch void + drip credits live (elite-leaders v3.2.0)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "elite-leaders v3.2.0",
      "summary": "Voided the 2 pending double-pay-risk payout batches and gated the auto-batch cron off (SliceWP via CC2 mark-paid is now the single payout source of truth). Rewired the credit-rewards engine to the hook that actually fires and fixed a status-value bug that was silently zeroing out all leader-eligible crons; first run issued 1,466 credits across 7 affiliates, verified idempotent on a second run.",
      "tags": [
        "affiliate",
        "credits",
        "bugfix",
        "financial"
      ],
      "hours": 5
    },
    {
      "date": "2026-07-02",
      "title": "Credit system relaunch — final economics + product-spend wiring + HUB display",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "elite-leaders v3.2.0 / peptide-credits-live v1.1.0 / HUB v0.4.0",
      "summary": "Locked in final credit economics (1 credit = $0.20 cash / $1.00 product, cash-out at 1,000cr=$200 with admin approval, all affiliates earn 1cr/$10 referred sales), reset all balances to zero with history preserved, and wired 1:1 product-spend at checkout (FIFO customer credits then affiliate ledger, 50% subtotal cap). Shipped HUB v0.4.0 with a /me.credits endpoint and a Peptide Credits Home card, generated a QR kit for all 36 active affiliates, and drafted (then Clayton-approved and sent) a 34/34 broadcast announcing credits plus the July 4th sale.",
      "tags": [
        "affiliate",
        "credits",
        "hub",
        "broadcast"
      ],
      "hours": 6
    },
    {
      "date": "2026-07-02",
      "title": "Credit hardening — auto-restore on cancel/fail/refund (peptide-credits-live v1.2.0)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "peptide-credits-live v1.2.0",
      "summary": "Closed a real-money gap: checkout-time credit deduction now acts as a reservation and auto-restores on order cancelled/failed/fully-refunded, with split-aware routing (customer portion back as a fresh peptide-credit row, affiliate portion back to the ledger), fully idempotent. Verified with a synthetic round-trip test on prod, then cleaned up.",
      "tags": [
        "affiliate",
        "credits",
        "bugfix",
        "financial"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "Andrew Thompson order reattribution",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Reattributed a $178.69 order that had zero commissions (no coupon/cookie at checkout) to affiliate Andrew Thompson via CC2's audited preview→commit reattribution flow at his elite-leader 15% rate, matching a nearby already-attributed order from the same customer.",
      "tags": [
        "affiliate",
        "reattribution",
        "commissions"
      ],
      "hours": 1
    },
    {
      "date": "2026-07-02",
      "title": "Affiliate coupons stack with July 4th sale (pnp-july4-b2g1 v1.5.0)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.5.0",
      "summary": "Let affiliate discount codes apply on top of the July 4th sale (both discounts compute additively on the undiscounted subtotal) while continuing to block all other/non-affiliate coupons. Live-proven both directions in a real cart: an affiliate code stacked correctly, a non-affiliate test coupon was blocked with the new explanatory message.",
      "tags": [
        "affiliate",
        "coupons",
        "sale"
      ],
      "hours": 2
    },
    {
      "date": "2026-07-02",
      "title": "CC2 v0.5.37.1 — HPOS sales-aggregate fix + v0.5.37.0 email bundle finally deployed",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.37.1",
      "summary": "Fixed a recurring debug.log error where the HPOS net-sales fallback query referenced shipping columns that don't exist on wp_wc_orders (HPOS keeps shipping in wp_wc_order_operational_data), which had been silently erroring on every 'today' Overview window before the day's first order synced to analytics. Also finally deployed the v0.5.37.0 email-tab bundle (PR #98) whose rebuilt assets had sat uncommitted for 5 days. Formula validated against wc_order_stats.net_total on 12 sampled orders before shipping.",
      "tags": [
        "cc2",
        "hpos",
        "revenue",
        "bugfix"
      ],
      "hours": 4
    },
    {
      "date": "2026-07-02",
      "title": "Email test-send allowlist wired live",
      "type": "infra",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Set PNP_CC2_TEST_SEND_ALLOWLIST in prod wp-config.php, discovering the endpoint checks the requester's WP user_email and that the CC2 proxy's fallback identity is the lowest-ID administrator, not Clayton's own WP user. Verified live end-to-end (200 send as the allowlisted proxy identity, 403 refusal for a non-allowlisted admin).",
      "tags": [
        "cc2",
        "email",
        "wp-config"
      ],
      "hours": 1
    },
    {
      "date": "2026-07-02",
      "title": "HUB v0.4.1 — 'Cookie check failed' logged-out fix + full endpoint sweep",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.4.1",
      "summary": "Fixed a broken-dashboard bug hitting every affiliate whose 14-day login had expired (a common case right after a 34-recipient broadcast drove traffic): hub.js was unconditionally wiping the server's logged-out sign-in gate and firing REST calls with an empty nonce, producing a raw 'Cookie check failed' error. Added a boot guard, a session self-heal via a new admin-ajax nonce-refresh endpoint with one retry, a friendly session-expired banner, and fixed the Logout menu item (had always pointed at '#'). Swept every registered HUB REST route as both a regular and elite affiliate — all 200.",
      "tags": [
        "hub",
        "bugfix",
        "auth",
        "affiliate"
      ],
      "hours": 4
    },
    {
      "date": "2026-07-02",
      "title": "HUB v0.4.2 — credits card full breakdown",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.4.2",
      "summary": "Upgraded the HUB credits card into labeled Spend/Earn/Cash-out/Expiry rows explaining the mechanics in plain language, and added 3 new credit-related FAQ entries (now 13 total), per Clayton's ask for clearer credit explanation.",
      "tags": [
        "hub",
        "credits",
        "content",
        "ux"
      ],
      "hours": 1
    },
    {
      "date": "2026-07-02",
      "title": "July 4th B2G1 sale — launch (pnp-july4-b2g1 v1.0.0)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.0.0",
      "summary": "Launched a new live-only plugin implementing a Buy-2-Get-1-Free mechanic (cheapest unit free) as a negative taxable cart fee across 9 eligible products, staging-tested (8/8) before going to prod (8/8), with a product-page badge, classic-cart nudge, kill switch, and a site-wide banner via the existing promos-center system.",
      "tags": [
        "sale",
        "promo",
        "b2g1",
        "new-plugin"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "July 4th sale v1.1.0 — single guarded banner + popup + noon end + coupon exclusivity",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.1.0",
      "summary": "Fixed a duplicate-banner bug (promos-center was double-injecting its own script), replaced it with the plugin's own single guarded sticky banner and a 'Learn more' details popup, moved the sale end-time to noon on July 6, and added two-way coupon exclusivity (blocks other coupons on qualifying carts, and vice-versa) with a clear cart notice explaining the tradeoff.",
      "tags": [
        "sale",
        "promo",
        "banner",
        "coupons"
      ],
      "hours": 2
    },
    {
      "date": "2026-07-02",
      "title": "Catalog prices +10% (64 products)",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Applied a store-wide +10% price increase across 64 product/variation changes, rounded to the nearest even dollar, with full rollback CSVs saved. Tesamorelin and BAC Water were excluded per Clayton's explicit mid-session call.",
      "tags": [
        "catalog",
        "pricing",
        "content"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "Logo redraw — shrink + vector redraw (deep-metallic gradient)",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Shrunk the header logo 290px→203px, then replaced a rejected raster-cleanup attempt with a real vector redraw (potraced from the actual mark, 3-band structure with a deep-metallic gradient Clayton picked from options). Had to deploy as a brand-new media attachment because Hostinger's CDN caches static files by URL and won't serve updated bytes at the same path.",
      "tags": [
        "branding",
        "logo",
        "content",
        "design"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "Mobile header fixes — logo visibility + popup contrast (rounds 4–5)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Fixed the mobile/tablet logo being nearly fully hidden under the search bar (an Elementor container margin-top bug) via append-only Customizer CSS, fixed a white-on-white sale popup title, and tightened the mobile banner. This was the necessary lead-in to the full single-line mobile header rebuild that followed the same day.",
      "tags": [
        "mobile",
        "bugfix",
        "css",
        "elementor"
      ],
      "hours": 2
    },
    {
      "date": "2026-07-02",
      "title": "Mobile header rebuild — single line (logo | search | menu | cart)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Rebuilt the mobile header into a clean single line via a new mu-plugin (pnp-mobile-header-row.php) after discovering CSS-only overrides were structurally impossible against Elementor's layered !important widget-width rules. Uses JS DOM-moves of each widget's inner container into a new flex row with its own gold hamburger menu (cloning the site's real nav links), with a stacked-layout CSS fallback preserved for no-JS. Live-verified at 390px on both homepage and a product page.",
      "tags": [
        "mobile",
        "header",
        "new-plugin",
        "elementor"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "Shop-grid badges + button alignment + BPC/TB joins sale (v1.2.0)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.2.0",
      "summary": "Added stacked SALE/B2G1 corner badge chips to eligible product cards on the shop grid, fixed misaligned add-to-cart buttons on mobile via Customizer CSS, and added the BPC/TB 10/10 blend as a 10th B2G1-eligible product per Clayton's follow-up ask.",
      "tags": [
        "sale",
        "grid",
        "badges",
        "css"
      ],
      "hours": 2
    },
    {
      "date": "2026-07-02",
      "title": "30% OFF storewide tier (v1.3.0) + 20% Best-Sellers tier (v1.4.0)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "pnp-july4-b2g1 v1.3.0–v1.4.0",
      "summary": "Extended the July 4th sale into a three-tier structure: 30% off everything not already in B2G1 (a second disjoint negative taxable fee, non-stackable with B2G1 by construction), then a category-driven 20% Best-Sellers tier layered in on top for GHK-Cu and CJC-1295+Ipa. All tiers share the same coupon-exclusivity, kill switch, and end time; banner/popup/product badges updated to reflect all three tiers.",
      "tags": [
        "sale",
        "promo",
        "pricing-tiers"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-02",
      "title": "Override mirror shipped — leader team-pay finally real (elite-leaders v3.3.0)",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "version": "elite-leaders v3.3.0",
      "summary": "Closed the last money-correctness item from the day's audit: leader L1/L2 override commissions (5%/2%) had only ever accrued in a ledger nobody actually pays from. Built a new mirroring engine that inserts overrides into wp_slicewp_commissions (the real payout source of truth via CC2 mark-paid), built with a 3-agent recon→implement→adversarial-review pipeline that caught a strict-mode NOT-NULL landmine before deploy. Full E2E-tested on a synthetic prod order before shipping.",
      "tags": [
        "affiliate",
        "commissions",
        "financial",
        "override"
      ],
      "hours": 6
    },
    {
      "date": "2026-07-03",
      "title": "Calendar tab overhaul — full audit + rebuild (branch, not yet deployed)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Deep audit found the Calendar tab was substantially broken: Approve & send always 400'd, recurring events were unusable from the UI, recurrence silently died after 30 days, all displayed times were shifted by the timezone offset, approval emails could stack duplicates hourly, and skipped events retried forever. Built a native RRULE engine, fixed the whole tick state machine, and rebuilt the frontend (edit flow, repeat control, removed the broken week view). Landed on a branch awaiting Clayton's go-ahead before deploy.",
      "tags": [
        "cc2",
        "calendar",
        "bugfix",
        "rrule"
      ],
      "hours": 5
    },
    {
      "date": "2026-07-03",
      "title": "Calendar tab overhaul — DEPLOYED + prod E2E verified",
      "type": "deploy",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.38.0",
      "summary": "Clayton green-lit the calendar overhaul branch; deployed to prod with all 10 checks green after discovering and fixing a WP plugin-header gotcha (WP only reads the first 8KB, so the Version field must sit above the changelog Description). Full prod E2E via real REST covered create/edit/invalid-input/recurring-advance/approval-parking, confirming the fixed tick state machine actually works live: zero emails sent for a parked above-threshold event, zero duplicate runs on a second tick.",
      "tags": [
        "cc2",
        "calendar",
        "deploy"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-03",
      "title": "Note/Reminder calendar event type",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.38.1",
      "summary": "Added a plain no-action Note/Reminder event type so managers can put trackable entries on the shared calendar without triggering any store action; registered first so the Add-event wizard defaults to the safest type. Prod E2E verified same day.",
      "tags": [
        "cc2",
        "calendar",
        "feature"
      ],
      "hours": 1
    },
    {
      "date": "2026-07-03",
      "title": "CC2 full condition sweep — confirmed healthy",
      "type": "ops",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "End-of-session full prod sweep confirmed every live REST endpoint (14 tabs plus sub-routes) returns 200, calendar tables clean of test data, cron schedules correct, and git fully synced (develop==prod, tags pushed, repo down to develop+main only).",
      "tags": [
        "cc2",
        "verification",
        "ops"
      ],
      "hours": 2
    },
    {
      "date": "2026-07-04",
      "title": "CC2 v0.5.38.2 — UTC display sweep + full close-out audit",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.38.2",
      "summary": "Centralized the calendar tab's local UTC-display fix into the shared date formatters used across the whole app (Email Ops, Email Stats, Actions, Today, Labels Folder, Email Templates, order-drawer email rows), fixing every remaining tab that displayed raw plugin-owned UTC timestamps as if they were local time. Ran a full two-agent audit (backend + frontend) where every other loud 'P0/P1' finding was proven false before acting — including one that would have introduced a real bug (SliceWP's local-time convention would have been broken by a naive 'fix'). Declared CC2 functionally complete and bug-free per Clayton's 'finish it' directive.",
      "tags": [
        "cc2",
        "bugfix",
        "timezone",
        "audit"
      ],
      "hours": 4
    },
    {
      "date": "2026-07-05",
      "title": "CC2 v0.5.39.0 — SMS console + Customer Contact Library",
      "type": "feature",
      "tool": "codex",
      "status": "shipped",
      "version": "v0.5.39.0",
      "summary": "Built a new Customer Contact Library (auto-captured at every checkout, deduplicated, with a searchable/filterable Contacts tab) and a fully fail-safe SMS console (compose/templates/log/settings) that can never send a real text — no provider configured, gate closed by default, the single transport chokepoint logs 'blocked' instead of calling any network. DB migrated 8→9 via the new deploy.sh --release lane (built specifically for this schema change). Caught a real pre-deploy bug where the version constants hadn't actually updated due to a prior failed edit, which would have shipped the feature without its database tables.",
      "tags": [
        "cc2",
        "sms",
        "contacts",
        "feature",
        "db-migration"
      ],
      "hours": 6
    },
    {
      "date": "2026-07-05",
      "title": "CC2 v0.5.39.1 — Alerts + Email Ops schema-drift fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.39.1 (untagged)",
      "summary": "Fixed both the Alerts and Email Ops REST queries, which had been silently 500ing on every request since 2026-06-27 because they referenced columns that don't exist on wp_pnp_fraud_alerts / wp_pnp_email_log. Real impact: the Today page's Active Alerts widget always showed 'No active alerts' regardless of real fraud alerts. Notably, a prior 07-04 audit had concluded 'no drift in code' for this exact item — that conclusion was wrong, and only reading the live debug.log (not just the code) proved the drift was real. No git tag exists for this release; DB_VERSION stayed at 9.",
      "tags": [
        "cc2",
        "bugfix",
        "schema-drift",
        "untagged"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-05",
      "title": "CC2 v0.5.39.2 — Bonuses + Credits write-path repair",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.39.2 (untagged)",
      "summary": "Fixed two silently-broken write paths: the Bonuses tab's Approve button called an entirely wrong endpoint (always 400'd) against the wrong table/columns, and the Credits tab's 'Issue credit' had silently no-op'd since inception — it targeted a balance column that never existed on the real per-transaction ledger table, while still returning saved:true. Rebuilt both against the real schema and verified end-to-end live by issuing a real $200 credit to a real affiliate and confirming it in both the database and the REST response. No git tag exists for this release; DB_VERSION stayed at 9.",
      "tags": [
        "cc2",
        "bugfix",
        "financial",
        "untagged"
      ],
      "hours": 4
    },
    {
      "date": "2026-07-05",
      "title": "pnp-affiliate-hub v0.4.3 — slicewp_affiliate_meta column fix",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "HUB v0.4.3",
      "summary": "Fixed 11 read-only lookups across 9 controller files that had been erroring 26-46x/day since 07-02 due to a wrong column name (affiliate_id vs the real slicewp_affiliate_id). The more severe companion bug: the affiliate's own 'save payment email' self-service action had the same wrong column as a write key, meaning payment-email changes had been silently failing to persist while reporting success. Also fixed an unrelated alias bug in the Landing Pages controller.",
      "tags": [
        "hub",
        "bugfix",
        "financial",
        "affiliate"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-05",
      "title": "25-affiliate 5% coupon rollout + broadcast",
      "type": "affiliate",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Generated plain LASTNAME5-style personal coupon codes for the 25 affiliates who didn't already have one (8 already had codes from an earlier rollout; Samantha excluded per Clayton since she already has SAM10), all correctly linked via the standard attribution meta pattern. Sent 24 personalized onboarding emails (Clayton excluded himself from the send only) using the newly-fixed Credits write path and Email Ops logging as verification.",
      "tags": [
        "affiliate",
        "coupons",
        "broadcast"
      ],
      "hours": 3
    },
    {
      "date": "2026-07-06",
      "title": "COGS + Realized P&L engine — first true profit/margin visibility",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.40.0 → v0.5.40.1",
      "summary": "Built a new COGS tab from scratch: per-product real cost (supplier price/vial + shipping + fees) vs Woo retail → live gross margin, sourced from Clayton's supplier pricing workbook (132+125 supplier rows). Deployed live, verified against the real store catalog (58/67 then 67/67 products costed after fixing a variation-name automap bug). Then built a Realized P&L view joining every paid order since 2026-03-08 (206 orders, 367 line items) to real per-product cost — the store's first-ever true profit number instead of a revenue-only view.",
      "hours": 10,
      "tags": [
        "cc2",
        "cogs",
        "revenue",
        "margin",
        "feature"
      ]
    },
    {
      "date": "2026-07-06",
      "title": "Affiliate commission accounting folded into P&L (v0.5.40.3)",
      "type": "feature",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.40.3",
      "summary": "Per Clayton's ask to 'correctly count all affiliate revenue and what we're paying them': pulled every SliceWP commission (paid+unpaid+pending) into the realized P&L as a real cost line, plus new KPIs for affiliate-driven vs organic revenue and effective commission rate. Surfaced $1,752 in affiliate costs that were previously invisible to the profit picture. Deployed live same day.",
      "hours": 3,
      "tags": [
        "cc2",
        "cogs",
        "affiliate",
        "revenue",
        "financial"
      ]
    },
    {
      "date": "2026-07-06",
      "title": "Shipping label cost capture fix + 48-label backfill (v0.5.40.1–v0.5.40.2)",
      "type": "bugfix",
      "tool": "claude-code",
      "status": "shipped",
      "version": "v0.5.40.1–v0.5.40.2",
      "summary": "Every shipping label had recorded $0.00 real cost since inception — Shippo's API returns the purchased rate as a string ID, not an inlined object, so the cost field never populated. Fixed the read path and backfilled real costs onto all 40 purchased labels ($293.35 total, avg $7.33/label), which the new COGS/P&L engine now uses as the real per-order shipping cost instead of an estimated default. Survived a same-day deploy race with a parallel session (both recovered cleanly, no prod fatal).",
      "hours": 4,
      "tags": [
        "cc2",
        "shipping",
        "shippo",
        "bugfix",
        "revenue"
      ]
    },
    {
      "date": "2026-07-06",
      "title": "Thymalin 10mg — new product launch (image + listing + costed live)",
      "type": "content",
      "tool": "claude-code",
      "status": "shipped",
      "summary": "Took a new SKU from zero to fully live in one pass: built an on-brand product image (not AI-generated — real vial photo with the label text swapped via pixel-level inpainting, matched to the site's actual font), created the Woo listing ($55 retail, Recovery & Inflammation category, stock-tracked), and mapped it into the new COGS engine ($14/vial cost → 74.5% margin / 3.93× markup). Verified purchasable live end to end same day.",
      "hours": 2,
      "tags": [
        "catalog",
        "new-product",
        "content",
        "cogs"
      ]
    }
  ],
  "open_items": [
    {
      "title": "Phase 7 — retire dual-firing WPCode snippets",
      "priority": "medium",
      "status": "in-progress",
      "now": true,
      "note": "Inventory done (26 active snippets: 18 PHP / 7 CSS / 1 trivial). Next: per-snippet dual-fire proof → staging deactivation → prod retirement. HIGH RISK, staging first."
    },
    {
      "title": "pnp-elite-leaders tier-decay cron fix",
      "priority": "high",
      "status": "plan-ready — awaiting go",
      "now": false,
      "note": "reference_amount → order_total rename (5 files) + mute tier-change notifications during catch-up recalc. Erroring 12×/day since 06-27, silently zeroing tier-decay math. Live-only plugin, no repo — fully specified, needs Clayton's final go to execute."
    },
    {
      "title": "Verify coupon-affiliate commission rates",
      "priority": "high",
      "status": "blocked on Clayton/SSH",
      "now": false,
      "note": "Reported live rates: elite=15% / regular=13%, base after all discounts. No git trace (live-only plugin, no repo) and no SSH/wp-cli reach — needs Clayton to confirm live rates directly or authorize SSH before this is written as brain-truth."
    },
    {
      "title": "Wire an SMS provider",
      "priority": "medium",
      "status": "blocked on provider choice",
      "now": false,
      "note": "SMS console shipped (v0.5.39.0) but no provider configured — zero texts sendable until one is added. Needs Clayton to pick a provider (Twilio, etc.)."
    },
    {
      "title": "v0.6.0.0 — legacy cutover",
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
      "note": "HUB creatives gallery empty — needs real brand assets from Clayton (no AI-slop, per standing rule)."
    },
    {
      "title": "debug.log rotation",
      "priority": "low",
      "status": "deferred",
      "now": false,
      "note": "1.1GB of benign notices — needs truncate/rotate. No blocker, just not prioritized."
    },
    {
      "title": "Real Stripe payments",
      "priority": "low",
      "status": "future",
      "now": false,
      "note": "Zelle/Venmo manual verify is the current real flow. Not started."
    }
  ],
  "revenue_impact": {
    "snapshot_date": "2026-07-06",
    "snapshot_note": "First real, all-time, fully-costed P&L for the store, produced by the new COGS/P&L engine shipped today (v0.5.40.0→v0.5.40.3). Covers every paid order since 2026-03-08 (store's order history to date). These are ACTUAL measured figures from the live database, not estimates.",
    "snapshot": {
      "revenue": 34088.1,
      "orders": 206,
      "units": 553,
      "aov": 165.48,
      "cogs_product": 11677.43,
      "cogs_shipping": 1509.98,
      "cogs_affiliate": 1752.01,
      "cogs_total": 14939.42,
      "gross_profit": 19148.68,
      "gross_margin_pct": 56.2,
      "affiliate_driven_revenue": 12547.95,
      "affiliate_driven_pct": 36.5,
      "organic_revenue": 21630.15,
      "commissions_paid": 953.76,
      "commissions_owed": 798.25,
      "effective_commission_rate_pct": 14.1
    },
    "items": [
      {
        "system": "COGS + Realized P&L Engine",
        "impact": "Gave Clayton the first true profit number the store has ever had: 56.2% real gross margin (not the ~65-79% product-only margin previously assumed) after correctly subtracting real shipping and affiliate costs. This is the foundation for every pricing, promo, and product-mix decision going forward — margin-blind decisions become margin-informed ones."
      },
      {
        "system": "Affiliate / HUB program",
        "impact": "Drives $12,547.95 — 36.5% of all revenue — through 36 active affiliates at a 14.1% effective commission rate. The recruiting, team-override, and tier engines exist specifically to grow this channel; every HUB bugfix this cycle (cookie/auth fixes, balance visibility, payout clarity) directly protects affiliate retention and therefore this revenue share."
      },
      {
        "system": "Credit / loyalty economy",
        "impact": "1 credit per $10 referred sale (earn) redeemable 1:1 at checkout (spend) — a repeat-purchase and referral incentive layered on top of the affiliate program, live for all affiliates since 2026-07-02."
      },
      {
        "system": "July 4th sale engine (B2G1 + tiered %-off)",
        "impact": "Reusable promotional infrastructure (negative-fee cart mechanics, coupon exclusivity, kill switch, banner/popup system) that drove a multi-week storewide promotion — the same engine can be re-triggered for future sales without rebuilding it."
      },
      {
        "system": "Coupon / re-attribution engine",
        "impact": "Protects revenue integrity rather than growing it directly: ensures affiliate commissions attribute to the right person (prevents payout disputes that erode affiliate trust) and closed a dual-ledger double-pay risk that could have cost real money if a payout batch had ever processed unchecked."
      },
      {
        "system": "Shipping automation + real cost capture",
        "impact": "Cut manual label-creation overhead (auto-create, print-auth, tracking webhooks) and, as of today's fix, feeds real per-shipment cost ($7.33 avg) into the P&L instead of a guess — the margin number is only as trustworthy as this input, and now it's real."
      },
      {
        "system": "Revenue Intelligence dashboard",
        "impact": "6-view analytics suite (overview, products, channels, customers, forecast, insights) giving visibility into where revenue is actually coming from — corrected affiliate-channel revenue from an undercounted ~4% to the real ~30%+ of gross during its own build."
      },
      {
        "system": "New-product launch pipeline",
        "impact": "The Thymalin launch (image → listing → cost-mapped → purchasable) took hours, not days, proving a repeatable process for adding new SKUs — directly shortens time-to-revenue on every future product add."
      },
      {
        "system": "Mobile header + storefront UX fixes",
        "impact": "Conversion-protecting rather than growth-driving: the mobile header was actively broken (logo clipped, unusable single-line nav) before the fix — on a peptide DTC store, mobile traffic share is typically majority, so this was suppressing checkout completion, not just cosmetics."
      },
      {
        "system": "Catalog pricing (+10% raise, 64 products)",
        "impact": "Direct realized revenue increase — a storewide price adjustment applied with rollback safety, now measurable against real margin data via the COGS engine rather than gut-feel."
      }
    ]
  }
};
