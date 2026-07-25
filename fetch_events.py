import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

EVENTS_FILE = Path("data/events.json")
PAST_EVENT_RETENTION_DAYS = 7

HEADERS = {
    "User-Agent": "NFLPlayoffCalendarBot/1.0 (personal hobby calendar)"
}

# Add a future Super Bowl here only after an official source publishes
# the exact calendar date. Never infer the date from the usual NFL schedule.
OFFICIAL_FUTURE_SUPER_BOWLS = [
    {
        "roman": "LXI",
        "date": "2027-02-14",
        "venue": "SoFi Stadium",
        "city": "Inglewood, California",
        "network": "TBA",
        "source_url": (
            "https://operations.nfl.com/"
            "calendar-events/nfl-important-dates"
        ),
    },
    {
        "roman": "LXII",
        "date": "2028-02-13",
        "venue": "Mercedes-Benz Stadium",
        "city": "Atlanta, Georgia",
        "network": "TBA",
        "source_url": (
            "https://www.mercedesbenzstadium.com/"
            "events/super-bowl-lxii"
        ),
    },
]


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
        parsed = datetime.fromisoformat(
            date_text.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except (TypeError, ValueError):
        return None


def integer_to_roman(number):
    values = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]

    result = []

    for value, numeral in values:
        while number >= value:
            result.append(numeral)
            number -= value

    return "".join(result)


def super_bowl_roman_for_year(postseason_year):
    # Super Bowl I was played in 1967.
    super_bowl_number = postseason_year - 1966

    if super_bowl_number < 1:
        return None

    return integer_to_roman(super_bowl_number)


def is_super_bowl_event(event, competition):
    labels = [
        event.get("name", ""),
        event.get("shortName", ""),
    ]

    for note in competition.get("notes", []):
        if isinstance(note, dict):
            labels.append(note.get("headline", ""))

    return any(
        "super bowl" in label.lower()
        for label in labels
        if isinstance(label, str)
    )


def super_bowl_event_id(roman):
    return f"super-bowl-{roman.lower()}"


def super_bowl_uid(roman):
    return f"super-bowl-{roman.lower()}@nfl-playoff-calendar"


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
current_super_bowl_roman = super_bowl_roman_for_year(
    postseason_year
)
current_official_super_bowl = next(
    (
        item
        for item in OFFICIAL_FUTURE_SUPER_BOWLS
        if item["roman"] == current_super_bowl_roman
    ),
    None,
)

print(f"Using postseason for NFL season {season_year}")
print(f"Searching January-February {postseason_year}")

# These ranges cover the Wild Card, Divisional, Conference
# Championship, and Super Bowl windows for the active postseason.
date_ranges = [
    f"{postseason_year}0113-{postseason_year}0119",
    f"{postseason_year}0120-{postseason_year}0126",
    f"{postseason_year}0127-{postseason_year}0202",
    f"{postseason_year}0210-{postseason_year}0216",
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
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    for event in data.get("events", []):
        espn_event_id = event.get("id")

        if not espn_event_id:
            continue

        date_text = event.get("date")

        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}

        notes = competition.get("notes", [])
        name = event.get("name", "NFL Playoff Game")

        if (
            name == "TBD at TBD"
            and notes
            and isinstance(notes[0], dict)
            and notes[0].get("headline")
        ):
            name = notes[0]["headline"]

        event_id = espn_event_id
        event_uid = ""

        event_calendar_date = parse_event_datetime(date_text)
        matches_official_super_bowl_date = (
            current_official_super_bowl is not None
            and event_calendar_date is not None
            and event_calendar_date.date().isoformat()
            == current_official_super_bowl["date"]
        )

        if (
            current_super_bowl_roman
            and (
                is_super_bowl_event(event, competition)
                or matches_official_super_bowl_date
            )
        ):
            event_id = super_bowl_event_id(
                current_super_bowl_roman
            )
            event_uid = super_bowl_uid(
                current_super_bowl_roman
            )

        if event_id in seen_event_ids:
            continue

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

        calendar_event = {
            "id": event_id,
            "name": name,
            "date": date_text,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL",
            "source": "espn",
            "espn_id": espn_event_id,
        }

        if event_uid:
            calendar_event["uid"] = event_uid

        events.append(calendar_event)
        seen_event_ids.add(event_id)

# -------------------
# Retain recently completed or temporarily missing ESPN games
# -------------------

retention_cutoff = now - timedelta(
    days=PAST_EVENT_RETENTION_DAYS
)

retained_count = 0

for previous_event in previous_events:
    event_id = previous_event.get("id")

    if not event_id or event_id in seen_event_ids:
        continue

    # Official future placeholders are regenerated from the audited list
    # below. Do not retain a stale placeholder if its date is corrected
    # or the entry is removed from that list.
    if previous_event.get("source") == "official-future-super-bowl":
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

# -------------------
# Add officially dated future Super Bowls not yet supplied by ESPN
# -------------------

placeholder_count = 0

for super_bowl in OFFICIAL_FUTURE_SUPER_BOWLS:
    roman = super_bowl["roman"]
    event_id = super_bowl_event_id(roman)

    if event_id in seen_event_ids:
        continue

    event_date = datetime.strptime(
        super_bowl["date"],
        "%Y-%m-%d",
    ).date()

    if event_date < now.date():
        continue

    events.append({
        "id": event_id,
        "uid": super_bowl_uid(roman),
        "name": f"Super Bowl {roman}",
        "date": super_bowl["date"],
        "venue": super_bowl["venue"],
        "city": super_bowl["city"],
        "network": super_bowl.get("network", "TBA"),
        "promotion": "NFL",
        "all_day": True,
        "status": "Kickoff time TBA",
        "source": "official-future-super-bowl",
        "source_url": super_bowl["source_url"],
    })

    seen_event_ids.add(event_id)
    placeholder_count += 1

events.sort(
    key=lambda event: (
        event.get("date", ""),
        event.get("id", ""),
    )
)

EVENTS_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with EVENTS_FILE.open(
    "w",
    encoding="utf-8",
) as f:
    json.dump(
        events,
        f,
        indent=2,
        ensure_ascii=False,
    )

print(f"Retained {retained_count} missing recent events")
print(f"Added {placeholder_count} official future Super Bowls")
print(f"Generated {len(events)} events")
