"""
DevOps War Room — Utility functions.

Time helpers, text normalization, and report section parsing.
"""

import re
from datetime import UTC, datetime

from config import REPORT_SECTIONS


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def truncate_for_slack(value: str, limit: int = 3000) -> str:
    """Trim text to Slack's per-section text limit."""
    clean_value = value.strip()
    if len(clean_value) <= limit:
        return clean_value
    return clean_value[: limit - 3].rstrip() + "..."


def normalize_report_text(report: str) -> str:
    """Remove common markdown markers from model output before parsing."""
    cleaned = report.replace("**", "").replace("__", "")
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    cleaned = re.sub(r"`(.*?)`", r"\1", cleaned)
    return cleaned.strip()


def parse_report_sections(report: str) -> dict[str, str]:
    """Extract the six expected incident-report sections from plain text."""
    cleaned = normalize_report_text(report)
    section_pattern = "|".join(re.escape(section) for section in REPORT_SECTIONS)
    matches = list(
        re.finditer(
            rf"(?im)^\s*(?:\d+\.\s*)?({section_pattern})\s*:?\s*$",
            cleaned,
        )
    )
    sections = {section: "" for section in REPORT_SECTIONS}

    for index, match in enumerate(matches):
        heading = match.group(1).upper()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        sections[heading] = cleaned[start:end].strip(" \n:-")

    if not any(sections.values()):
        sections["INCIDENT SUMMARY"] = cleaned

    return sections
