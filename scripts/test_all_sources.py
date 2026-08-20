# Source diagnostic — verifies every Coral source used by DevOps War Room.
# Purpose: run one fast read-only query per source before a demo scenario.
# Run: python scripts/test_all_sources.py

import subprocess
import sys


QUERIES = [
    (
        "PagerDuty — triggered incidents",
        "SELECT id, title FROM pagerduty.incidents WHERE status = 'triggered' LIMIT 3",
    ),
    (
        "GitHub — confirmed payment-service PR query",
        "SELECT title, merged_at, user__login, html_url, additions, deletions "
        "FROM github.pulls "
        "WHERE owner = 'dhupthumbadiya2005' "
        "AND repo = 'demo-payment-service' "
        "ORDER BY merged_at DESC LIMIT 5",
    ),
    (
        "Sentry — confirmed payment-service issue query",
        "SELECT title, level, count, first_seen, last_seen "
        "FROM sentry.issues "
        "WHERE project = 'payment-service' "
        "ORDER BY first_seen DESC LIMIT 10",
    ),
    (
        "Slack — #incidents messages",
        "SELECT text, ts FROM slack.messages(channel => 'C0B5WAQU8UW') LIMIT 3",
    ),
    (
        "Slack — #alerts messages",
        "SELECT text, ts FROM slack.messages(channel => 'C0B621BD0TE') LIMIT 3",
    ),
    (
        "Slack — #deploys messages",
        "SELECT text, ts FROM slack.messages(channel => 'C0B621GA3A8') LIMIT 3",
    ),
    (
        "Grafana — expected payment-service alert rules",
        "SELECT title FROM grafana.alert_rules "
        "WHERE title IN ("
        "'payment-service-error-rate-high', "
        "'payment-service-latency-p99-high', "
        "'payment-service-connection-pool-exhausted'"
        ") LIMIT 10",
    ),
    (
        "Statuspage — Stripe public status",
        "SELECT indicator, description FROM statuspage.status",
    ),
]


def run(sql, label):
    result = subprocess.run(
        ["coral", "sql", sql],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    ok = result.returncode == 0 and result.stderr.strip() == ""
    status = "✓" if ok else "✗"
    print(f"{status} {label}")
    if ok:
        rows = max(0, len([line for line in result.stdout.splitlines() if line.strip()]) - 2)
        print(f"   Rows returned: {rows}")
    else:
        print(f"   Output: {result.stdout[:240]}")
        print(f"   Error:  {result.stderr[:240]}")
    print()
    return ok


def main():
    print("=== DevOps War Room Source Diagnostic ===\n")
    passed = 0
    failed = 0
    for label, sql in QUERIES:
        if run(sql, label):
            passed += 1
        else:
            failed += 1

    print("=" * 44)
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All sources healthy — agent ready for demo")
        sys.exit(0)
    print("Fix failing sources before running a scenario")
    sys.exit(1)


if __name__ == "__main__":
    main()
