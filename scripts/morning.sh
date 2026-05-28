#!/usr/bin/env bash
# Daily 9am wrapper. Three stages:
#   1. Run the screener with deferred analysis → dump pending dossiers
#   2. Commit + push the screener output (so candidates visible immediately)
#   3. Invoke `claude -p /morning` headless to run the full analysis +
#      auto-promote interesting names to deep dives, then commit + push again
#
# If the `claude` CLI isn't installed/auth'd, stage 3 is skipped gracefully —
# the user can run `/morning` interactively later.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y-%m-%d)_morning.log"

# Resolve claude CLI (launchd has minimal PATH; we set it in the plist too)
CLAUDE_BIN=""
for candidate in \
    "$HOME/.npm-global/bin/claude" \
    "$HOME/.claude/local/claude" \
    /opt/homebrew/bin/claude \
    /usr/local/bin/claude \
    "$(command -v claude 2>/dev/null || true)"; do
    if [[ -x "$candidate" ]]; then
        CLAUDE_BIN="$candidate"
        break
    fi
done

{
    echo "=== $(date) STAGE 1: Screener ==="
    "$PROJECT_ROOT/.venv/bin/python" scripts/run_daily.py --skip-analysis --no-slack

    echo ""
    echo "=== $(date) STAGE 2: Commit + push screener output ==="
    git add data/pipeline.db data/reports data/pending data/logs 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git -c user.email="jonto2121@gmail.com" -c user.name="Jonathan Tompkins" \
            commit -m "Screener output $(date +%Y-%m-%d)" || true
        git push || echo "  (push failed, will retry after analysis)"
    else
        echo "Nothing to commit at stage 2."
    fi

    echo ""
    echo "=== $(date) STAGE 3: Claude analysis (headless) ==="
    if [[ -n "$CLAUDE_BIN" ]]; then
        echo "Invoking $CLAUDE_BIN -p '/morning' ..."
        "$CLAUDE_BIN" -p "/morning" --output-format text 2>&1 || {
            echo "  Claude analysis exited non-zero. Pending dossiers remain in data/pending/ — re-run interactively with /morning later."
        }
    else
        echo "  claude CLI not found in PATH. Analysis must be run manually."
        echo "  To install: visit https://docs.claude.com/en/docs/claude-code"
    fi

    # If claude wrote analyses, commit+push them too (idempotent if there's nothing).
    git add data/pipeline.db data/analyzed data/research data/reports data/logs 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git -c user.email="jonto2121@gmail.com" -c user.name="Jonathan Tompkins" \
            commit -m "Daily analysis $(date +%Y-%m-%d)" || true
        git push || true
    fi

    echo "=== Done $(date) ==="
} 2>&1 | tee -a "$LOG"
