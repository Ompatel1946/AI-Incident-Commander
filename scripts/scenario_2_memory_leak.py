# Scenario 2 — Memory Leak from Dependency Upgrade
# Seeds realistic incident data across GitHub, Sentry,
# Slack, and PagerDuty for DevOps War Room demo testing.
# Run: python scripts/scenario_2_memory_leak.py
# Cleanup: bash scripts/run_scenario.sh clean

import base64
import json
import os
import random
import time

import requests
import sentry_sdk
from dotenv import load_dotenv
from slack_sdk import WebClient

import ssl
import certifi
import os

# Fix macOS SSL certificate verification
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()



load_dotenv()

OWNER = "dhupthumbadiya2005"
REPO = "demo-payment-service"
BRANCH = "deps/upgrade-stripe-sdk-7"
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
            f"{BASE_URL}/contents/requirements.txt",
            headers=headers,
            params={"ref": BRANCH},
            timeout=30,
        )
        if file_response.status_code == 200:
            file_sha = file_response.json().get("sha")

        content = (
            "stripe==7.0.0\n"
            "requests==2.31.0\n"
            "pyyaml==6.0.1\n"
            "psycopg2-binary==2.9.9\n"
            "redis==5.0.1\n"
        )
        body = {
            "message": "deps: upgrade stripe-python from 5.4.0 to 7.0.0",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": BRANCH,
        }
        if file_sha:
            body["sha"] = file_sha
        request_json("PUT", f"{BASE_URL}/contents/requirements.txt", headers=headers, json=body)

        pr = request_json(
            "POST",
            f"{BASE_URL}/pulls",
            headers=headers,
            json={
                "title": "deps: upgrade stripe-python from 5.4.0 to 7.0.0",
                "body": (
                    "Major version upgrade for Stripe SDK. v7 includes new webhook handling, "
                    "improved idempotency keys, and async support. Breaking changes documented "
                    "in MIGRATION.md. Tested on staging for 2 hours — all payment flows passing. Resolves #52."
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
                "commit_title": "deps: upgrade stripe-python from 5.4.0 to 7.0.0 (#52)",
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
            release="payment-service@2.4.3",
        )
        for _ in range(31):
            try:
                raise MemoryError(
                    "OOMKilled: container exceeded memory limit 512Mi "
                    f"— heap usage {random.randint(85, 98)}% before kill signal "
                    f"— pod payment-service-{random.randint(1, 3)} "
                    f"— memory {random.randint(480, 512)}Mi/512Mi"
                )
            except MemoryError as exc:
                sentry_sdk.capture_exception(exc)
            time.sleep(0.1)

        for _ in range(12):
            try:
                raise Exception(
                    "StripeWebhookQueueOverflow: webhook event queue size "
                    "exceeded 50000 entries — possible memory leak in "
                    "stripe.WebhookHandler (stripe-python 7.0.0)"
                )
            except Exception as exc:
                sentry_sdk.capture_exception(exc)

        for _ in range(8):
            try:
                raise Exception(
                    "PodRestartLoop: payment-service restarted 8 times "
                    "in last 45 minutes — OOMKilled on each restart"
                )
            except Exception as exc:
                sentry_sdk.capture_exception(exc)

        sentry_sdk.flush()
        print("✓ Sentry errors sent — 51 total errors")
    except Exception as exc:
        print(f"✗ Sentry step failed: {exc}")
    finally:
        time.sleep(2)


def post_slack_messages():
    print("\n[3/5] Posting Slack messages...")
    try:
        client = WebClient(token=os.getenv("SLACK_TOKEN"))
        deploys = [
            "🚀 Deploy started: payment-service v2.4.3 → production by @priya.dev",
            "📝 PR merged: 'deps: upgrade stripe-python from 5.4.0 to 7.0.0' by @priya.dev — requirements.txt changed",
            "✅ Deploy complete: payment-service v2.4.3 live on all nodes",
            "📊 Staging showed no issues — memory stable at 45% for 2h soak test",
        ]
        alerts = [
            "🟡 WARNING: payment-service memory usage 78% — threshold 75%",
            "🔴 ALERT: payment-service memory usage 91% — threshold 85% — pod 1/3",
            "🔴 ALERT: payment-service OOMKilled — pod payment-service-7d9f8b-xk2p9 restarted",
            "🔴 ALERT: payment-service OOMKilled — pod payment-service-7d9f8b-mn4r1 restarted",
            "🔴 ALERT: payment-service OOMKilled — pod payment-service-7d9f8b-qw8t3 restarted (3rd restart)",
        ]
        incidents = [
            "🚨 Incident opened: payment-service pods OOMKilling repeatedly — PagerDuty P1",
            "All 3 pods have restarted at least twice in last 45 minutes",
            "Memory grows steadily after each restart — classic memory leak pattern",
            "No config changes recently — checking dependency upgrades",
            "Found it: stripe-python upgraded from 5.4 to 7.0 in deploy 2h ago",
            "Googling stripe-python 7.0 memory leak — found GitHub issue #1847 in stripe/stripe-python",
            "Confirmed: stripe 7.0.0 has a known webhook queue memory leak — fix in 7.0.1",
            "Options: rollback to 5.4 or pin to 7.0.1 — recommending rollback to unblock",
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
        print("✓ Slack messages posted")
    except Exception as exc:
        print(f"✗ Slack step failed: {exc}")
    finally:
        time.sleep(2)


def trigger_pagerduty():
    print("\n[4/5] Triggering PagerDuty incident...")
    try:
        response = request_json(
            "POST",
            "https://events.pagerduty.com/v2/enqueue",
            headers={"Content-Type": "application/json"},
            json={
                "routing_key": os.getenv("PAGERDUTY_PAYMENT_SERVICE_INTEGRATION_KEY"),
                "event_action": "trigger",
                "payload": {
                    "summary": "payment-service OOMKilled repeatedly — memory leak after stripe-python upgrade",
                    "severity": "critical",
                    "source": "kubernetes-prod",
                    "custom_details": {
                        "service": "payment-service",
                        "pod_restarts_last_hour": "8",
                        "memory_at_oom": "512Mi / 512Mi (100%)",
                        "heap_usage_before_kill": "94%",
                        "restart_pattern": "memory grows 15% every 8 minutes",
                        "last_deploy": "payment-service v2.4.3 — stripe-python 5.4→7.0",
                        "environment": "production",
                    },
                },
            },
        )
        dedup_key = response.get("dedup_key", "")
        if dedup_key:
            with open("/tmp/scenario_2_dedup_key.txt", "w", encoding="utf-8") as handle:
                handle.write(dedup_key)
        print("✓ PagerDuty incident triggered")
    except Exception as exc:
        print(f"✗ PagerDuty step failed: {exc}")


def print_summary(pr_number):
    print(
        f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENARIO 2 SEEDED — Memory Leak / SDK Upgrade
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub PR:  #{pr_number} merged to main
Sentry:     51 errors — OOMKilled, WebhookQueueOverflow
Slack:      Memory leak investigation thread in #incidents
PagerDuty:  Incident triggered (critical)

EXPECTED REPORT OUTPUT:
Root cause → PR #{pr_number}: stripe-python 5.4→7.0 upgrade
Evidence   → 31x OOMKilled + 12x WebhookQueueOverflow in Sentry
             Deploy in #deploys matches incident timeline
             Engineers identified root cause in #incidents
Confidence → HIGH
3rd party  → Stripe operational (SDK issue not service issue)

The agent will investigate in ~30 seconds.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    )


def main():
    print("Scenario 2 — Memory Leak from Dependency Upgrade")
    pr_number = create_and_merge_pr()
    post_slack_messages()
    trigger_pagerduty()
    print_summary(pr_number)


if __name__ == "__main__":
    main()
