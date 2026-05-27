#!/usr/bin/env bash
# Daily 9am wrapper. Runs the screener with deferred analysis, then pushes
# results to GitHub so today's candidates are visible from any device.
# Claude Code's /morning slash command picks up from there to do the analysis.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y-%m-%d)_morning.log"

{
    echo "=== $(date) ==="
    echo "Running screener with deferred analysis..."
    "$PROJECT_ROOT/.venv/bin/python" scripts/run_daily.py --skip-analysis --no-slack

    echo ""
    echo "Committing and pushing to GitHub..."
    git add data/pipeline.db data/reports data/pending data/logs 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git commit -m "Daily screen — $(date +%Y-%m-%d)"
        git push
    else
        echo "Nothing to commit."
    fi
    echo "=== Done $(date) ==="
} 2>&1 | tee -a "$LOG"
