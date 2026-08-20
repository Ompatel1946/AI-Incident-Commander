"""
DevOps War Room — Report generation and persistence.

Handles:
- Generating incident reports with Groq LLM
- Saving reports to the local filesystem
"""

import os

import config
from utils import normalize_report_text, utc_now


def generate_report(incident: dict, correlation_data: str, statuspage_data: str) -> str:
    """Generate a structured plain-text incident report with Groq."""
    prompt = f"""
Do not use markdown formatting. Do not use **bold**, *italic*, or any markdown syntax.
Use plain text only. Use ALL CAPS for section headers exactly as specified.

You are an autonomous incident commander. A production incident has fired.
Analyze the correlated data from 5 monitoring sources and produce a structured
incident report with root cause analysis.

INCIDENT DETAILS
----------------
ID       : {incident['id']}
Title    : {incident['title']}
Urgency  : {incident['urgency']}
Status   : {incident['status']}
Service  : {incident.get('service', {}).get('summary', 'unknown')}
Started  : {incident.get('created_at', 'unknown')}

CORRELATED DATA FROM 5 SOURCES (PagerDuty + GitHub + Sentry + Slack + Grafana)
--------------------------------------------------------------------------------
{correlation_data}

WHAT YOU ARE RECEIVING:
- Slack messages from THREE channels:
  * #deploys: deployment announcements — if this shows a deploy
    of the affected service within 2 hours of the incident,
    that deploy is your PRIMARY root cause suspect
  * #incidents: human responder observations and commentary
  * #alerts: automated monitoring alert messages

CRITICAL RULE: If #deploys shows a recent deploy and Sentry
shows errors that started at the same time, the deploy IS the
root cause. State this directly. Do not hedge with "possibly"
or "may have". Name the exact deploy, the engineer who pushed
it, and the PR title if visible.

THIRD-PARTY VENDOR STATUS (Statuspage)
--------------------------------------
{statuspage_data}

Write a structured incident report with these exact sections:

INCIDENT SUMMARY:
One paragraph explaining what happened, when, and what is affected.

ROOT CAUSE ANALYSIS:
Most likely cause based on the data. Be specific. Name the exact PR, error
message, component, or signal responsible. If multiple causes are possible,
rank them.

CORROBORATING EVIDENCE:
Use simple dash (-) bullets only. List evidence from each source that supports
the root cause conclusion.

THIRD-PARTY STATUS:
State whether any vendor outage is contributing or whether this is internal.

RECOMMENDED ACTIONS:
Use numbered lines. Most urgent first. Include exact commands where possible.

CONFIDENCE LEVEL:
High / Medium / Low, followed by one sentence explaining why.

Be direct and specific. Avoid generic advice. Time is critical.
"""

    response = config.groq_client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert site reliability engineer and incident commander. "
                    "You analyze production incidents using correlated data from multiple "
                    "monitoring tools and generate precise, actionable incident reports. "
                    "You respond in plain text only. No markdown. No asterisks. "
                    "No bullet symbols other than a simple dash (-). Section headers "
                    "are written in ALL CAPS followed by a colon and newline."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=1500,
    )
    return response.choices[0].message.content


def save_report(incident: dict, report: str, query_strings: list[str]) -> str:
    """Save the incident report and all query contexts under the project reports directory."""
    os.makedirs("reports", exist_ok=True)
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/incident_{incident['id']}_{timestamp}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Incident ID : {incident['id']}\n")
        f.write(f"Title       : {incident['title']}\n")
        f.write(f"Urgency     : {incident.get('urgency', 'unknown')}\n")
        f.write(f"Service     : {incident.get('service', {}).get('summary', 'unknown')}\n")
        f.write(f"Started     : {incident.get('created_at', 'unknown')}\n")
        f.write(f"Generated   : {utc_now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")
        f.write(normalize_report_text(report))
        f.write("\n\nCORAL SQL QUERIES\n")
        f.write("-" * 60 + "\n")
        f.write("\n\n".join(query_strings))
        f.write("\n")
    print(f"  → Report saved to {filename}")
    return filename
