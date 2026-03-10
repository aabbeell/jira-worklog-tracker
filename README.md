# Jira Worklog Tracker

Napi bot, ami ellenőrzi a Jira worklogokat és Slack DM-ben értesíti azokat, akik nem logoltak 8 órát.

## Hogyan működik

1. Lekéri a Jira API-n keresztül az aznapi worklogokat (összes project)
2. Összesíti személyenként: ki melyik ticketekre hány órát logolt
3. Akinek nincs meg a 8 óra, annak privát Slack üzenetet küld az összesítéssel

## Setup

### 1. Jira API Token

1. Menj ide: https://id.atlassian.com/manage-profile/security/api-tokens
2. "Create API token" → másold ki

### 2. Slack App

1. Menj ide: https://api.slack.com/apps → "Create New App" → "From scratch"
2. OAuth & Permissions → Bot Token Scopes:
   - `chat:write` - üzenet küldés
   - `im:write` - DM channel nyitás
3. Install to Workspace → másold ki a "Bot User OAuth Token"-t (xoxb-...)

### 3. User Mapping

JSON formátumú mapping a Jira account ID-k és Slack user ID-k között:

```json
{"jira_account_id_1": "SLACK_USER_ID_1", "jira_account_id_2": "SLACK_USER_ID_2"}
```

**Jira Account ID megtalálása:**
- Jira user profil URL-ben: `https://yoursite.atlassian.net/jira/people/ACCOUNT_ID`
- Vagy API: `GET /rest/api/3/user/search?query=username`

**Slack User ID megtalálása:**
- Slack desktop → user profil → "..." menü → "Copy member ID"

### 4. GitHub Secrets

A repo Settings → Secrets and variables → Actions → New repository secret:

| Secret | Leírás | Példa |
|--------|--------|-------|
| `JIRA_BASE_URL` | Jira instance URL | `https://yourcompany.atlassian.net` |
| `JIRA_EMAIL` | Jira user email | `you@company.com` |
| `JIRA_API_TOKEN` | Jira API token | `ATATT3x...` |
| `SLACK_BOT_TOKEN` | Slack bot token | `xoxb-...` |
| `USER_MAPPING` | JSON mapping | `{"abc123": "U0123ABC"}` |

## Futtatás

### Automatikus (GitHub Actions)
Hétfőtől péntekig 17:00 CET-kor automatikusan fut. Kézzel is indítható: Actions → Jira Worklog Tracker → Run workflow.

### Lokális teszt
```bash
export JIRA_BASE_URL="https://yourcompany.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your_token"
export SLACK_BOT_TOKEN="xoxb-your-token"
export USER_MAPPING='{"jira_id": "slack_id"}'

pip install -r requirements.txt
python worklog_tracker.py --dry-run
```

### Paraméterek
- `--dry-run` — Csak kiírja az üzeneteket, nem küld Slack DM-et
- `--date YYYY-MM-DD` — Adott napot ellenőriz (alapértelmezett: ma)
