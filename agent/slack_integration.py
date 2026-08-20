"""
DevOps War Room — Slack integration.

Handles:
- Fetching messages from Slack channels via Coral table function
- Building Slack Block Kit payloads for incident reports
- Posting reports to Slack
"""

import config
from coral import run_coral_query
from utils import parse_report_sections, truncate_for_slack


# ── Slack Channel Message Fetching ────────────────────────────────────────


def fetch_slack_channel(channel_name: str, limit: int = 10) -> str:
    """Fetch recent messages from a Slack channel using Coral's
    slack.messages() table function. Requires channel ID not name.
    Returns formatted string of messages or error description.
    """
    channel_id = config.SLACK_CHANNEL_IDS.get(channel_name)
    if not channel_id:
        return f"#{channel_name}: channel ID not configured"

    sql = f"""
    SELECT text, ts
    FROM slack.messages(channel => '{channel_id}')
    ORDER BY ts DESC
    LIMIT {limit}
    """
    result = run_coral_query(sql)

    if "error" in result.lower() or "Error" in result:
        return f"#{channel_name}: {result}"

    return f"#{channel_name}:\n{result}"


def fetch_all_slack_context() -> str:
    """Fetch recent messages from all incident-relevant Slack channels.
    Returns combined formatted string for AI context.
    #deploys is most important — recent deploys are the most
    common root cause of production incidents.
    """
    try:
        deploys = fetch_slack_channel("deploys", limit=10)
        incidents = fetch_slack_channel("incidents", limit=10)
        alerts = fetch_slack_channel("alerts", limit=5)

        return (
            "SLACK CONTEXT\n"
            "=============\n\n"
            f"DEPLOYS (check for recent deploys near incident time):\n"
            f"{deploys}\n\n"
            f"INCIDENTS (human responder observations):\n"
            f"{incidents}\n\n"
            f"ALERTS (automated monitoring messages):\n"
            f"{alerts}"
        )
    except Exception as exc:
        return f"SLACK CONTEXT: Failed to fetch — {exc}"


# ── Slack Block Kit Report Posting ────────────────────────────────────────


def build_slack_blocks(incident: dict, report: str) -> list[dict]:
    """Build the Slack Block Kit payload for an incident report."""
    from utils import utc_now

    sections = parse_report_sections(report)
    urgency = incident.get("urgency", "unknown").upper()
    generated = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 INCIDENT REPORT — AUTO-GENERATED",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Incident:* {truncate_for_slack(incident.get('title', 'Unknown incident'), 250)}",
                },
                {"type": "mrkdwn", "text": f"*Urgency:* {urgency}"},
                {"type": "mrkdwn", "text": f"*Generated:* {generated}"},
            ],
        },
        {"type": "divider"},
    ]

    for heading in config.REPORT_SECTIONS:
        content = sections.get(heading) or "No details provided."
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": truncate_for_slack(f"*{heading}*\n{content}"),
                },
            }
        )

    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Powered by Coral SQL cross-source JOIN across "
                            "PagerDuty · GitHub · Sentry · Slack · Grafana · Statuspage"
                        ),
                    }
                ],
            },
        ]
    )
    return blocks


def post_report_to_slack(incident: dict, report: str) -> bool:
    """Post a structured Block Kit report to Slack."""
    try:
        config.slack_client.chat_postMessage(
            channel=config.SLACK_CHANNEL,
            blocks=build_slack_blocks(incident, report),
        )
    except Exception as exc:
        print(f"  → Slack post failed: {exc}")
        return False

    print(f"  → Report posted to #{config.SLACK_CHANNEL}")
    return True
