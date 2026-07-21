import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

EVENTS_FILE = Path("data/events.json")
PAST_EVENT_RETENTION_DAYS = 7

HEADERS = {
    "User-Agent": "NFLPlayoffCalendarBot/1.0 (personal hobby calendar)"
}


def load_previous_events():
    if not EVENTS_FILE.exists():
        return []

    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not load previous events: {error}")

    return []


def parse_event_datetime(date_text):
    if not date_text:
        return None

    try:
        return datetime.fromisoformat(
            date_text.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


now = datetime.now(timezone.utc)
current_year = now.year

# NFL seasons begin in one calendar year and their playoffs
# occur in January and February of the following calendar year.
#
# January/February 2027 still belong to the 2026 NFL season.
if now.month in (1, 2):
    season_year = current_year - 1
else:
    season_year = current_year

postseason_year = season_year + 1

print(f"Using postseason for NFL season {season_year}")
print(f"Searching January-February {postseason_year}")

date_ranges = [
    f"{postseason_year}0113-{postseason_year}0119",
    f"{postseason_year}0120-{postseason_year}0126",
    f"{postseason_year}0127-{postseason_year}0202",
    f"{postseason_year}0210-{postseason_year}0216"
]

previous_events = load_previous_events()
events = []

seen_event_ids = set()

for date_range in date_ranges:
    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/football/nfl/scoreboard?dates={date_range}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()

    data = response.json()

    for event in data.get("events", []):
        event_id = event.get("id")

        if not event_id or event_id in seen_event_ids:
            continue

        date_text = event.get("date")

        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}

        name = event.get("name", "NFL Playoff Game")

        notes = competition.get("notes", [])

        if (
            name == "TBD at TBD"
            and notes
            and notes[0].get("headline")
        ):
            name = notes[0]["headline"]

        venue_data = competition.get("venue", {})

        venue = venue_data.get("fullName", "")

        city = (
            venue_data
            .get("address", {})
            .get("city", "")
        )

        broadcasts = competition.get("broadcasts", [])
        network = ""

        if broadcasts:
            names = broadcasts[0].get("names", [])

            if names:
                network = names[0]

        events.append({
            "id": event_id,
            "name": name,
            "date": date_text,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL"
        })

        seen_event_ids.add(event_id)

# -------------------
# Retain recently completed or temporarily missing games
# -------------------

retention_cutoff = now - timedelta(
    days=PAST_EVENT_RETENTION_DAYS
)

retained_count = 0

for previous_event in previous_events:
    event_id = previous_event.get("id")

    if not event_id or event_id in seen_event_ids:
        continue

    event_datetime = parse_event_datetime(
        previous_event.get("date")
    )

    if event_datetime is None:
        continue

    # Keep future events if ESPN temporarily omits them.
    # Keep completed events for seven days after kickoff.
    if event_datetime >= retention_cutoff:
        events.append(previous_event)
        seen_event_ids.add(event_id)
        retained_count += 1

events.sort(
    key=lambda event: (
        event.get("date", ""),
        event.get("id", "")
    )
)

EVENTS_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

with EVENTS_FILE.open(
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        events,
        f,
        indent=2,
        ensure_ascii=False
    )

print(f"Retained {retained_count} missing recent events")
print(f"Generated {len(events)} events")
