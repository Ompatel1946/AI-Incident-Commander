"""
DevOps War Room — PagerDuty integration.

Fetches active triggered incidents from PagerDuty's API.
All error paths return [] — the agent must never crash on a
PagerDuty fetch failure.
"""

import os

import requests


def fetch_active_incidents() -> list[dict]:
    """Fetch active triggered incidents from PagerDuty.

    Returns an empty list on any failure — never crashes the agent loop.
    """
    try:
        response = requests.get(
            "https://api.pagerduty.com/incidents",
            headers={
                "Authorization": f"Token token={os.getenv('PAGERDUTY_API_TOKEN')}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            },
            params={"statuses[]": "triggered", "limit": 5},
            timeout=20,
        )
        if response.status_code != 200:
            print(f"[ERROR] PagerDuty returned status {response.status_code}: {response.text[:200]}")
            return []
        try:
            data = response.json()
        except ValueError as exc:
            print(f"[ERROR] Failed to parse PagerDuty JSON response: {exc}")
            return []
        return data.get("incidents", [])
    except requests.exceptions.Timeout:
        print("[ERROR] PagerDuty request timed out after 20s")
        return []
    except requests.exceptions.ConnectionError:
        print("[ERROR] Could not connect to PagerDuty — check network")
        return []
    except Exception as exc:
        print(f"[ERROR] Failed to fetch PagerDuty incidents: {exc}")
        return []
