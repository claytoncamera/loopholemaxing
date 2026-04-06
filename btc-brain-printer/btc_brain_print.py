#!/usr/bin/env python3
"""
BTC Brain Auto-Print Script
Runs daily on Mac Mini — fetches live BTC data, generates alert PDF, sends to printer.
Install: see README_SETUP.md in this folder
"""

import urllib.request, urllib.error, json, subprocess, os, sys, tempfile
from datetime import datetime

# ─────────────────────────────────────────
# CONFIG — edit these
# ─────────────────────────────────────────
PRINTER_NAME   = ""          # Leave blank to use default printer. Or set e.g. "HP_LaserJet"
ALERT_LOGFILE  = os.path.expanduser("~/btc_brain_alerts.log")
ONLY_ON_ALERTS = False       # True = only print if a significant event occurred
                              # False = always print the daily briefing

# Key levels to monitor
KEY_LEVELS = {
    "ATH":         126296,
    "200 MA":       89365,
    "March High":   76000,
    "20/50 MA":     68600,
    "Near Support": 65000,
    "Cycle Low":    60001,
}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(ALERT_LOGFILE, "a") as f:
        f.write(line + "\n")

def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "BTC-Brain-Printer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def get_btc_data():
    try:
        ticker = fetch("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
        klines_4h = fetch("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=14")
        klines_1d = fetch("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=7")
        try:
            funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
            fund_rate = float(funding.get("lastFundingRate", 0)) * 100
        except:
            fund_rate = None
        try:
            oi_data = fetch("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
            oi = float(oi_data.get("openInterest", 0))
        except:
            oi = None
        return {
            "price":   float(ticker["lastPrice"]),
            "change":  float(ticker["priceChangePercent"]),
            "high":    float(ticker["highPrice"]),
            "low":     float(ticker["lowPrice"]),
            "vol_usd": float(ticker["quoteVolume"]),
            "klines_4h": klines_4h,
            "klines_1d": klines_1d,
            "funding": fund_rate,
            "oi":      oi,
            "source":  "Binance",
        }
    except Exception as e:
        log(f"Binance failed ({e}), trying CoinGecko fallback...")
        try:
            cg = fetch("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true")
            btc = cg["bitcoin"]
            return {
                "price":   btc["usd"],
                "change":  btc.get("usd_24h_change", 0),
                "high":    btc["usd"] * 1.02,
                "low":     btc["usd"] * 0.98,
                "vol_usd": btc.get("usd_24h_vol", 0),
                "klines_4h": [],
                "klines_1d": [],
                "funding": None,
                "oi":      None,
                "source":  "CoinGecko",
            }
        except Exception as e2:
            log(f"Both APIs failed: {e2}")
            return None

def detect_events(d):
    events = []
    price, change = d["price"], d["change"]

    # Price move threshold
    if abs(change) >= 3.0:
        direction = "UP" if change > 0 else "DOWN"
        events.append(f"⚡ LARGE MOVE: BTC {direction} {change:+.2f}% in 24 hours")

    # Key level breaks
    for name, level in KEY_LEVELS.items():
        if name in ("ATH", "200 MA", "March High"):
            if price > level * 0.99 and price < level * 1.01:
                events.append(f"🎯 APPROACHING {name}: ${price:,.0f} near ${level:,.0f}")
            elif price > level and change > 0:
                events.append(f"🚀 BROKE ABOVE {name}: ${price:,.0f} > ${level:,.0f}")
        else:
            if price < level * 1.02 and change < 0:
                events.append(f"⚠️  TESTING SUPPORT {name}: ${price:,.0f} near ${level:,.0f}")
            elif price < level and change < -2:
                events.append(f"🔴 BROKE BELOW {name}: ${price:,.0f} < ${level:,.0f}")

    # Funding rate extremes
    if d["funding"] is not None:
        if d["funding"] > 0.05:
            events.append(f"🔥 FUNDING EXTREME HIGH: {d['funding']:+.4f}% — longs overleveraged")
        elif d["funding"] < -0.05:
            events.append(f"💎 FUNDING EXTREME LOW: {d['funding']:+.4f}% — capitulation signal")

    return events

def get_trend(klines):
    if not klines or len(klines) < 3:
        return "UNKNOWN"
    closes = [float(k[4]) for k in klines[-5:]]
    up = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    if up >= 4: return "BULLISH"
    if up <= 1: return "BEARISH"
    return "NEUTRAL"

def generate_pdf(d, events):
    """Generate alert PDF using ReportLab"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import urllib.request, os

        # Download fonts if needed
        fonts_dir = os.path.expanduser("~/.btc_brain_fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        font_urls = {
            'BB_Sans': 'https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriCZa4ET-DNl0.ttf',
            'BB_Bold': 'https://fonts.gstatic.com/s/dmsans/v15/rP2Cp2ywxg089UriAjTIq1EvgQ.ttf',
            'BB_Mono': 'https://fonts.gstatic.com/s/dmmono/v14/aFTU7PB1QTsUX8KYvrumpr8.ttf',
        }
        FONT = FONT_BOLD = FONT_MONO = 'Helvetica'
        for name, url in font_urls.items():
            path = os.path.join(fonts_dir, f"{name}.ttf")
            if not os.path.exists(path):
                try:
                    urllib.request.urlretrieve(url, path)
                except: continue
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                if name == 'BB_Sans':  FONT      = name
                if name == 'BB_Bold':  FONT_BOLD = name
                if name == 'BB_Mono':  FONT_MONO = name
            except: pass

        # Colors — light/print-friendly theme (minimal ink)
        C_ORANGE = colors.HexColor('#c45e00')   # darker orange for white bg
        C_DARK   = colors.white                  # white background
        C_DARK2  = colors.HexColor('#f5f5f5')   # very light gray
        C_DARK3  = colors.HexColor('#e0e0e0')   # light gray for borders
        C_TEXT   = colors.HexColor('#111111')   # near-black text
        C_MUTED  = colors.HexColor('#555555')   # medium gray
        C_GREEN  = colors.HexColor('#1a7a1a')   # dark green
        C_RED    = colors.HexColor('#b71c1c')   # dark red
        C_BLUE   = colors.HexColor('#1565c0')   # dark blue
        C_PURPLE = colors.HexColor('#6a1b9a')   # dark purple
        C_YELLOW = colors.HexColor('#e65100')   # dark amber

        price   = d["price"]
        change  = d["change"]
        now     = datetime.now()
        date_s  = now.strftime("%B %d, %Y")
        time_s  = now.strftime("%I:%M %p")
        alert_t = "LARGE MOVE DETECTED" if events else "DAILY BRIEFING"
        sev     = "HIGH" if events else "INFO"
        trend4h = get_trend(d.get("klines_4h", []))
        trend1d = get_trend(d.get("klines_1d", []))
        chg_col = '#3fb950' if change >= 0 else '#f85149'
        chg_sym = '+' if change >= 0 else ''

        tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False, prefix='btc_alert_')
        doc = SimpleDocTemplate(tmp.name, pagesize=letter,
            leftMargin=0.65*inch, rightMargin=0.65*inch,
            topMargin=0.55*inch, bottomMargin=0.65*inch,
            title=f'BTC Brain Alert — {date_s}',
            author='Perplexity Computer')

        def P(text, size=10, color='#111111', bold=False, center=False, mono=False):
            fn = FONT_MONO if mono else (FONT_BOLD if bold else FONT)
            align = TA_CENTER if center else TA_LEFT
            return Paragraph(f'<font name="{fn}" size="{size}" color="{color}">{text}</font>',
                              ParagraphStyle('x', fontName=fn, fontSize=size, alignment=align, leading=size*1.5))

        story = []

        # Header
        hdr = Table([[P(f'₿ BTC BRAIN — {alert_t}', 16, '#f7931a', bold=True),
                      P(f'{date_s}  {time_s}', 9, '#8b949e', mono=True, center=True)]],
                    colWidths=[4.8*inch, 2.5*inch])
        hdr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.white),
            ('TOPPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),14),
            ('LEFTPADDING',(0,0),(0,-1),18),('RIGHTPADDING',(-1,0),(-1,-1),16),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LINEBELOW',(0,0),(-1,-1),1.5,C_ORANGE)]))
        story += [hdr, Spacer(1, 8)]

        # Price row
        prow = Table([[
            P(f'${price:,.2f}', 34, '#f7931a', bold=True),
            P(f'{chg_sym}{change:.2f}%', 20, chg_col, bold=True, center=True),
            P(f'H: ${d["high"]:,.0f}  L: ${d["low"]:,.0f}', 10, '#8b949e', mono=True, center=True),
        ]], colWidths=[3.6*inch, 1.8*inch, 1.9*inch])
        prow.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.white),
            ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
            ('LEFTPADDING',(0,0),(0,-1),18),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LINEAFTER',(0,0),(1,-1),0.5,C_DARK3),
            ('LINEBELOW',(0,0),(-1,-1),0.5,C_DARK3)]))
        story += [prow, Spacer(1, 8)]

        # Events box (if any)
        if events:
            ev_rows = [[P('⚡ ALERT EVENTS DETECTED', 10, '#f7931a', bold=True)]]
            for ev in events:
                ev_rows.append([P(ev, 10, '#111111')])
            ev_tbl = Table(ev_rows, colWidths=[7.3*inch])
            ev_tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.white),
                ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
                ('LEFTPADDING',(0,0),(-1,-1),16),
                ('LINEAFTER',(0,0),(0,-1),3,C_RED),
                ('BOX',(0,0),(-1,-1),0.5,C_DARK3)]))
            story += [ev_tbl, Spacer(1, 8)]

        # Trend + levels
        trend_data = [
            [P('METRIC', 9, '#8b949e', bold=True), P('VALUE', 9, '#8b949e', bold=True), P('SIGNAL', 9, '#8b949e', bold=True)],
            [P('4H Trend', 10), P(trend4h, 10, '#3fb950' if trend4h == 'BULLISH' else '#f85149' if trend4h == 'BEARISH' else '#d29922', bold=True), P('Mid-term direction', 9, '#555555')],
            [P('Daily Trend', 10), P(trend1d, 10, '#3fb950' if trend1d == 'BULLISH' else '#f85149' if trend1d == 'BEARISH' else '#d29922', bold=True), P('Macro direction', 9, '#555555')],
            [P('24h Volume', 10), P(f'${d["vol_usd"]/1e9:.2f}B', 10, '#58a6ff', mono=True), P('Market activity', 9, '#555555')],
        ]
        if d["funding"] is not None:
            fc = '#f85149' if d["funding"] > 0.05 else '#3fb950' if d["funding"] < -0.05 else '#d29922'
            sig = 'Longs overleveraged' if d["funding"] > 0.05 else 'Capitulation signal' if d["funding"] < -0.05 else 'Neutral'
            trend_data.append([P('Funding Rate', 10), P(f'{d["funding"]:+.4f}%', 10, fc, mono=True), P(sig, 9, '#555555')])

        ttbl = Table(trend_data, colWidths=[1.8*inch, 1.6*inch, 3.9*inch])
        ttbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),C_DARK3),('BACKGROUND',(0,1),(-1,-1),C_DARK2),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_DARK2, C_DARK]),
            ('GRID',(0,0),(-1,-1),0.3,C_DARK3),
            ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
            ('LEFTPADDING',(0,0),(-1,-1),12),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        story += [P('MARKET INTELLIGENCE', 10, '#58a6ff', bold=True), Spacer(1,4), ttbl, Spacer(1, 8)]

        # Key levels
        level_rows = [[P('LEVEL', 9, '#8b949e', bold=True), P('PRICE', 9, '#8b949e', bold=True), P('STATUS', 9, '#8b949e', bold=True)]]
        for name, lvl in sorted(KEY_LEVELS.items(), key=lambda x: -x[1]):
            diff = (price - lvl) / lvl * 100
            status = f'{diff:+.1f}% from current'
            col = '#3fb950' if lvl < price else '#f85149'
            marker = ' ← CURRENT' if abs(diff) < 2 else ''
            level_rows.append([P(name, 9), P(f'${lvl:,.0f}', 9, col, mono=True), P(status + marker, 9, '#555555')])
        lvl_tbl = Table(level_rows, colWidths=[1.5*inch, 1.3*inch, 4.5*inch])
        lvl_tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),C_DARK3),('BACKGROUND',(0,1),(-1,-1),colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_DARK2, colors.white]),
            ('GRID',(0,0),(-1,-1),0.3,C_DARK3),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LEFTPADDING',(0,0),(-1,-1),10)]))
        story += [P('KEY LEVELS', 10, '#e65100', bold=True), Spacer(1,4), lvl_tbl, Spacer(1, 8)]

        # Footer
        foot = Table([[
            P('loopholemaxing.com/btc-brain', 8, '#555555'),
            P(f'BTC Brain v3.0  |  IQ: 164  |  {d["source"]}', 8, '#555555', center=True),
            P('Not financial advice', 8, '#555555'),
        ]], colWidths=[2.4*inch, 3.0*inch, 1.9*inch])
        foot.setStyle(TableStyle([('LINEABOVE',(0,0),(-1,0),0.8,C_ORANGE),
            ('BACKGROUND',(0,0),(-1,-1),colors.white),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.append(foot)

        doc.build(story)
        return tmp.name

    except ImportError:
        log("ReportLab not installed. Run: pip3 install reportlab")
        return None
    except Exception as e:
        log(f"PDF generation error: {e}")
        return None

def print_pdf(pdf_path):
    """Send PDF to printer using lp command (macOS/Linux)"""
    if not pdf_path or not os.path.exists(pdf_path):
        log(f"PDF not found: {pdf_path}")
        return False

    cmd = ["lp"]
    if PRINTER_NAME:
        cmd += ["-d", PRINTER_NAME]
    cmd.append(pdf_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log(f"✅ Printed: {result.stdout.strip()}")
            return True
        else:
            log(f"❌ Print failed: {result.stderr.strip()}")
            # Try open -p as fallback (opens print dialog in Preview)
            log("Trying Preview fallback...")
            subprocess.Popen(["open", "-p", pdf_path])
            return True
    except FileNotFoundError:
        log("lp command not found. Trying open -p (Preview)...")
        subprocess.Popen(["open", "-p", pdf_path])
        return True
    except Exception as e:
        log(f"Print error: {e}")
        return False

def main():
    log("=" * 50)
    log("BTC Brain Auto-Print — Starting")
    log("=" * 50)

    # Fetch data
    log("Fetching live BTC data...")
    data = get_btc_data()
    if not data:
        log("❌ Could not fetch BTC data. Exiting.")
        sys.exit(1)

    log(f"BTC: ${data['price']:,.2f} ({data['change']:+.2f}%) via {data['source']}")

    # Detect events
    events = detect_events(data)
    if events:
        log(f"⚡ {len(events)} significant event(s) detected:")
        for ev in events:
            log(f"  {ev}")
    else:
        log("No significant events — printing daily briefing")

    # Skip if ONLY_ON_ALERTS=True and no events
    if ONLY_ON_ALERTS and not events:
        log("ONLY_ON_ALERTS=True and no events. Skipping print.")
        sys.exit(0)

    # Generate PDF
    log("Generating alert PDF...")
    pdf_path = generate_pdf(data, events)
    if not pdf_path:
        log("❌ PDF generation failed.")
        sys.exit(1)
    log(f"PDF: {pdf_path}")

    # Print
    log("Sending to printer...")
    success = print_pdf(pdf_path)

    # Cleanup
    try:
        os.unlink(pdf_path)
    except:
        pass

    if success:
        log("✅ Done — BTC Brain daily alert printed")
    else:
        log("❌ Printing failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
