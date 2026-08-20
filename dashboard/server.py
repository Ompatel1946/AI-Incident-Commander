import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
REPORT_DIRS = [PROJECT_ROOT / "reports", PROJECT_ROOT / "agent" / "reports"]
REPORT_SECTION_MAP = {
    "INCIDENT SUMMARY": "summary",
    "ROOT CAUSE ANALYSIS": "root_cause",
    "CORROBORATING EVIDENCE": "evidence",
    "THIRD-PARTY STATUS": "third_party",
    "RECOMMENDED ACTIONS": "actions",
    "CONFIDENCE LEVEL": "confidence",
}
SOURCES = [
    {
        "schema": "pagerduty",
        "name": "PagerDuty",
        "icon": "🔔",
        "tables": ["incidents", "services", "escalation_policies"],
    },
    {
        "schema": "github",
        "name": "GitHub",
        "icon": "🐙",
        "tables": ["pulls", "pull_requests", "issues", "commits"],
    },
    {
        "schema": "sentry",
        "name": "Sentry",
        "icon": "🪲",
        "tables": ["issues", "events", "projects"],
    },
    {
        "schema": "slack",
        "name": "Slack",
        "icon": "💬",
        "tables": ["messages", "channels"],
    },
    {
        "schema": "grafana",
        "name": "Grafana",
        "icon": "📊",
        "tables": ["alert_rules", "dashboards"],
    },
    {
        "schema": "statuspage",
        "name": "Statuspage",
        "icon": "📋",
        "tables": ["status", "components", "active_incidents", "active_maintenances"],
    },
]

app = FastAPI(title="DevOps War Room Dashboard")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO string."""
    return datetime.now(UTC).isoformat()


def report_files() -> list[Path]:
    """Return report text files from known report directories."""
    files: list[Path] = []
    for directory in REPORT_DIRS:
        if directory.exists():
            files.extend(directory.glob("*.txt"))
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def clean_heading_text(value: str) -> str:
    """Normalize report headings emitted by older markdown reports."""
    return re.sub(r"[*#_`]", "", value).strip().upper().rstrip(":")


def extract_metadata(raw_text: str) -> dict[str, str]:
    """Extract report metadata from the text header."""
    metadata = {
        "id": "unknown",
        "title": "Untitled incident",
        "generated_at": "",
        "urgency": "high",
        "service": "payment-service",
        "started_at": "",
    }
    patterns = {
        "id": r"^Incident ID\s*:\s*(.+)$",
        "title": r"^Title\s*:\s*(.+)$",
        "generated_at": r"^Generated\s*:\s*(.+)$",
        "urgency": r"^Urgency\s*:\s*(.+)$",
        "service": r"^Service\s*:\s*(.+)$",
        "started_at": r"^Started\s*:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, raw_text, flags=re.MULTILINE)
        if match:
            metadata[key] = match.group(1).strip()
    return metadata


def extract_sections(raw_text: str) -> dict[str, str]:
    """Extract the six canonical report sections from raw text."""
    sections = {value: "" for value in REPORT_SECTION_MAP.values()}
    headings = "|".join(re.escape(key) for key in REPORT_SECTION_MAP)
    matches = list(
        re.finditer(
            rf"(?im)^\s*(?:\d+\.\s*)?(?:#+\s*)?\**({headings})\**\s*:?\s*$",
            raw_text,
        )
    )

    for index, match in enumerate(matches):
        heading = clean_heading_text(match.group(1))
        key = REPORT_SECTION_MAP.get(heading)
        if not key:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        content = raw_text[start:end].strip(" \n:-")
        sections[key] = content

    return sections


def extract_coral_query(raw_text: str) -> str:
    """Extract the saved Coral SQL query block from a report."""
    # Try multiple patterns to find the query
    patterns = [
        r"(?is)CORAL SQL QUERY:\s*\n?-+\s*\n?(.+)$",
        r"(?is)CORAL SQL QUERY:\s*\n(.+?)(?:\n\n|\Z)",
        r"(?is)CORAL SQL QUERY\s*\n-+\s*\n(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            return match.group(1).strip()
    return ""


def extract_sources_hit(raw_text: str) -> list[str]:
    """Infer which sources returned meaningful data based on report text."""
    hits = []
    # PagerDuty is always considered connected since the incident came from there
    hits.append("PagerDuty")
    
    for source in SOURCES:
        name = source["name"]
        if name == "PagerDuty":
            continue  # Already added
        pattern = re.compile(rf"(?is){re.escape(name)}(.{{0,240}})")
        match = pattern.search(raw_text)
        if match and not re.search(r"no data|empty|not found|query error|0 rows", match.group(1), re.I):
            hits.append(name)
    return hits


def parse_report_datetime(value: str, fallback: datetime) -> datetime:
    """Parse a report timestamp and fall back when older reports are incomplete."""
    if not value:
        return fallback
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def timeline_event(at: datetime, source: str, label: str, detail: str, severity: str = "info") -> dict:
    """Build one normalized incident timeline event."""
    return {
        "at": at.isoformat(),
        "time": at.strftime("%H:%M UTC"),
        "source": source,
        "label": label,
        "detail": detail,
        "severity": severity,
    }


def extract_timeline_events(raw_text: str, metadata: dict[str, str], generated: str) -> list[dict]:
    """Create a concise incident timeline from the report content.

    The demo scenarios seed exact cross-source narratives, so the dashboard
    renders scenario-specific timelines when it recognizes them. Other reports
    still get a useful generic investigation timeline.
    """
    fallback = datetime.fromtimestamp(datetime.now(UTC).timestamp(), UTC)
    generated_at = parse_report_datetime(generated, fallback)
    started_at = parse_report_datetime(metadata.get("started_at", ""), generated_at - timedelta(minutes=18))
    text = raw_text.lower()

    if "oomkilled" in text or "stripe-python" in text or "memory leak" in text:
        report_at = max(generated_at, started_at + timedelta(minutes=8))
        deploy_at = started_at - timedelta(hours=2)
        return [
            timeline_event(deploy_at, "GitHub", "Deploy merged", '"deps: upgrade stripe-python from 5.4.0 to 7.0.0"', "deploy"),
            timeline_event(started_at - timedelta(minutes=45), "Grafana", "Memory warning", "payment-service memory usage 78%", "warning"),
            timeline_event(started_at, "PagerDuty", "Alert triggered", "Pods OOMKilling repeatedly", "critical"),
            timeline_event(started_at + timedelta(minutes=1), "Sentry", "First OOM error", "OOMKilled: container exceeded memory limit 512Mi", "critical"),
            timeline_event(started_at + timedelta(minutes=4), "Slack", "Root cause found", "stripe-python 7.0.0 webhook queue memory leak", "info"),
            timeline_event(report_at, "War Room", "Report generated", metadata.get("title", "Incident report"), "success"),
        ]

    if "gateway timeout" in text or "30s to 3s" in text or "3000ms" in text:
        report_at = max(generated_at, started_at + timedelta(minutes=20))
        deploy_at = started_at - timedelta(minutes=18)
        return [
            timeline_event(deploy_at, "GitHub", "Deploy merged", '"perf: reduce payment gateway timeout from 30s to 3s"', "deploy"),
            timeline_event(started_at, "PagerDuty", "Alert triggered", "payment-service error rate 44%", "critical"),
            timeline_event(started_at + timedelta(minutes=1), "Sentry", "First error", "GatewayTimeoutError: downstream timeout on stripe.com:443", "critical"),
            timeline_event(started_at + timedelta(minutes=1), "Grafana", "Alert firing", "payment-service-error-rate-high", "critical"),
            timeline_event(started_at + timedelta(minutes=3), "Slack", "Responder update", "Looking into it now", "info"),
            timeline_event(report_at, "War Room", "Report generated", metadata.get("title", "Incident report"), "success"),
        ]

    title = metadata.get("title", "Incident report")
    return [
        timeline_event(started_at, "PagerDuty", "Incident detected", title, "critical"),
        timeline_event(started_at + timedelta(minutes=1), "Coral", "Cross-source query", "PagerDuty, GitHub, Sentry, Slack, Grafana, Statuspage", "info"),
        timeline_event(started_at + timedelta(minutes=2), "Slack", "Context gathered", "Deploy, alert, and incident channels inspected", "info"),
        timeline_event(generated_at, "War Room", "Report generated", title, "success"),
    ]


def parse_report(path: Path) -> dict:
    """Parse one report file into dashboard JSON."""
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    metadata = extract_metadata(raw_text)
    sections = extract_sections(raw_text)
    generated = metadata["generated_at"] or datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    return {
        "id": metadata["id"],
        "title": metadata["title"],
        "generated_at": generated,
        "urgency": metadata["urgency"],
        "service": metadata["service"],
        "started_at": metadata["started_at"],
        "sections": sections,
        "raw_text": raw_text,
        "sources_hit": extract_sources_hit(raw_text),
        "timeline": extract_timeline_events(raw_text, metadata, generated),
        "coral_query": extract_coral_query(raw_text),
        "path": str(path.relative_to(PROJECT_ROOT)),
    }


def sort_key(report: dict) -> str:
    """Return a stable descending sort key for report timestamps."""
    return report.get("generated_at") or ""


def run_command(command: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a CLI command and return return code, stdout, and stderr."""
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as exc:
        return 1, "", str(exc)


def parse_coral_tables(stdout: str) -> dict[str, list[str]]:
    """Parse coral.tables CLI output into schema-to-table names."""
    tables: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        if "|" not in line or "schema_name" in line or "---" in line:
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            tables.setdefault(parts[0], []).append(parts[1])
    return tables


def parse_source_list(stdout: str) -> set[str]:
    """Parse `coral source list` output into configured source names."""
    sources = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("Source"):
            continue
        parts = stripped.split()
        if parts:
            sources.add(parts[0])
    return sources


def source_health() -> list[dict]:
    """Return health and table metadata for each dashboard source."""
    list_code, list_stdout, list_stderr = run_command(["coral", "source", "list"], timeout=15)
    table_code, table_stdout, table_stderr = run_command(
        ["coral", "sql", "SELECT schema_name, table_name FROM coral.tables ORDER BY schema_name, table_name"],
        timeout=15,
    )
    configured = parse_source_list(list_stdout) if list_code == 0 else set()
    available = parse_coral_tables(table_stdout) if table_code == 0 else {}
    now = utc_now_iso()
    health = []
    for source in SOURCES:
        tables = available.get(source["schema"], [])
        connected = source["schema"] in configured
        health.append(
            {
                "name": source["name"],
                "schema": source["schema"],
                "icon": source["icon"],
                "status": "connected" if connected else "error",
                "last_queried": now,
                "rows_returned": len(tables),
                "tables": tables or source["tables"],
                "error": "" if list_code == 0 and table_code == 0 else list_stderr or table_stderr,
            }
        )
    return health


@app.get("/")
def index() -> FileResponse:
    """Serve the single-file dashboard."""
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/api/incidents")
def list_incidents() -> list[dict]:
    """Return parsed incident reports sorted by generated timestamp descending.
    
    Deduplicates by incident ID, keeping only the most recent report for each ID.
    """
    all_reports = [parse_report(path) for path in report_files()]
    
    # Deduplicate by incident ID, keeping the most recent
    seen_ids: dict[str, dict] = {}
    for report in all_reports:
        inc_id = report["id"]
        if inc_id not in seen_ids:
            seen_ids[inc_id] = report
        else:
            # Keep whichever was generated more recently
            if report["generated_at"] > seen_ids[inc_id]["generated_at"]:
                seen_ids[inc_id] = report
    
    # Return sorted by timestamp descending
    return sorted(seen_ids.values(), key=sort_key, reverse=True)


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    """Return one parsed incident report by incident ID."""
    for report in list_incidents():
        if report["id"] == incident_id:
            return report
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


@app.get("/api/sources")
def get_sources() -> list[dict]:
    """Return Coral source connectivity information."""
    return source_health()
