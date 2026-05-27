#!/usr/bin/env bash
# Install the launchd agent that fires scripts/morning.sh at 9am Pacific daily.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$PROJECT_ROOT/deploy/com.tompkins.turnaround-screener.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.tompkins.turnaround-screener.plist"

if [[ ! -f "$PROJECT_ROOT/.venv/bin/python" ]]; then
    echo "Error: venv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_ROOT/data/logs"

# Substitute the project root into the plist
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$PLIST_SRC" > "$PLIST_DST"

# Unload first in case it was already installed (idempotent)
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Installed launchd agent: $PLIST_DST"
echo "Will fire daily at 9am Pacific."
echo ""
echo "To uninstall:    launchctl unload \"$PLIST_DST\" && rm \"$PLIST_DST\""
echo "To trigger now:  launchctl start com.tompkins.turnaround-screener"
echo "To check next:   launchctl list | grep turnaround-screener"
