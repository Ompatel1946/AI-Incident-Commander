"""
DevOps War Room — Configuration and client initialization.

All environment variables, API clients, and runtime-discovered
schema constants live here so every module can import them.
"""

import os
import ssl

import certifi
import requests
from dotenv import load_dotenv
from groq import Groq
from slack_sdk import WebClient

load_dotenv()

# ── API Clients ────────────────────────────────────────────────────────────
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
ssl_context = ssl.create_default_context(cafile=certifi.where())
slack_client = WebClient(token=os.getenv("SLACK_TOKEN"), ssl=ssl_context)

# ── Environment Config ─────────────────────────────────────────────────────
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "dhupthumbadiya2005")
GITHUB_REPO = os.getenv("GITHUB_REPO", "demo-payment-service")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "incidents")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Report Section Headers ─────────────────────────────────────────────────
REPORT_SECTIONS = [
    "INCIDENT SUMMARY",
    "ROOT CAUSE ANALYSIS",
    "CORROBORATING EVIDENCE",
    "THIRD-PARTY STATUS",
    "RECOMMENDED ACTIONS",
    "CONFIDENCE LEVEL",
]

# ── Runtime-discovered Source Schema (populated at startup by coral.py) ────
SLACK_TABLE = "channels"
SLACK_CHANNEL_COL = "name"
SENTRY_ORG_COL = "project"
GRAFANA_TITLE_COL = "title"
GRAFANA_STATE_FILTER = "no_data_state != 'OK' OR exec_err_state != 'OK'"

# ── Slack Channel IDs — looked up once, hardcoded for performance ──────────
# Run: coral sql "SELECT id, name FROM slack.channels" to refresh.
SLACK_CHANNEL_IDS: dict[str, str] = {
    "incidents": "C0B5WAQU8UW",
    "alerts": "C0B621BD0TE",
    "deploys": "C0B621GA3A8",
}
