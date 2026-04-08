#!/usr/bin/env python3
"""
BTC Brain Automation Engine
============================
Production-grade daily intelligence runner.
Fetches live BTC data, detects significant events,
generates a PDF alert, and sends email via Resend.

Designed to run on GitHub Actions (free) or Railway (always-on).
"""

import os, json, time, logging, smtplib, base64, sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
import urllib.request, urllib.error

# ── Configuration (loaded from environment variables) ────────────────
CONFIG = {
    # Email — Resend API
    "RESEND_API_KEY":     os.getenv("RESEND_API_KEY",    ""),
    "ALERT_EMAIL_FROM":   os.getenv("ALERT_EMAIL_FROM",  "BTC Brain <btcbrain@orbitroute.ai>"),
    "ALERT_EMAIL_TO":     os.getenv("ALERT_EMAIL_TO",    "clayton.camera@icloud.com"),

    # Thresholds for alert triggers
    "MOVE_THRESHOLD_PCT": float(os.getenv("MOVE_THRESHOLD_PCT", "3.0")),

    # Always send (useful for daily digest mode / testing)
    "ALWAYS_SEND":        os.getenv("ALWAYS_SEND", "false").lower() == "true",

    # Logging
    "LOG_DIR":            os.getenv("LOG_DIR", "logs"),
    "LOG_LEVEL":          os.getenv("LOG_LEVEL", "INFO"),
}

KEY_LEVELS = {
    "ATH (Oct 2025)":     126296,
    "200-Day MA":          89365,
    "March 2026 High":     76000,
    "20/50 MA Zone":       68600,
    "Near Support":        65000,
    "Cycle Low (Feb)":     60001,
}

# ── Logging setup ────────────────────────────────────────────────────
def setup_logging():
    log_dir = Path(CONFIG["LOG_DIR"])
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC"
    )
    logger = logging.getLogger("btcbrain")
    logger.setLevel(getattr(logging, CONFIG["LOG_LEVEL"], logging.INFO))

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Rotating file (10 MB, keep 5 backups)
    try:
        fh = RotatingFileHandler(
            log_dir / "btc_brain.log",
            maxBytes=10 * 1024 * 1024, backupCount=5
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # GitHub Actions has no persistent disk — fine to skip

    return logger

log = setup_logging()


# ── HTTP helpers with retry ──────────────────────────────────────────
def fetch_json(url: str, retries: int = 3, backoff: float = 2.0) -> dict | None:
    """Fetch JSON from URL with exponential backoff retries."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "BTC-Brain-Engine/2.0"}
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read())
                log.debug(f"  ✓ Fetched {url.split('?')[0].split('/')[-1]}")
                return data
        except urllib.error.HTTPError as e:
            log.warning(f"  HTTP {e.code} on attempt {attempt}/{retries}: {url[:60]}")
        except Exception as e:
            log.warning(f"  Attempt {attempt}/{retries} failed: {e}")
        if attempt < retries:
            wait = backoff ** attempt
            log.info(f"  Retrying in {wait:.0f}s...")
            time.sleep(wait)
    log.error(f"  ✗ All {retries} attempts failed for: {url[:80]}")
    return None


# ── Data fetching ────────────────────────────────────────────────────
def fetch_btc_data() -> dict | None:
    """
    Multi-source BTC data fetch.
    Primary:  CoinGecko (price/volume/mcap) + Kraken (OHLCV)
    Fallback: CoinGecko market chart for klines
    """
    log.info("Fetching BTC market data...")

    # ① CoinGecko — price, change, volume, market cap
    cg = fetch_json(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
        "&include_24hr_change=true"
        "&include_24hr_vol=true"
        "&include_market_cap=true"
    )
    if not cg or "bitcoin" not in cg:
        log.error("CoinGecko price fetch failed")
        return None

    btc = cg["bitcoin"]
    price  = float(btc["usd"])
    change = float(btc.get("usd_24h_change", 0))
    volume = float(btc.get("usd_24h_vol", 0))
    mcap   = float(btc.get("usd_market_cap", 0))
    log.info(f"  CoinGecko: ${price:,.2f}  {change:+.2f}%  Vol ${volume/1e9:.2f}B")

    # ② Kraken — 1h OHLCV for trend analysis
    klines_1h, klines_4h = [], []
    kr = fetch_json("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60")
    if kr and "result" in kr:
        rows = kr["result"].get("XXBTZUSD", [])
        # Each row: [time, open, high, low, close, vwap, volume, count]
        klines_1h = [[r[0], r[1], r[2], r[3], r[4], r[6]] for r in rows[-48:]]
        # Build synthetic 4H from 1H (group every 4)
        for i in range(0, len(klines_1h) - 4, 4):
            chunk = klines_1h[i:i+4]
            klines_4h.append([
                chunk[0][0],
                chunk[0][1],                               # open of first
                max(c[2] for c in chunk),                  # highest high
                min(c[3] for c in chunk),                  # lowest low
                chunk[-1][4],                              # close of last
                str(sum(float(c[5]) for c in chunk))       # total volume
            ])
        log.info(f"  Kraken: {len(klines_1h)} 1h candles → {len(klines_4h)} synthetic 4h")
    else:
        # Fallback: CoinGecko hourly chart
        log.warning("Kraken failed — falling back to CoinGecko hourly chart")
        cg2 = fetch_json(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=2&interval=hourly"
        )
        if cg2 and "prices" in cg2:
            prices = cg2["prices"]
            klines_1h = [[p[0], 0, 0, 0, str(p[1]), "0"] for p in prices]
            log.info(f"  CoinGecko chart: {len(klines_1h)} hourly data points")

    return {
        "price":     price,
        "change":    change,
        "vol_usd":   volume,
        "mcap":      mcap,
        "klines_1h": klines_1h,
        "klines_4h": klines_4h,
        "source":    "CoinGecko + Kraken",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Analysis ─────────────────────────────────────────────────────────
def analyze(data: dict) -> dict:
    """Detect significant events and compute trend."""
    price  = data["price"]
    change = data["change"]
    events = []

    # ① Large price move
    if abs(change) >= CONFIG["MOVE_THRESHOLD_PCT"]:
        direction = "UP" if change > 0 else "DOWN"
        events.append({
            "type": "LARGE_MOVE",
            "severity": "HIGH",
            "msg": f"⚡ BTC {direction} {change:+.2f}% in 24 hours",
        })

    # ② Key level breaks
    for name, level in KEY_LEVELS.items():
        pct_away = (price - level) / level * 100
        if name in ("200-Day MA", "March 2026 High", "ATH (Oct 2025)"):
            if 0 < pct_away < 2:
                events.append({"type": "APPROACHING", "severity": "MEDIUM",
                               "msg": f"🎯 Approaching {name}: ${price:,.0f} → ${level:,.0f}"})
            elif pct_away >= 0 and change > 2:
                events.append({"type": "BREAK_UP", "severity": "HIGH",
                               "msg": f"🚀 Broke above {name}: ${price:,.0f} > ${level:,.0f}"})
        else:  # Support levels
            if -2 < pct_away < 0 and change < -1:
                events.append({"type": "TESTING_SUPPORT", "severity": "MEDIUM",
                               "msg": f"⚠️ Testing support {name}: ${price:,.0f} near ${level:,.0f}"})
            elif pct_away < -2 and change < -2:
                events.append({"type": "BREAK_DOWN", "severity": "HIGH",
                               "msg": f"🔴 Broke below {name}: ${price:,.0f} < ${level:,.0f}"})

    # ③ Sustained 7h trend from 1h candles
    recent_1h = data.get("klines_1h", [])[-7:]
    up_count = sum(
        1 for k in recent_1h
        if len(k) >= 5 and k[1] and float(k[4]) > float(k[1])
    )
    if up_count >= 5:
        trend = "BULLISH"
        events.append({"type": "TREND", "severity": "LOW",
                       "msg": f"📈 7H trend: {up_count}/7 candles bullish (sustained buying)"})
    elif up_count <= 2:
        trend = "BEARISH"
        events.append({"type": "TREND", "severity": "LOW",
                       "msg": f"📉 7H trend: {7-up_count}/7 candles bearish (sustained selling)"})
    else:
        trend = "NEUTRAL"

    # ④ Key level position summary
    above = [n for n, l in KEY_LEVELS.items() if price > l]
    below = [n for n, l in KEY_LEVELS.items() if price <= l]
    nearest_resist = min((l for l in KEY_LEVELS.values() if l > price), default=None)
    nearest_support = max((l for l in KEY_LEVELS.values() if l <= price), default=None)

    return {
        "events":          events,
        "trend":           trend,
        "above_levels":    above,
        "below_levels":    below,
        "nearest_resist":  nearest_resist,
        "nearest_support": nearest_support,
        "is_significant":  bool(events) or CONFIG["ALWAYS_SEND"],
    }


# ── PDF generation ───────────────────────────────────────────────────
def generate_pdf(data: dict, analysis: dict) -> str | None:
    """Generate alert PDF. Returns file path or None."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import tempfile

        # Fonts
        FONT = FONT_BOLD = FONT_MONO = "Helvetica"
        fonts_dir = Path.home() / ".btc_brain_fonts"
        fonts_dir.mkdir(exist_ok=True)
        font_map = {
            "BB_Sans": "https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriCZa4ET-DNl0.ttf",
            "BB_Bold": "https://fonts.gstatic.com/s/dmsans/v15/rP2Cp2ywxg089UriAjTIq1EvgQ.ttf",
            "BB_Mono": "https://fonts.gstatic.com/s/dmmono/v14/aFTU7PB1QTsUX8KYvrumpr8.ttf",
        }
        for name, url in font_map.items():
            path = fonts_dir / f"{name}.ttf"
            if not path.exists():
                try:
                    urllib.request.urlretrieve(url, str(path))
                except Exception:
                    continue
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                if name == "BB_Sans":  FONT      = name
                if name == "BB_Bold":  FONT_BOLD = name
                if name == "BB_Mono":  FONT_MONO = name
            except Exception:
                pass

        # Colors
        ORANGE = colors.HexColor("#c45e00")
        DARK3  = colors.HexColor("#e0e0e0")
        DARK2  = colors.HexColor("#f5f5f5")
        MUTED  = colors.HexColor("#555555")
        BLACK  = colors.HexColor("#111111")
        GREEN  = colors.HexColor("#1a7a1a")
        RED    = colors.HexColor("#b71c1c")
        BLUE   = colors.HexColor("#1565c0")

        def P(text, size=10, color=BLACK, bold=False, center=False, mono=False):
            fn    = FONT_MONO if mono else (FONT_BOLD if bold else FONT)
            align = TA_CENTER if center else 0
            return Paragraph(
                f'<font name="{fn}" size="{size}" color="{color.hexval() if hasattr(color,"hexval") else "#111111"}">{text}</font>',
                ParagraphStyle("x", fontName=fn, fontSize=size, alignment=align, leading=size * 1.5)
            )

        price   = data["price"]
        change  = data["change"]
        now     = datetime.now()
        date_s  = now.strftime("%B %d, %Y")
        time_s  = now.strftime("%I:%M %p")
        chg_col = GREEN if change >= 0 else RED
        chg_sym = "+" if change >= 0 else ""
        events  = analysis["events"]
        trend   = analysis["trend"]
        alert_t = "SIGNIFICANT EVENT" if [e for e in events if e["severity"] == "HIGH"] else "DAILY BRIEFING"

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="btcbrain_")
        doc = SimpleDocTemplate(
            tmp.name, pagesize=letter,
            leftMargin=0.65*inch, rightMargin=0.65*inch,
            topMargin=0.55*inch, bottomMargin=0.65*inch,
            title=f"BTC Brain — {date_s}", author="Perplexity Computer"
        )
        story = []

        # Header
        hdr = Table([[
            P(f"₿ BTC BRAIN — {alert_t}", 16, ORANGE, bold=True),
            P(f"{date_s}  {time_s}", 9, MUTED, mono=True, center=True)
        ]], colWidths=[4.8*inch, 2.5*inch])
        hdr.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), colors.white),
            ("TOPPADDING",(0,0),(-1,-1),14), ("BOTTOMPADDING",(0,0),(-1,-1),14),
            ("LEFTPADDING",(0,0),(0,-1),18), ("RIGHTPADDING",(-1,0),(-1,-1),16),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LINEBELOW",(0,0),(-1,-1),1.5, ORANGE),
        ]))
        story += [hdr, Spacer(1, 8)]

        # Price row
        prow = Table([[
            P(f"${price:,.2f}", 34, ORANGE, bold=True),
            P(f"{chg_sym}{change:.2f}%", 20, chg_col, bold=True, center=True),
            P(f"H: ${data['high']:,.0f}  L: ${data['low']:,.0f}" if "high" in data else
              f"Vol: ${data['vol_usd']/1e9:.2f}B", 10, MUTED, mono=True, center=True),
        ]], colWidths=[3.6*inch, 1.8*inch, 1.9*inch])
        prow.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),colors.white),
            ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10),
            ("LEFTPADDING",(0,0),(0,-1),18), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LINEAFTER",(0,0),(1,-1),0.5, DARK3), ("LINEBELOW",(0,0),(-1,-1),0.5,DARK3),
        ]))
        story += [prow, Spacer(1, 8)]

        # Events
        if events:
            ev_rows = [[P("⚡ EVENTS DETECTED", 10, RED, bold=True)]]
            for ev in events:
                ev_rows.append([P(ev["msg"], 10, BLACK)])
            ev_tbl = Table(ev_rows, colWidths=[7.3*inch])
            ev_tbl.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,-1),colors.white),
                ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
                ("LEFTPADDING",(0,0),(-1,-1),16), ("LINEAFTER",(0,0),(0,-1),3,RED),
                ("BOX",(0,0),(-1,-1),0.5,DARK3),
            ]))
            story += [ev_tbl, Spacer(1, 8)]

        # Intelligence table
        trend_color = GREEN if trend == "BULLISH" else RED if trend == "BEARISH" else colors.HexColor("#e65100")
        intel_data = [
            [P("METRIC",9,MUTED,bold=True), P("VALUE",9,MUTED,bold=True), P("SIGNAL",9,MUTED,bold=True)],
            [P("4H/Daily Trend"), P(trend, 10, trend_color, bold=True), P("Based on 7 recent 1h candles",9,MUTED)],
            [P("24h Volume"), P(f"${data['vol_usd']/1e9:.2f}B",10,BLUE,mono=True), P("Market participation",9,MUTED)],
            [P("Market Cap"), P(f"${data['mcap']/1e12:.3f}T",10,BLUE,mono=True), P("Network value",9,MUTED)],
            [P("Nearest Resist"), P(f"${analysis['nearest_resist']:,.0f}" if analysis["nearest_resist"] else "N/A", 10, RED, mono=True), P("Next key level above",9,MUTED)],
            [P("Nearest Support"), P(f"${analysis['nearest_support']:,.0f}" if analysis["nearest_support"] else "N/A", 10, GREEN, mono=True), P("Next key level below",9,MUTED)],
        ]
        intel_tbl = Table(intel_data, colWidths=[1.8*inch,1.6*inch,3.9*inch])
        intel_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),DARK3), ("ROWBACKGROUNDS",(0,1),(-1,-1),[DARK2,colors.white]),
            ("GRID",(0,0),(-1,-1),0.3,DARK3), ("TOPPADDING",(0,0),(-1,-1),8),
            ("BOTTOMPADDING",(0,0),(-1,-1),8), ("LEFTPADDING",(0,0),(-1,-1),10),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ]))
        story += [P("MARKET INTELLIGENCE", 10, BLUE, bold=True), Spacer(1,4), intel_tbl, Spacer(1, 8)]

        # Key levels
        level_rows = [[P("LEVEL",9,MUTED,bold=True), P("PRICE",9,MUTED,bold=True), P("DISTANCE",9,MUTED,bold=True)]]
        for name, level in sorted(KEY_LEVELS.items(), key=lambda x: -x[1]):
            pct = (price - level) / level * 100
            col = GREEN if level < price else RED
            cur = " ← CURRENT" if abs(pct) < 2 else ""
            level_rows.append([P(name,9), P(f"${level:,.0f}",9,col,mono=True), P(f"{pct:+.1f}%"+cur,9,MUTED)])
        lvl_tbl = Table(level_rows, colWidths=[1.5*inch,1.3*inch,4.5*inch])
        lvl_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),DARK3), ("ROWBACKGROUNDS",(0,1),(-1,-1),[DARK2,colors.white]),
            ("GRID",(0,0),(-1,-1),0.3,DARK3), ("TOPPADDING",(0,0),(-1,-1),7),
            ("BOTTOMPADDING",(0,0),(-1,-1),7), ("LEFTPADDING",(0,0),(-1,-1),10),
        ]))
        story += [P("KEY LEVELS", 10, colors.HexColor("#e65100"), bold=True), Spacer(1,4), lvl_tbl, Spacer(1, 8)]

        # Footer
        foot = Table([[
            P("loopholemaxing.com/btc-brain", 8, MUTED),
            P(f"BTC Brain v5.0  |  IQ: 189  |  {data['source']}", 8, MUTED, center=True),
            P("Not financial advice", 8, MUTED),
        ]], colWidths=[2.4*inch, 3.0*inch, 1.9*inch])
        foot.setStyle(TableStyle([
            ("LINEABOVE",(0,0),(-1,0),0.8,ORANGE), ("BACKGROUND",(0,0),(-1,-1),colors.white),
            ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ]))
        story.append(foot)

        doc.build(story)
        log.info(f"  ✓ PDF generated: {tmp.name}")
        return tmp.name

    except ImportError:
        log.error("reportlab not installed — skipping PDF generation")
        return None
    except Exception as e:
        log.error(f"PDF generation failed: {e}", exc_info=True)
        return None


# ── Email via Resend ─────────────────────────────────────────────────
def send_email(data: dict, analysis: dict, pdf_path: str | None) -> bool:
    """Send alert email via Resend API (resend.com)."""
    api_key = CONFIG["RESEND_API_KEY"]
    if not api_key:
        log.warning("RESEND_API_KEY not set — skipping email")
        return False

    price  = data["price"]
    change = data["change"]
    events = analysis["events"]

    subject = (
        f"⚡ BTC Brain Alert — ${price:,.0f} ({change:+.2f}%)"
        if events else
        f"BTC Brain Daily — ${price:,.0f} ({change:+.2f}%)"
    )

    body_lines = [
        f"BTC/USD: ${price:,.2f}  ({change:+.2f}%)",
        f"Volume:  ${data['vol_usd']/1e9:.2f}B  |  MCap: ${data['mcap']/1e12:.3f}T",
        "",
    ]
    if events:
        body_lines.append("── EVENTS ──────────────────────")
        for ev in events:
            body_lines.append(f"  {ev['msg']}")
        body_lines.append("")
    body_lines += [
        f"7H Trend:        {analysis['trend']}",
        f"Nearest Resist:  ${analysis['nearest_resist']:,.0f}"  if analysis["nearest_resist"]  else "Nearest Resist:  N/A",
        f"Nearest Support: ${analysis['nearest_support']:,.0f}" if analysis["nearest_support"] else "Nearest Support: N/A",
        "",
        "── KEY LEVELS ──────────────────",
    ]
    for name, level in sorted(KEY_LEVELS.items(), key=lambda x: -x[1]):
        pct = (price - level) / level * 100
        body_lines.append(f"  {name:<22} ${level:>7,.0f}  ({pct:+.1f}%)")
    body_lines += [
        "",
        f"Brain IQ: 189  |  v5.0 Living Intelligence Edition",
        f"loopholemaxing.com/btc-brain",
        "",
        "─" * 38,
        f"Source:    {data['source']}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}",
        "Not financial advice.",
    ]
    body_text = "\n".join(body_lines)

    # Build Resend JSON payload
    payload: dict = {
        "from":    CONFIG["ALERT_EMAIL_FROM"],
        "to":      [CONFIG["ALERT_EMAIL_TO"]],
        "subject": subject,
        "text":    body_text,
    }

    # Attach PDF as base64
    if pdf_path:
        try:
            with open(pdf_path, "rb") as f:
                pdf_b64 = base64.b64encode(f.read()).decode()
            fname = f"btc_brain_{datetime.now().strftime('%Y%m%d')}.pdf"
            payload["attachments"] = [{"filename": fname, "content": pdf_b64}]
            log.info(f"  PDF attached: {fname}")
        except Exception as e:
            log.warning(f"  Could not attach PDF: {e}")

    # POST to Resend
    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            log.info(f"  ✓ Email sent via Resend: id={resp.get('id')} → {CONFIG['ALERT_EMAIL_TO']}")
            return True
    except urllib.error.HTTPError as e:
        log.error(f"  Resend HTTP {e.code}: {e.read().decode()[:300]}")
    except Exception as e:
        log.error(f"  Email failed: {e}", exc_info=True)
    return False


# ── Save run record ──────────────────────────────────────────────────
def save_run_record(data: dict, analysis: dict, sent: bool):
    """Append JSON record of this run to a log file for history tracking."""
    record = {
        "run_at":       datetime.now(timezone.utc).isoformat(),
        "price":        data["price"],
        "change_pct":   round(data["change"], 4),
        "trend":        analysis["trend"],
        "events":       [e["msg"] for e in analysis["events"]],
        "alert_sent":   sent,
        "iq":           189,
    }
    log_path = Path(CONFIG["LOG_DIR"]) / "run_history.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")
    log.info(f"  ✓ Run record saved to {log_path}")


# ── Main ─────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("  BTC Brain Automation Engine  —  Starting")
    log.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 55)

    # Fetch
    data = fetch_btc_data()
    if not data:
        log.error("Fatal: could not fetch BTC data. Exiting.")
        sys.exit(1)

    # Analyze
    analysis = analyze(data)
    log.info(f"Analysis: {len(analysis['events'])} events | trend={analysis['trend']} | significant={analysis['is_significant']}")

    if not analysis["is_significant"]:
        log.info("No significant events today — quiet day. No alert sent.")
        save_run_record(data, analysis, sent=False)
        log.info("Done.")
        return

    log.info(f"Significant events detected: {[e['msg'][:50] for e in analysis['events']]}")

    # Generate PDF
    pdf_path = generate_pdf(data, analysis)

    # Send email
    email_sent = send_email(data, analysis, pdf_path)

    # Cleanup temp PDF
    if pdf_path:
        try:
            Path(pdf_path).unlink()
        except Exception:
            pass

    save_run_record(data, analysis, sent=email_sent)
    log.info("=" * 55)
    log.info(f"  Done. Email sent: {email_sent}")
    log.info("=" * 55)


if __name__ == "__main__":
    main()
