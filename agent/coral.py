"""
DevOps War Room — Coral SQL integration.

Handles all Coral SQL queries, schema discovery, and source inspection.
Every function that talks to the Coral CLI lives here.
"""

import subprocess

# Import mutable config globals that discover_source_columns() updates
import config


def run_coral_query(sql: str, timeout: int = 30) -> str:
    """Run a Coral SQL query through the CLI and return stdout or an error string."""
    try:
        result = subprocess.run(
            ["coral", "sql", sql],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return f"Query error: {exc}"

    if result.returncode != 0:
        return f"Query error: {result.stderr.strip()}"
    return result.stdout.strip()


# ── Schema Discovery ──────────────────────────────────────────────────────


def discover_source_columns() -> None:
    """Discover correct table and column names from Coral at startup.

    This makes the agent self-healing — if Coral updates a source spec and
    renames a column or table, the agent discovers it automatically on next
    startup instead of silently failing with wrong column names.
    """
    print("\nDiscovering source schemas from Coral...")

    # Discover Slack table name (should be 'channels')
    print("  → Checking Slack tables...")
    output = run_coral_query("SELECT table_name FROM coral.tables WHERE schema_name = 'slack'")
    if not output.startswith("Query error:"):
        tables = [
            line.strip()
            for line in output.split("\n")
            if line.strip() and "table_name" not in line and "---" not in line
        ]
        if tables:
            config.SLACK_TABLE = tables[0].strip()
            print(f"    Slack table: {config.SLACK_TABLE}")

    # Discover Slack channel column (should be 'name')
    print("  → Checking Slack columns...")
    output = run_coral_query(
        f"SELECT column_name FROM coral.columns "
        f"WHERE schema_name = 'slack' AND table_name = '{config.SLACK_TABLE}'"
    )
    if not output.startswith("Query error:"):
        columns = [
            line.strip()
            for line in output.split("\n")
            if line.strip() and "column_name" not in line and "---" not in line
        ]
        for col in columns:
            if col.strip().lower() in ("name", "channel_name"):
                config.SLACK_CHANNEL_COL = col.strip()
                print(f"    Slack channel column: {config.SLACK_CHANNEL_COL}")
                break

    # Discover Sentry org/project column (should be 'project')
    print("  → Checking Sentry columns...")
    output = run_coral_query(
        "SELECT column_name FROM coral.columns WHERE schema_name = 'sentry' AND table_name = 'issues'"
    )
    if not output.startswith("Query error:"):
        columns = [
            line.strip()
            for line in output.split("\n")
            if line.strip() and "column_name" not in line and "---" not in line
        ]
        for col in columns:
            if col.strip().lower() in ("project", "project_slug", "org_slug"):
                config.SENTRY_ORG_COL = col.strip()
                print(f"    Sentry org column: {config.SENTRY_ORG_COL}")
                break

    # Discover Grafana columns
    print("  → Checking Grafana columns...")
    output = run_coral_query(
        "SELECT column_name FROM coral.columns WHERE schema_name = 'grafana' AND table_name = 'alert_rules'"
    )
    if not output.startswith("Query error:"):
        columns = [
            line.strip()
            for line in output.split("\n")
            if line.strip() and "column_name" not in line and "---" not in line
        ]
        col_lower = [c.strip().lower() for c in columns]
        if "title" in col_lower:
            config.GRAFANA_TITLE_COL = "title"
            print("    Grafana title column: title")

        # Build state filter based on available columns
        has_no_data = "no_data_state" in col_lower
        has_exec_err = "exec_err_state" in col_lower
        if has_no_data and has_exec_err:
            config.GRAFANA_STATE_FILTER = "no_data_state != 'OK' OR exec_err_state != 'OK'"
        elif has_no_data:
            config.GRAFANA_STATE_FILTER = "no_data_state != 'OK'"
        elif has_exec_err:
            config.GRAFANA_STATE_FILTER = "exec_err_state != 'OK'"
        print(f"    Grafana state filter: {config.GRAFANA_STATE_FILTER}")

    print("\n  Discovered schema:")
    print(f"    Slack   : {config.SLACK_TABLE}.{config.SLACK_CHANNEL_COL}")
    print(f"    Sentry  : issues.{config.SENTRY_ORG_COL}")
    print(
        f"    Grafana : alert_rules.{config.GRAFANA_TITLE_COL}, "
        f"filter={config.GRAFANA_STATE_FILTER}"
    )
    print()


def inspect_github_tables() -> str:
    """Print the GitHub tables Coral currently exposes."""
    print("\nInspecting GitHub Coral tables...")
    query = "SELECT table_name FROM coral.tables WHERE schema_name = 'github' ORDER BY table_name"
    output = run_coral_query(query)
    print(output)
    return output


# ── Correlation Queries ───────────────────────────────────────────────────


def build_correlation_queries(
    incident_id: str, incident_created_at: str
) -> list[tuple[str, str]]:
    """Build sequential queries for each source, returning (label, query) pairs.

    Instead of one giant JOIN that fails on HTTP-backed sources, this builds
    separate queries for each source that run independently. Results are
    combined into a single context string for the AI.
    """
    three_hours_before = incident_created_at

    queries = [
        (
            "PAGERDUTY DATA",
            f"""SELECT id, title, urgency, status, created_at
FROM pagerduty.incidents
WHERE id = '{incident_id}'
LIMIT 5""",
        ),
        (
            "GITHUB RECENT PRs (last 3 hours)",
            f"""SELECT title, merged_at, user__login, html_url, additions, deletions
FROM github.pulls
WHERE owner = '{config.GITHUB_USERNAME}'
  AND repo = '{config.GITHUB_REPO}'
  AND merged_at >= '{three_hours_before}' - interval '3 hours'
ORDER BY merged_at DESC
LIMIT 10""",
        ),
        (
            "SENTRY ERRORS",
            f"""SELECT title, level, count, first_seen, last_seen
FROM sentry.issues
WHERE {config.SENTRY_ORG_COL} = 'payment-service'
ORDER BY first_seen DESC
LIMIT 10""",
        ),
        (
            "GRAFANA ALERTS",
            f"""SELECT {config.GRAFANA_TITLE_COL}, no_data_state, exec_err_state
FROM grafana.alert_rules
WHERE {config.GRAFANA_STATE_FILTER}
LIMIT 10""",
        ),
    ]
    return queries


def run_correlation_queries(
    incident_id: str, incident_created_at: str
) -> tuple[str, list[str]]:
    """Run all correlation queries sequentially and combine results.

    Returns (combined_data_string, list_of_query_strings).
    Slack is fetched separately via fetch_all_slack_context().
    """
    queries = build_correlation_queries(incident_id, incident_created_at)
    results = []
    query_strings = []

    for label, query in queries:
        print(f"  → {label}...", end=" ", flush=True)
        output = run_coral_query(query)
        query_strings.append(f"-- {label}\n{query.strip()}")
        results.append(f"{label}:\n{output}")
        print("Done")

    combined = "\n\n".join(results)
    return combined, query_strings


# ── Third-Party Status (Statuspage) ───────────────────────────────────────


def check_third_party_status() -> str:
    """Query the custom Statuspage source for third-party health context."""
    queries = {
        "Overall health": "SELECT indicator, description FROM statuspage.status",
        "Degraded components": (
            "SELECT name, status FROM statuspage.components "
            "WHERE status != 'operational'"
        ),
        "Active incidents": (
            "SELECT name, impact, status, shortlink FROM statuspage.active_incidents"
        ),
        "Active maintenance": (
            "SELECT name, status, scheduled_for FROM statuspage.active_maintenances"
        ),
    }
    results = []
    for label, query in queries.items():
        output = run_coral_query(query)
        results.append(f"{label}:\n{output}")
    return "\n\n".join(results)
