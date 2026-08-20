"""
DevOps War Room — Main entry point.

Polls PagerDuty for active incidents and triggers investigation
for each new incident. The agent runs continuously until stopped.
"""

import time

import config
from coral import discover_source_columns, inspect_github_tables
from investigator import investigate_incident
from pagerduty import fetch_active_incidents
from utils import utc_now


def run_polling_mode(interval_seconds: int = 30) -> None:
    """Poll PagerDuty for active incidents and investigate new ones."""
    print("🚀 DevOps War Room agent started")
    print(f"   Model  : {config.GROQ_MODEL} (Groq)")
    print(f"   Poll   : every {interval_seconds}s")
    print(f"   Channel: #{config.SLACK_CHANNEL}\n")

    # Discover source schemas at startup so queries use correct column names
    discover_source_columns()
    inspect_github_tables()

    investigated = set()

    while True:
        try:
            incidents = fetch_active_incidents()
            if not incidents:
                print(f"[{utc_now().strftime('%H:%M:%S')}] No active incidents. Watching...")
            else:
                for incident in incidents:
                    if incident["id"] not in investigated:
                        investigate_incident(incident)
                        investigated.add(incident["id"])
                    else:
                        print(
                            f"[{utc_now().strftime('%H:%M:%S')}] "
                            f"Already handled: {incident['id']}"
                        )
        except KeyboardInterrupt:
            print("\n\nAgent stopped.")
            break
        except Exception as exc:
            print(f"[ERROR] Polling loop error: {exc}")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_polling_mode(interval_seconds=30)
