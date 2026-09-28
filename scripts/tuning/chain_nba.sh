#!/bin/bash
# Wait for the running terra ablation (3 graphs) to finish, then run the nba column.
# Idempotent: re-running this script after an interruption resumes at the first unfinished cell.
cd /Users/q0w01lh/Documents/repo/t2c || exit 1
while pgrep -f "[r]un_ablation_model.py" >/dev/null 2>&1; do sleep 60; done
echo "=== previous driver finished; starting nba column $(date '+%H:%M') ==="
export $(grep -v '^#' .env | xargs) 2>/dev/null
exec ./llmenv/bin/python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --graphs nba
