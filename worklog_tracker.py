#!/usr/bin/env python3
"""
Jira Worklog Tracker
Checks daily logged hours per person and sends Slack DM if < 8 hours.
"""

import argparse
import json
import os
import ssl
import sys
from datetime import date, datetime, timezone

import certifi
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"Error: {name} environment variable is not set")
        sys.exit(1)
    return value


def get_jira_worklogs(base_url, email, api_token, date_str, blacklisted_projects=None):
    """Fetch all worklogs for the given date across all projects."""
    auth = (email, api_token)
    headers = {"Accept": "application/json"}

    # Search for issues with worklogs on the target date
    jql = f'worklogDate = "{date_str}"'
    if blacklisted_projects:
        excluded = ", ".join(f'"{p}"' for p in blacklisted_projects)
        jql += f" AND project NOT IN ({excluded})"
    max_results = 100
    all_issues = []
    next_page_token = None

    while True:
        body = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["key", "summary"],
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        response = requests.post(
            f"{base_url}/rest/api/3/search/jql",
            json=body,
            auth=auth,
            headers={**headers, "Content-Type": "application/json"},
        )
        if not response.ok:
            print(f"Jira search error {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()
        all_issues.extend(data["issues"])

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    print(f"Found {len(all_issues)} issues with worklogs on {date_str}")

    # Collect worklogs per person
    # Structure: {account_id: {"name": str, "tickets": {key: {"summary": str, "seconds": int}}, "total_seconds": int}}
    people = {}

    for issue in all_issues:
        issue_key = issue["key"]
        issue_summary = issue["fields"]["summary"]

        # Get worklogs for this issue
        wl_response = requests.get(
            f"{base_url}/rest/api/3/issue/{issue_key}/worklog",
            auth=auth,
            headers=headers,
        )
        wl_response.raise_for_status()
        worklogs = wl_response.json().get("worklogs", [])

        for wl in worklogs:
            # Filter for target date
            started = wl["started"][:10]  # "2024-01-15T..." -> "2024-01-15"
            if started != date_str:
                continue

            account_id = wl["author"]["accountId"]
            display_name = wl["author"]["displayName"]
            time_spent_seconds = wl["timeSpentSeconds"]

            if account_id not in people:
                people[account_id] = {
                    "name": display_name,
                    "tickets": {},
                    "total_seconds": 0,
                }

            if issue_key not in people[account_id]["tickets"]:
                people[account_id]["tickets"][issue_key] = {
                    "summary": issue_summary,
                    "seconds": 0,
                }

            people[account_id]["tickets"][issue_key]["seconds"] += time_spent_seconds
            people[account_id]["total_seconds"] += time_spent_seconds

    return people


def get_active_issues(base_url, email, api_token, account_id, blacklisted_projects=None):
    """Fetch issues assigned to a user that are In Progress or To Do."""
    auth = (email, api_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    jql = f'assignee = "{account_id}" AND statusCategory IN ("To Do", "In Progress")'
    if blacklisted_projects:
        excluded = ", ".join(f'"{p}"' for p in blacklisted_projects)
        jql += f" AND project NOT IN ({excluded})"
    jql += " ORDER BY status ASC"
    all_issues = []
    next_page_token = None

    while True:
        body = {
            "jql": jql,
            "maxResults": 50,
            "fields": ["key", "summary", "status", "duedate"],
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        response = requests.post(
            f"{base_url}/rest/api/3/search/jql",
            json=body,
            auth=auth,
            headers=headers,
        )
        if not response.ok:
            print(f"Jira active issues error {response.status_code}: {response.text}")
            return []
        data = response.json()
        all_issues.extend(data["issues"])

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return all_issues


def format_hours(seconds):
    """Format seconds as hours and minutes."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def build_slack_message(person_data, date_str, active_issues=None):
    """Build a Slack message for someone with < 8 hours."""
    missing_seconds = (8 * 3600) - person_data["total_seconds"]

    lines = [
        f":wave: Szia! A mai napra ({date_str}) *{format_hours(person_data['total_seconds'])}* van logolva a Jirában.",
        f"*{format_hours(missing_seconds)}* hiányzik a 8 órából.",
    ]

    if person_data["tickets"]:
        lines.append("")
        lines.append("*Logolt munkák:*")
        for ticket_key, ticket_data in person_data["tickets"].items():
            lines.append(
                f"  • `{ticket_key}` {ticket_data['summary']} — {format_hours(ticket_data['seconds'])}"
            )

    if active_issues:
        in_progress = []
        with_deadline = []
        today = date.today()

        for issue in active_issues:
            key = issue["key"]
            summary = issue["fields"]["summary"]
            category = issue["fields"]["status"]["statusCategory"]["name"]
            duedate = issue["fields"].get("duedate")

            if category == "In Progress":
                in_progress.append(f"  • `{key}` {summary}")

            if duedate:
                due = date.fromisoformat(duedate)
                days_left = (due - today).days
                if days_left < 0:
                    days_str = f":rotating_light: *{abs(days_left)} napja lejárt!*"
                elif days_left == 0:
                    days_str = ":warning: *ma!*"
                else:
                    days_str = f"{days_left} nap múlva"
                with_deadline.append(f"  • `{key}` {summary} — határidő: {duedate} ({days_str})")

        if in_progress:
            lines.append("")
            lines.append("*In Progress feladatok:*")
            lines.extend(in_progress)
        if with_deadline:
            lines.append("")
            lines.append("*Határidős feladatok:*")
            lines.extend(with_deadline)

    lines.append("")
    lines.append("Kérlek pótold a hiányzó órákat! :pray:")

    return "\n".join(lines)


def send_slack_dm(slack_client, slack_user_id, message, dry_run=False):
    """Send a direct message to a Slack user."""
    if dry_run:
        print(f"  [DRY RUN] Would send DM to Slack user {slack_user_id}")
        print(f"  Message:\n{message}\n")
        return

    try:
        # Open a DM channel
        response = slack_client.conversations_open(users=[slack_user_id])
        channel_id = response["channel"]["id"]

        # Send message
        slack_client.chat_postMessage(channel=channel_id, text=message)
        print(f"  Sent DM to Slack user {slack_user_id}")
    except SlackApiError as e:
        print(f"  Error sending DM to {slack_user_id}: {e.response['error']}")


def main():
    parser = argparse.ArgumentParser(description="Jira Worklog Tracker")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages instead of sending Slack DMs",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to check (YYYY-MM-DD format, defaults to today)",
    )
    args = parser.parse_args()

    # Config from environment
    jira_base_url = get_env("JIRA_BASE_URL").rstrip("/")
    jira_email = get_env("JIRA_EMAIL")
    jira_api_token = get_env("JIRA_API_TOKEN")
    slack_bot_token = get_env("SLACK_BOT_TOKEN")
    user_mapping_json = get_env("USER_MAPPING")

    try:
        user_mapping = json.loads(user_mapping_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing USER_MAPPING JSON: {e}")
        sys.exit(1)

    # Target date
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Project blacklist (optional, comma-separated)
    blacklist_str = os.environ.get("PROJECT_BLACKLIST", "")
    blacklisted_projects = [p.strip() for p in blacklist_str.split(",") if p.strip()] if blacklist_str else []
    if blacklisted_projects:
        print(f"Blacklisted projects: {', '.join(blacklisted_projects)}")

    print(f"Checking worklogs for {date_str}...")

    # Fetch worklogs from Jira
    people = get_jira_worklogs(jira_base_url, jira_email, jira_api_token, date_str, blacklisted_projects)

    print(f"\nFound {len(people)} people with worklogs:")
    for account_id, data in people.items():
        print(f"  {data['name']}: {format_hours(data['total_seconds'])}")

    # Initialize Slack client
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    slack_client = WebClient(token=slack_bot_token, ssl=ssl_context)

    # Check each mapped user
    notified = 0
    skipped = 0

    for jira_id, slack_id in user_mapping.items():
        person = people.get(jira_id)
        total_seconds = person["total_seconds"] if person else 0

        if total_seconds >= 8 * 3600:
            name = person["name"] if person else jira_id
            print(f"\n{name}: {format_hours(total_seconds)} - OK")
            skipped += 1
            continue

        # Less than 8 hours - send notification
        active_issues = get_active_issues(jira_base_url, jira_email, jira_api_token, jira_id, blacklisted_projects)
        if person:
            name = person["name"]
            message = build_slack_message(person, date_str, active_issues)
        else:
            name = jira_id
            person_data = {"total_seconds": 0, "tickets": {}}
            message = build_slack_message(person_data, date_str, active_issues)

        print(f"\n{name}: {format_hours(total_seconds)} - UNDER 8h")
        send_slack_dm(slack_client, slack_id, message, dry_run=args.dry_run)
        notified += 1

    print(f"\nDone! Notified: {notified}, OK: {skipped}")


if __name__ == "__main__":
    main()
