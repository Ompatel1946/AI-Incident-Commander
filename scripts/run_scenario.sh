#!/bin/bash
# Usage:
#   bash scripts/run_scenario.sh 1    — runs scenario 1
#   bash scripts/run_scenario.sh 2    — runs scenario 2
#   bash scripts/run_scenario.sh clean — resolves all incidents

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || true
export $(cat .env | grep -v '^#' | xargs)

SCENARIO=$1

if [ -z "$SCENARIO" ]; then
  echo "Usage: bash scripts/run_scenario.sh [1|2|clean]"
  exit 1
fi

if [ "$SCENARIO" = "clean" ]; then
  echo "🧹 Cleaning up all scenarios..."
  python3 scripts/cleanup_scenarios.py
  exit 0
fi

if [ "$SCENARIO" = "1" ]; then
  echo "🎬 Running Scenario 1: Bad Deploy / Timeout Cascade"
  echo "This will seed GitHub, Sentry, Slack, and PagerDuty"
  echo ""
  python3 scripts/scenario_1_bad_deploy.py
fi

if [ "$SCENARIO" = "2" ]; then
  echo "🎬 Running Scenario 2: Memory Leak / SDK Upgrade"
  echo "This will seed GitHub, Sentry, Slack, and PagerDuty"
  echo ""
  python3 scripts/scenario_2_memory_leak.py
fi

echo ""
echo "Agent is watching. Report will appear in ~30 seconds."
echo "Dashboard: http://localhost:8000"
