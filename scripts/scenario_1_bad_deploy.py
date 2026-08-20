# Scenario 1 — Bad Deploy Causes Payment Timeout Cascade
# Seeds realistic incident data across GitHub, Sentry,
# Slack, and PagerDuty for DevOps War Room demo testing.
# Run: python scripts/scenario_1_bad_deploy.py
# Cleanup: bash scripts/run_scenario.sh clean

import ssl
import certifi
import os

# Fix macOS SSL certificate verification
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()


import base64
import json
import os
import time
from datetime import UTC, datetime, timedelta

import requests
import sentry_sdk
from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv()

OWNER = "dhupthumbadiya2005"
REPO = "demo-payment-service"
BRANCH = "hotfix/reduce-gateway-timeout"
BASE_URL = f"https://api.github.com/repos/{OWNER}/{REPO}"
SLACK_CHANNELS = {
    "incidents": "C0B5WAQU8UW",
    "alerts": "C0B621BD0TE",
    "deploys": "C0B621GA3A8",
}


def github_headers():
    return {
        "Authorization": f"token {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def request_json(method, url, **kwargs):
    response = requests.request(method, url, timeout=30, **kwargs)
    if response.status_code >= 400:
        body = response.text[:500]
        raise RuntimeError(f"{method} {url} failed: HTTP {response.status_code} {body}")
    return response.json() if response.text else {}


def create_and_merge_pr():
    print("\n[1/5] Creating and merging GitHub PR...")
    try:
        headers = github_headers()
        main_ref = request_json("GET", f"{BASE_URL}/git/ref/heads/main", headers=headers)
        main_sha = main_ref["object"]["sha"]

        requests.delete(f"{BASE_URL}/git/refs/heads/{BRANCH}", headers=headers, timeout=30)
        request_json(
            "POST",
            f"{BASE_URL}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{BRANCH}", "sha": main_sha},
        )

        file_sha = None
        file_response = requests.get(
            f"{BASE_URL}/contents/config/timeouts.yaml",
            headers=headers,
            params={"ref": BRANCH},
            timeout=30,
        )
        if file_response.status_code == 200:
            file_sha = file_response.json().get("sha")

        content = (
            "gateway_timeout: 3000\n"
            "retry_count: 2\n"
            "connection_pool_size: 5\n"
            "health_check_interval: 10\n"
        )
        body = {
            "message": "perf: reduce gateway timeout for faster failure detection",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": BRANCH,
        }
        if file_sha:
            body["sha"] = file_sha
        request_json(
            "PUT",
            f"{BASE_URL}/contents/config/timeouts.yaml",
            headers=headers,
            json=body,
        )

        pr = request_json(
            "POST",
            f"{BASE_URL}/pulls",
            headers=headers,
            json={
                "title": "perf: reduce payment gateway timeout from 30s to 3s",
                "body": (
                    "Reduces timeout from 30000ms to 3000ms to fail faster on bad connections. "
                    "Tested on staging with p50 latency of 800ms. Resolves #47."
                ),
                "head": BRANCH,
                "base": "main",
            },
        )
        pr_number = pr["number"]
        request_json(
            "PUT",
            f"{BASE_URL}/pulls/{pr_number}/merge",
            headers=headers,
            json={
                "commit_title": "perf: reduce payment gateway timeout from 30s to 3s (#47)",
                "merge_method": "merge",
            },
        )
        print(f"✓ GitHub PR created and merged — PR #{pr_number}")
        return pr_number
    except Exception as exc:
        print(f"✗ GitHub step failed: {exc}")
        return "unknown"
    finally:
        time.sleep(3)


def send_sentry_errors():
    print("\n[2/5] Sending Sentry errors...")
    try:
        sentry_sdk.init(
            dsn=os.getenv("SENTRY_DSN"),
            environment="production",
            release="payment-service@2.4.2",
        )
        errors = [
            (
                23,
                "GatewayTimeoutError: payment gateway did not respond within 3000ms — downstream timeout on stripe.com:443",
            ),
            (
                18,
                "PaymentProcessingException: timeout waiting for gateway response — customer charge failed silently",
            ),
            (
                7,
                "ConnectionPoolTimeout: all 5 gateway connections busy — new request could not acquire connection within 3000ms",
            ),
        ]
        for count, message in errors:
            for _ in range(count):
                try:
                    raise Exception(message)
                except Exception as exc:
                    sentry_sdk.capture_exception(exc)
            time.sleep(0.3)
        sentry_sdk.flush()
        print("✓ Sentry errors sent — 48 total errors across 3 types")
    except Exception as exc:
        print(f"✗ Sentry step failed: {exc}")
    finally:
        time.sleep(2)


def post_slack_messages():
    print("\n[3/5] Posting Slack messages...")
    try:
        client = WebClient(token=os.getenv("SLACK_TOKEN"))
        deploys = [
            "🚀 Deploy started: payment-service v2.4.2 → production by @alex.dev",
            "📝 PR merged: 'perf: reduce payment gateway timeout from 30s to 3s' by @alex.dev — config/timeouts.yaml changed",
            "✅ Deploy complete: payment-service v2.4.2 live on all nodes (3/3)",
            "📊 Post-deploy metrics look normal on p50 — monitoring for 10min",
        ]
        alerts = [
            "🔴 ALERT: payment-service error rate 44% — threshold 5% — firing for 2m",
            "🔴 ALERT: payment-service P99 latency 9200ms — threshold 2000ms",
            "🔴 ALERT: payment-service gateway timeout rate 41% — NEW ALERT",
        ]
        incidents = [
            "🚨 Incident opened: payment-service error rate 44% — PagerDuty P1",
            "Pulling up Datadog — seeing massive spike in GatewayTimeoutError starting 14 minutes ago",
            "Checking recent deploys — payment-service v2.4.2 went out 18 minutes ago",
            "PR in that deploy: 'reduce payment gateway timeout from 30s to 3s' — that's almost certainly it",
            "Gateway timeout changed from 30s to 3s — under production load legitimate payments take 4-8s",
            "Initiating rollback of v2.4.2 now",
        ]
        for message in deploys:
            client.chat_postMessage(channel=SLACK_CHANNELS["deploys"], text=message)
            time.sleep(1)
        for message in alerts:
            client.chat_postMessage(channel=SLACK_CHANNELS["alerts"], text=message)
            time.sleep(1)
        for message in incidents:
            client.chat_postMessage(channel=SLACK_CHANNELS["incidents"], text=message)
            time.sleep(1.5)
        print("✓ Slack messages posted to #deploys, #alerts, #incidents")
    except Exception as exc:
        print(f"✗ Slack step failed: {exc}")
    finally:
        time.sleep(2)


def trigger_pagerduty():
    print("\n[4/5] Triggering PagerDuty incident...")
    try:
        deploy_time = (datetime.now(UTC) - timedelta(minutes=18)).isoformat()
        response = request_json(
            "POST",
            "https://events.pagerduty.com/v2/enqueue",
            headers={"Content-Type": "application/json"},
            json={
                "routing_key": os.getenv("PAGERDUTY_PAYMENT_SERVICE_INTEGRATION_KEY"),
                "event_action": "trigger",
                "payload": {
                    "summary": "payment-service error rate 44% — gateway timeout cascade after deploy v2.4.2",
                    "severity": "critical",
                    "source": "payment-service-prod",
                    "custom_details": {
                        "service": "payment-service",
                        "error_rate": "44%",
                        "baseline_error_rate": "0.3%",
                        "primary_error": "GatewayTimeoutError",
                        "deploy_version": "v2.4.2",
                        "deploy_time": deploy_time,
                        "affected_endpoints": "/api/v1/charge, /api/v1/refund",
                        "environment": "production",
                    },
                },
            },
        )
        dedup_key = response.get("dedup_key", "")
        if dedup_key:
            with open("/tmp/scenario_1_dedup_key.txt", "w", encoding="utf-8") as handle:
                handle.write(dedup_key)
        print("✓ PagerDuty incident triggered")
    except Exception as exc:
        print(f"✗ PagerDuty step failed: {exc}")


def print_summary(pr_number):
    print(
        f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENARIO 1 SEEDED — Bad Deploy / Timeout Cascade
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub PR:  #{pr_number} merged to main
Sentry:     48 errors across 3 types
Slack:      Messages in #deploys, #alerts, #incidents
PagerDuty:  Incident triggered (critical)

EXPECTED REPORT OUTPUT:
Root cause → PR #{pr_number}: reduce gateway timeout 30s→3s
Evidence   → 23x GatewayTimeoutError in Sentry
             Deploy in #deploys 18min before incident
             Human confirmation in #incidents
Confidence → HIGH
3rd party  → Stripe operational (internal issue confirmed)

The agent will investigate in ~30 seconds.
Watch: dashboard at http://localhost:8000
Watch: #incidents in Slack for the report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    )


def main():
    print("Scenario 1 — Bad Deploy Causes Payment Timeout Cascade")
    pr_number = create_and_merge_pr()
    send_sentry_errors()
    post_slack_messages()
    trigger_pagerduty()
    print_summary(pr_number)


if __name__ == "__main__":
    main()
