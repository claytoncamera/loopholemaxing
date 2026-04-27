# tests/

Static + lightweight behavioural validation for the public BTC Intelligence
Brain. There is no JS test framework wired into the repo (the site is shipped
as raw HTML on GitHub Pages), so these checks are intentionally framework-free.

## Run all

```
bash tests/run-all.sh
```

## What each check covers

| File | Covers |
|------|--------|
| `btc-brain-truth-scan.sh` | (a) no synthetic OHLC fabrication; (b) no fabricated CoinGecko high/low/open; (c) closed-candle helper present; (d) public disclaimer banner present; (e) no unrelabeled accuracy/IQ/analog-match claims; (f) feed-failure copy present |
| `secret-scan.sh` | Token-shape patterns (AWS/Stripe/Slack/GitHub PAT/Google API/JWT/PEM) across the public bundle, plus `.env` not tracked. Prints only file paths and pattern names — never secret values. |
| `closed-candles.spec.mjs` | Behavioural unit test of the `closedCandlesOnly` helper (Node only). |

## Manual test plan

The checks above cover what static grep can verify. The following must be
exercised in a browser before each release:

1. **No-feed state** — block `api.binance.com` in DevTools network tab and
   block `api.coingecko.com`. The Live Market section must show:
   - `live-status` text containing "Feed unavailable" or "OHLC unavailable"
   - `live-dot` background `#f85149` or `#d29922`
   - TF matrix showing all rows as `STALE` / `N/A`
   - No fabricated bullish/bearish bias
2. **Partial-feed state** — block only `api.binance.com`. CoinGecko ticker
   should populate price and 24h change. High/Low/Volume must show
   `— (unavailable)`. TF matrix must still be `STALE`.
3. **Closed-candle parity** — with a live Binance feed, confirm the rightmost
   live candle does NOT alter RSI/EMA snapshots between two consecutive
   ticks within the same hour (visual sanity check on the indicator panel).
4. **Disclaimer visibility** — the orange disclaimer banner is visible above
   every chapter without scrolling.
5. **Public bundle build** — `bash tests/secret-scan.sh` returns clean. If
   any pattern matches, rotate the credential immediately and never commit
   the diff.
