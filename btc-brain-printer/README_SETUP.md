# BTC Brain Auto-Print — Mac Mini Setup

Prints a fresh BTC intelligence alert PDF to your physical printer every morning at 6:05 AM.

## Requirements

- macOS (Mac Mini or any Mac)
- Python 3 (comes pre-installed on macOS)
- A printer connected to the Mac (USB, AirPrint, or network)
- `reportlab` Python package

---

## Step 1 — Install reportlab

Open Terminal and run:
```bash
pip3 install reportlab
```

---

## Step 2 — Find your printer name

In Terminal:
```bash
lpstat -p -d
```

You'll see output like:
```
printer HP_LaserJet_Pro is idle
```

Copy the printer name (e.g., `HP_LaserJet_Pro`).

---

## Step 3 — Configure the script

Open `btc_brain_print.py` in any text editor and set:
```python
PRINTER_NAME = "HP_LaserJet_Pro"    # your printer name from step 2
ONLY_ON_ALERTS = False              # True = only print if BTC moved significantly
```

---

## Step 4 — Install the script

```bash
# Copy the script to a permanent location
cp btc_brain_print.py /usr/local/bin/btc_brain_print.py
chmod +x /usr/local/bin/btc_brain_print.py
```

---

## Step 5 — Install the scheduler (launchd)

This makes it run automatically every day at 6:05 AM:

```bash
# Copy the plist to your LaunchAgents folder
cp com.btcbrain.printer.plist ~/Library/LaunchAgents/

# Load it (starts it without rebooting)
launchctl load ~/Library/LaunchAgents/com.btcbrain.printer.plist

# Verify it's loaded
launchctl list | grep btcbrain
```

You should see `com.btcbrain.printer` in the output.

---

## Step 6 — Test it right now

Don't wait until tomorrow — run it immediately:
```bash
python3 /usr/local/bin/btc_brain_print.py
```

Watch the output. You should see:
```
[...] BTC Brain Auto-Print — Starting
[...] Fetching live BTC data...
[...] BTC: $69,252 (+3.10%) via Binance
[...] Generating alert PDF...
[...] Sending to printer...
[...] ✅ Printed: request id is HP_LaserJet_Pro-12 (1 file(s))
[...] ✅ Done — BTC Brain daily alert printed
```

---

## Logs

Check the log file anytime:
```bash
cat ~/btc_brain_alerts.log
```

Or the launchd log:
```bash
cat /Users/Shared/btc_brain_print.log
```

---

## Stopping / Uninstalling

```bash
# Stop the scheduler
launchctl unload ~/Library/LaunchAgents/com.btcbrain.printer.plist

# Remove files
rm ~/Library/LaunchAgents/com.btcbrain.printer.plist
rm /usr/local/bin/btc_brain_print.py
```

---

## What Gets Printed

Every morning at 6:05 AM the script:
1. Fetches live BTC price, 4H/daily klines, funding rate, OI from Binance
2. Detects significant events (3%+ moves, key level breaks, funding extremes)
3. Generates a formatted 1-page PDF alert with:
   - Current price, 24h change, high/low
   - 4H + Daily trend direction
   - Volume and derivatives data
   - Key levels with % distance from current price
   - Alert events highlighted (if any occurred)
   - BTC Brain IQ status footer
4. Sends to your printer automatically

If `ONLY_ON_ALERTS = True`, it only prints when something significant happened.
If `ONLY_ON_ALERTS = False`, it prints a clean daily briefing every morning regardless.

---

## Changing the Print Time

Edit `com.btcbrain.printer.plist`, change Hour/Minute, then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.btcbrain.printer.plist
launchctl load ~/Library/LaunchAgents/com.btcbrain.printer.plist
```

