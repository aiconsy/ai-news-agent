#!/usr/bin/env bash
# ── AI News Agent — Hourly Cron Wrapper ──────────────────────────────────────
# Run this via cron or Hermes scheduler to generate hourly briefings.
#
# Usage:
#   ./scripts/run_hourly.sh              # Normal run
#   ./scripts/run_hourly.sh --force       # Force (ignore dedup/quiet hours)
#   ./scripts/run_hourly.sh --text-only   # Text only, no TTS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Activate venv if present
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Run the pipeline
cd "$PROJECT_DIR"
python -m ai_news_agent.main "$@"

echo "Pipeline run complete at $(date -u '+%Y-%m-%d %H:%M UTC')"