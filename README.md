![Hackathon](https://img.shields.io/badge/Pirates_of_the_Coral--bean-2025-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Coral](https://img.shields.io/badge/powered_by-Coral_SQL-orange)

# DevOps War Room

<a href="https://www.youtube.com/watch?v=k_uoO7MIY84" target="_blank" rel="noopener noreferrer">
  <img src="https://img.youtube.com/vi/k_uoO7MIY84/hqdefault.jpg" alt="DevOps War Room demo video" width="560" />
</a>

Autonomous incident commander for production incidents. The agent watches PagerDuty, correlates data across Coral sources, checks Stripe Statuspage, generates a specific root-cause report with Groq, posts it to Slack, and renders the investigation in a professional web dashboard with an incident timeline.

## What It Does

- Detects active PagerDuty incidents for `payment-service`.
- Queries GitHub, Sentry, Slack, Grafana, PagerDuty, and Statuspage through Coral SQL.
- Uses Stripe public status data to separate internal regressions from vendor outages.
- Generates plain-text incident reports with root cause, evidence, actions, and confidence.
- Shows incident reports and a timeline view in the dashboard at `http://localhost:8000`.
- Provides two realistic end-to-end demo scenarios that seed every source.

## Architecture

```text
PagerDuty incident
      ↓
Python agent
      ↓
Coral SQL source checks
      ↓
GitHub + Sentry + Slack + Grafana + Statuspage
      ↓
Groq report generation
      ↓
Slack report + Dashboard timeline
```

## Sources

| Source | What the agent uses |
| --- | --- |
| PagerDuty | Triggered incidents and service urgency |
| GitHub | Recent merged PRs for `dhupthumbadiya2005/demo-payment-service` |
| Sentry | `payment-service` issue titles, levels, counts, and first/last seen times |
| Slack | `#incidents`, `#alerts`, and `#deploys` channel context |
| Grafana | Payment service alert rule titles and firing signals |
| Statuspage | Stripe public status showing vendor health |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` with these values:

```bash
GITHUB_TOKEN=...
SLACK_TOKEN=...
SENTRY_DSN=...
PAGERDUTY_PAYMENT_SERVICE_INTEGRATION_KEY=...
GROQ_API_KEY=...
GITHUB_USERNAME=dhupthumbadiya2005
GITHUB_REPO=demo-payment-service
SLACK_CHANNEL=incidents
```

Add the Coral sources:

```bash
coral source add --interactive pagerduty
coral source add --interactive github
coral source add --interactive sentry
coral source add --interactive slack
coral source add --interactive grafana

STATUSPAGE_BASE_URL="https://status.stripe.com" \
  coral source add --file ./sources/statuspage/manifest.yaml
```

Verify every source before a demo:

```bash
python scripts/test_all_sources.py
```

## Run The App

Start the dashboard:

```bash
uvicorn dashboard.server:app --reload --port 8000
```

Start the incident agent in another terminal:

```bash
python agent/main.py
```

Open the dashboard:

```text
http://localhost:8000
```

## Demo Scenarios

Scenario 1 creates a bad deploy that reduces payment gateway timeout from 30s to 3s, sends timeout errors to Sentry, posts deploy/alert/incident Slack context, and triggers PagerDuty.

```bash
bash scripts/run_scenario.sh 1
```

Scenario 2 upgrades `stripe-python` from 5.4.0 to 7.0.0, simulates OOMKilled and webhook queue overflow errors, posts memory-leak Slack context, and triggers PagerDuty.

```bash
bash scripts/run_scenario.sh 2
```

Clean up triggered incidents and stale local reports:

```bash
bash scripts/run_scenario.sh clean
```

## Script Inventory

| Script | Purpose |
| --- | --- |
| `scripts/test_all_sources.py` | Read-only Coral source diagnostic across all sources |
| `scripts/scenario_1_bad_deploy.py` | Seeds the timeout cascade incident |
| `scripts/scenario_2_memory_leak.py` | Seeds the SDK memory leak incident |
| `scripts/cleanup_scenarios.py` | Resolves scenario PagerDuty incidents and deletes stale reports |
| `scripts/run_scenario.sh` | Master runner for scenarios and cleanup |

## Dashboard

The dashboard includes:

- Live Feed: current incident reports and source coverage.
- Timeline: deploys, alerts, Sentry errors, Slack updates, and report generation in order.
- Report: structured root cause, evidence, third-party status, actions, and confidence.
- Sources: Coral connectivity and table availability.

## Built For

Pirates of the Coral-bean Hackathon  
WeMakeDevs x Coral
