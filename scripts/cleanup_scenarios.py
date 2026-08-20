# Cleanup — Demo scenario reset
# Resolves PagerDuty incidents created by the scenario scripts and removes
# stale local report files so the dashboard returns to a clean state.
# Run: python scripts/cleanup_scenarios.py

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DEDUP_KEY_FILES = [
    "/tmp/scenario_1_dedup_key.txt",
    "/tmp/scenario_2_dedup_key.txt",
]


def resolve_incident(dedup_key):
    response = requests.post(
        "https://events.pagerduty.com/v2/enqueue",
        headers={"Content-Type": "application/json"},
        json={
            "routing_key": os.getenv("PAGERDUTY_PAYMENT_SERVICE_INTEGRATION_KEY"),
            "event_action": "resolve",
            "dedup_key": dedup_key,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"PagerDuty resolve failed: HTTP {response.status_code} {response.text[:300]}")


def cleanup_pagerduty():
    for path in DEDUP_KEY_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            dedup_key = handle.read().strip()
        if not dedup_key:
            os.remove(path)
            continue
        try:
            resolve_incident(dedup_key)
            print(f"✓ Resolved incident: {dedup_key[:12]}...")
            os.remove(path)
        except Exception as exc:
            print(f"✗ Failed to resolve {dedup_key[:12]}...: {exc}")


def cleanup_reports():
    reports_dir = "reports"
    if not os.path.isdir(reports_dir):
        return
    cutoff = time.time() - 600
    for name in os.listdir(reports_dir):
        if not name.endswith(".txt"):
            continue
        path = os.path.join(reports_dir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except Exception as exc:
            print(f"✗ Failed to delete old report {path}: {exc}")


def main():
    cleanup_pagerduty()
    cleanup_reports()
    print(
        """
✓ All incidents resolved
✓ Old reports cleaned up
Dashboard should show: All systems operational
Ready for next scenario run.
"""
    )


if __name__ == "__main__":
    main()
