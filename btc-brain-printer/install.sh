#!/bin/bash
# BTC Brain Auto-Print — One-Command Installer
# Run on your Mac Mini: bash <(curl -fsSL https://raw.githubusercontent.com/claytoncamera/loopholemaxing/main/btc-brain-printer/install.sh)

set -e

SCRIPT_PATH="/usr/local/bin/btc_brain_print.py"
PLIST_PATH="$HOME/Library/LaunchAgents/com.btcbrain.printer.plist"
REPO_RAW="https://raw.githubusercontent.com/claytoncamera/loopholemaxing/main/btc-brain-printer"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   BTC Brain Auto-Print — Installer       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: Python3 check ──────────────────────
echo "① Checking Python3..."
if ! command -v python3 &>/dev/null; then
  echo "  ✗ Python3 not found. Install from python.org"
  exit 1
fi
echo "  ✓ $(python3 --version)"

# ── Step 2: Install reportlab ──────────────────
echo ""
echo "② Installing reportlab..."
pip3 install reportlab --quiet && echo "  ✓ reportlab installed" || {
  pip3 install --user reportlab --quiet && echo "  ✓ reportlab installed (user)"
}

# ── Step 3: Detect printer ─────────────────────
echo ""
echo "③ Detecting printers..."
PRINTER_NAME=""
if command -v lpstat &>/dev/null; then
  DEFAULT_PRINTER=$(lpstat -d 2>/dev/null | awk '{print $NF}')
  PRINTER_LIST=$(lpstat -p 2>/dev/null | awk '{print $2}' | head -5)
  if [ -n "$PRINTER_LIST" ]; then
    echo "  Found printers:"
    echo "$PRINTER_LIST" | while read p; do echo "    • $p"; done
    PRINTER_NAME="$DEFAULT_PRINTER"
    echo "  ✓ Using default: ${PRINTER_NAME:-system default}"
  else
    echo "  ⚠ No printers found — will open Preview for manual print"
  fi
else
  echo "  ⚠ lpstat not available — will use Preview fallback"
fi

# ── Step 4: Download script ────────────────────
echo ""
echo "④ Downloading print script..."
curl -fsSL "$REPO_RAW/btc_brain_print.py" -o "$SCRIPT_PATH"
chmod +x "$SCRIPT_PATH"
echo "  ✓ Saved to $SCRIPT_PATH ($(wc -l < $SCRIPT_PATH) lines)"

# ── Step 5: Inject printer name ────────────────
if [ -n "$PRINTER_NAME" ]; then
  # Replace PRINTER_NAME = "" with the detected printer
  sed -i '' "s/PRINTER_NAME   = \"\"/PRINTER_NAME   = \"$PRINTER_NAME\"/" "$SCRIPT_PATH"
  echo "  ✓ Configured printer: $PRINTER_NAME"
fi

# ── Step 6: Install scheduler ─────────────────
echo ""
echo "⑤ Installing daily scheduler (6:05 AM)..."
mkdir -p "$HOME/Library/LaunchAgents"
curl -fsSL "$REPO_RAW/com.btcbrain.printer.plist" -o "$PLIST_PATH"

# Unload old instance if running
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load new
launchctl load "$PLIST_PATH"

# Verify
if launchctl list | grep -q "com.btcbrain.printer"; then
  echo "  ✓ Scheduler active — will run daily at 6:05 AM"
else
  echo "  ⚠ Scheduler loaded but not confirmed — may need relogin"
fi

# ── Step 7: Test run ───────────────────────────
echo ""
echo "⑥ Running test now..."
echo "─────────────────────────────────────────"
python3 "$SCRIPT_PATH"
echo "─────────────────────────────────────────"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ✅ BTC Brain Auto-Print is installed!  ║"
echo "║                                          ║"
echo "║   Prints daily at 6:05 AM automatically ║"
echo "║   Logs: ~/btc_brain_alerts.log           ║"
echo "╚══════════════════════════════════════════╝"
echo ""
