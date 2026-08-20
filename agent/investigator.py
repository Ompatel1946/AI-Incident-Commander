"""
DevOps War Room — Incident investigation orchestrator.

Coordinates the full investigation pipeline for a single incident:
  1. Run Coral cross-source correlation queries
  2. Fetch Slack channel context
  3. Check third-party vendor status
  4. Generate report with Groq
  5. Post to Slack and save locally
"""

import time

import config
from coral import run_correlation_queries, check_third_party_status
from reports import generate_report, save_report
from slack_integration import fetch_all_slack_context, post_report_to_slack
from utils import utc_now


def investigate_incident(incident: dict) -> str | None:
    """Investigate one incident and continue gracefully if a step fails."""
    try:
        incident_id = incident["id"]
        incident_created = incident.get("created_at", utc_now().isoformat())
        print(f"\n{'=' * 60}")
        print(f"INVESTIGATING: {incident['title']}")
        print(f"ID: {incident_id} | Urgency: {incident['urgency']}")
        print(f"{'=' * 60}")

        print("\n[1/5] Running Coral cross-source correlation queries...")
        started = time.time()
        correlation_data, query_strings = run_correlation_queries(incident_id, incident_created)
        print(f"  → Done in {time.time() - started:.1f}s")

        print("\n[2/5] Fetching Slack channel context...")
        slack_context = fetch_all_slack_context()
        print("  → Done")

        print("\n[3/5] Checking third-party vendor status...")
        statuspage_data = check_third_party_status()
        print("  → Done")

        full_context = correlation_data + "\n\n" + slack_context

        print(f"\n[4/5] Generating report with Groq ({config.GROQ_MODEL})...")
        started = time.time()
        report = generate_report(incident, full_context, statuspage_data)
        print(f"  → Done in {time.time() - started:.1f}s")

        print("\n[5/5] Posting to Slack and saving locally...")
        post_report_to_slack(incident, report)
        filename = save_report(incident, report, query_strings)

        print(f"\n✅ Complete — {filename}")
        return report
    except Exception as exc:
        print(f"[ERROR] Failed to investigate incident {incident.get('id', 'unknown')}: {exc}")
        return None
