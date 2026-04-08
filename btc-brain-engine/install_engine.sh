#!/bin/bash
# BTC Brain Engine — Mac Mini Installer
# Installs the full automation engine: data fetch + PDF + email via Resend
# Runs daily at 6:05 AM (right after the print script)

set -e
ENGINE_PATH="$HOME/bin/btc_brain_engine.py"
PLIST_PATH="$HOME/Library/LaunchAgents/com.btcbrain.engine.plist"
REPO_RAW="https://raw.githubusercontent.com/claytoncamera/loopholemaxing/main/btc-brain-engine"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║   BTC Brain Engine Installer                   ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# ① Python check
echo "① Checking Python3..."
python3 --version && echo "  ✓ Python3 found"

# ② Install dependencies
echo ""
echo "② Installing dependencies..."
pip3 install reportlab --break-system-packages --quiet 2>/dev/null \
  || pip3 install reportlab --user --quiet
echo "  ✓ reportlab installed"

# ③ Prompt for Resend API key
echo ""
echo "③ Configure email..."
if [ -z "$RESEND_API_KEY" ]; then
  echo "  Enter your Resend API key (re_NwsqUtYm_...):"
  read -r RESEND_API_KEY
fi
echo "  ✓ API key set"

# ④ Download engine
echo ""
echo "④ Downloading engine..."
mkdir -p "$HOME/bin"
curl -fsSL "$REPO_RAW/engine.py" -o "$ENGINE_PATH"
chmod +x "$ENGINE_PATH"
echo "  ✓ Saved to $ENGINE_PATH ($(wc -l < $ENGINE_PATH) lines)"

# ⑤ Create wrapper script that injects env vars
cat > "$HOME/bin/btc_brain_engine_run.sh" << WRAPPER
#!/bin/bash
export RESEND_API_KEY="${RESEND_API_KEY}"
export ALERT_EMAIL_FROM="BTC Brain <btcbrain@orbitroute.ai>"
export ALERT_EMAIL_TO="clayton.camera@icloud.com"
export ALWAYS_SEND=false
export LOG_DIR="$HOME/btc_brain_logs"
python3 "${ENGINE_PATH}"
WRAPPER
chmod +x "$HOME/bin/btc_brain_engine_run.sh"
echo "  ✓ Wrapper script created"

# ⑥ Install launchd plist
echo ""
echo "⑥ Installing scheduler (6:05 AM daily)..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.btcbrain.engine</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HOME/bin/btc_brain_engine_run.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>5</integer>
  </dict>
  <key>StandardOutPath</key><string>$HOME/btc_brain_logs/engine.log</string>
  <key>StandardErrorPath</key><string>$HOME/btc_brain_logs/engine_err.log</string>
  <key>RunAtLoad</key><false/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
PLIST

mkdir -p "$HOME/btc_brain_logs"
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

if launchctl list | grep -q "com.btcbrain.engine"; then
  echo "  ✓ Scheduler active — runs daily at 6:05 AM"
else
  echo "  ⚠ Loaded but not confirmed — may need re-login"
fi

# ⑦ Test run
echo ""
echo "⑦ Running test (email will send)..."
echo "────────────────────────────────────────────────"
bash "$HOME/bin/btc_brain_engine_run.sh"
echo "────────────────────────────────────────────────"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║   ✅ BTC Brain Engine installed!               ║"
echo "║                                                ║"
echo "║   Runs daily at 6:05 AM                        ║"
echo "║   Sends email to clayton.camera@icloud.com     ║"
echo "║   Logs: ~/btc_brain_logs/                      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
