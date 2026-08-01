import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

EVENTS_FILE = Path("data/events.json")
PAST_EVENT_RETENTION_DAYS = 7
CALENDAR_TIMEZONE = ZoneInfo("America/New_York")
REQUEST_WINDOW_DAYS = 14

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

CALENDAR_FIELDS = (
    "name",
    "date",
    "all_day",
    "venue",
    "city",
    "network",
    "status",
)


def calendar_today():
    return datetime.now(CALENDAR_TIMEZONE).date()


def normalize_id(value):
    if value is None:
        return ""

    return str(value)


def slugify(value):
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value).lower(),
    ).strip("-")

    return slug or "unknown"


def load_previous_events():
    if not EVENTS_FILE.exists():
        return []

    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

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
            str(date_text).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except (TypeError, ValueError):
        return None


def event_calendar_date(event):
    date_text = event.get("date", "")

    if event.get("all_day"):
        try:
            return datetime.strptime(
                date_text,
                "%Y-%m-%d",
            ).date()
        except (TypeError, ValueError):
            return None

    event_datetime = parse_event_datetime(date_text)

    if event_datetime is None:
        return None

    return event_datetime.astimezone(
        CALENDAR_TIMEZONE
    ).date()


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


def super_bowl_event_id(roman):
    return f"super-bowl-{roman.lower()}"


def super_bowl_uid(roman):
    return f"super-bowl-{roman.lower()}@nfl-playoff-calendar"


def event_labels(event, competition):
    labels = [
        event.get("name", ""),
        event.get("shortName", ""),
    ]

    status = event.get("status", {})

    if isinstance(status, dict):
        status_type = status.get("type", {})

        if isinstance(status_type, dict):
            labels.extend([
                status_type.get("description", ""),
                status_type.get("detail", ""),
                status_type.get("shortDetail", ""),
            ])

    for note in competition.get("notes", []):
        if isinstance(note, dict):
            labels.append(note.get("headline", ""))

    return [
        str(label).strip()
        for label in labels
        if label
    ]


def is_super_bowl_event(event, competition):
    return any(
        "super bowl" in label.lower()
        for label in event_labels(event, competition)
    )


def is_postseason_event(event, competition):
    labels = " ".join(
        event_labels(event, competition)
    ).lower()

    if "pro bowl" in labels:
        return False

    season = event.get("season", {})
    season_type = season.get("type") if isinstance(season, dict) else None
    season_slug = (
        str(season.get("slug", "")).lower()
        if isinstance(season, dict)
        else ""
    )

    if season_type == 3 or "post" in season_slug:
        return True

    postseason_terms = (
        "wild card",
        "divisional",
        "afc championship",
        "nfc championship",
        "conference championship",
        "super bowl",
        "playoff",
    )

    return any(term in labels for term in postseason_terms)


def network_names(competition):
    names = []

    for broadcast in competition.get("broadcasts", []):
        if not isinstance(broadcast, dict):
            continue

        for name in broadcast.get("names", []):
            cleaned = str(name).strip()

            if cleaned and cleaned not in names:
                names.append(cleaned)

    return " / ".join(names)


def is_placeholder_time(event_datetime, competition):
    if event_datetime is None:
        return False

    if competition.get("timeValid") is False:
        return True

    local_datetime = event_datetime.astimezone(
        CALENDAR_TIMEZONE
    )

    # ESPN commonly uses midnight Eastern when a date is known but
    # a kickoff time has not been announced. NFL playoff games do not
    # actually begin at midnight Eastern.
    return (
        local_datetime.hour == 0
        and local_datetime.minute == 0
        and local_datetime.second == 0
    )


def build_date_ranges(postseason_year):
    start = date(postseason_year, 1, 1)
    end = date(postseason_year, 3, 31)
    ranges = []
    window_start = start

    while window_start <= end:
        window_end = min(
            window_start + timedelta(
                days=REQUEST_WINDOW_DAYS - 1
            ),
            end,
        )

        ranges.append(
            f"{window_start.strftime('%Y%m%d')}-"
            f"{window_end.strftime('%Y%m%d')}"
        )

        window_start = window_end + timedelta(days=1)

    return ranges


def fetch_scoreboard(date_range):
    url = (
        "https://site.api.espn.com/apis/site/v2/"
        "sports/football/nfl/scoreboard"
    )

    response = requests.get(
        url,
        params={"dates": date_range},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            f"ESPN returned an unexpected response for {date_range}."
        )

    if "events" not in data or not isinstance(data["events"], list):
        raise RuntimeError(
            f"ESPN response is missing an events list for {date_range}."
        )

    return data["events"]


def legacy_uid_for_event(event):
    if event.get("uid"):
        return event["uid"]

    if str(event.get("id", "")).startswith("super-bowl-"):
        roman = str(event["id"]).removeprefix(
            "super-bowl-"
        )
        return super_bowl_uid(roman)

    return (
        f"{slugify(event.get('name', 'NFL Playoff Game'))}-"
        f"{normalize_id(event.get('id'))}"
    )


def new_uid_for_event(event):
    if event.get("uid"):
        return event["uid"]

    event_id = normalize_id(event.get("id"))

    if event_id.startswith("super-bowl-"):
        roman = event_id.removeprefix("super-bowl-")
        return super_bowl_uid(roman)

    espn_id = normalize_id(
        event.get("espn_id") or event_id
    )

    return f"nfl-{espn_id}@nfl-playoff-calendar"


def calendar_data_changed(current_event, previous_event):
    return any(
        current_event.get(field, "")
        != previous_event.get(field, "")
        for field in CALENDAR_FIELDS
    )


def previous_event_indexes(previous_events):
    by_id = {}
    by_espn_id = {}

    for event in previous_events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(
            event.get("espn_id")
            or (
                event_id
                if event_id.isdigit()
                else ""
            )
        )

        if event_id:
            by_id[event_id] = event

        if espn_id:
            by_espn_id[espn_id] = event

    return by_id, by_espn_id


def assign_stable_metadata(events, previous_events):
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    by_id, by_espn_id = previous_event_indexes(
        previous_events
    )

    for event in events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(event.get("espn_id"))

        previous = by_id.get(event_id)

        if previous is None and espn_id:
            previous = by_espn_id.get(espn_id)

        if previous is not None:
            event["uid"] = (
                previous.get("uid")
                or legacy_uid_for_event(previous)
            )

            if (
                previous.get("dtstamp")
                and not calendar_data_changed(event, previous)
            ):
                event["dtstamp"] = previous["dtstamp"]
            else:
                event["dtstamp"] = timestamp
        else:
            event["uid"] = new_uid_for_event(event)
            event["dtstamp"] = timestamp


def validate_espn_result(events, previous_events, postseason_year):
    previous_future = [
        event
        for event in previous_events
        if event.get("source") == "espn"
        and (
            event_calendar_date(event) or date.min
        ) >= calendar_today()
        and str(postseason_year) in event.get("date", "")
    ]

    parsed_future = [
        event
        for event in events
        if event.get("source") == "espn"
        and (
            event_calendar_date(event) or date.min
        ) >= calendar_today()
    ]

    if previous_future and not parsed_future:
        raise RuntimeError(
            "ESPN returned no future postseason events while "
            f"{len(previous_future)} were previously stored. "
            "Aborting to prevent an accidental calendar wipe."
        )


def deduplicate_events(events):
    unique = []
    seen_ids = set()
    seen_espn_ids = set()

    for event in events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(event.get("espn_id"))

        if not event_id:
            continue

        if event_id in seen_ids:
            continue

        if espn_id and espn_id in seen_espn_ids:
            continue

        unique.append(event)
        seen_ids.add(event_id)

        if espn_id:
            seen_espn_ids.add(espn_id)

    return unique


def filter_events_by_retention(events):
    retention_start = calendar_today() - timedelta(
        days=PAST_EVENT_RETENTION_DAYS
    )
    kept = []
    removed_count = 0

    for event in events:
        event_date = event_calendar_date(event)

        if event_date is None:
            raise RuntimeError(
                "Invalid event date for "
                f"{event.get('name', 'unknown event')}: "
                f"{event.get('date', '')}"
            )

        if event_date < retention_start:
            removed_count += 1
            continue

        kept.append(event)

    return kept, removed_count


def retain_temporarily_missing_events(
    events,
    previous_events,
):
    retention_start = calendar_today() - timedelta(
        days=PAST_EVENT_RETENTION_DAYS
    )
    current_ids = {
        normalize_id(event.get("id"))
        for event in events
    }
    current_espn_ids = {
        normalize_id(event.get("espn_id"))
        for event in events
        if event.get("espn_id")
    }
    retained_count = 0

    for previous in previous_events:
        if previous.get("source") != "espn":
            continue

        event_id = normalize_id(previous.get("id"))
        espn_id = normalize_id(
            previous.get("espn_id")
            or (
                event_id
                if event_id.isdigit()
                else ""
            )
        )

        if event_id in current_ids:
            continue

        if espn_id and espn_id in current_espn_ids:
            continue

        previous_date = event_calendar_date(previous)

        if previous_date is None:
            continue

        if previous_date < retention_start:
            continue

        events.append(dict(previous))
        current_ids.add(event_id)

        if espn_id:
            current_espn_ids.add(espn_id)

        retained_count += 1

    return retained_count


def write_events_atomically(events):
    EVENTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_file = EVENTS_FILE.with_suffix(
        ".json.tmp"
    )

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            events,
            file,
            indent=2,
            ensure_ascii=False,
        )
        file.write("\n")

    temporary_file.replace(EVENTS_FILE)


def main():
    now = datetime.now(CALENDAR_TIMEZONE)
    current_year = now.year

    # Keep following the prior NFL season through March. This avoids
    # assuming the postseason must always end in February.
    if now.month <= 3:
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
    print(
        "Searching January-March "
        f"{postseason_year}"
    )

    previous_events = load_previous_events()
    events = []
    seen_raw_espn_ids = set()

    for date_range in build_date_ranges(
        postseason_year
    ):
        for raw_event in fetch_scoreboard(date_range):
            espn_event_id = normalize_id(
                raw_event.get("id")
            )

            if not espn_event_id:
                continue

            if espn_event_id in seen_raw_espn_ids:
                continue

            competitions = raw_event.get(
                "competitions",
                [],
            )
            competition = (
                competitions[0]
                if competitions
                and isinstance(competitions[0], dict)
                else {}
            )

            if not is_postseason_event(
                raw_event,
                competition,
            ):
                continue

            seen_raw_espn_ids.add(espn_event_id)

            date_text = raw_event.get("date", "")
            event_datetime = parse_event_datetime(
                date_text
            )

            if event_datetime is None:
                raise RuntimeError(
                    "ESPN event has an invalid date: "
                    f"{espn_event_id}"
                )

            name = raw_event.get(
                "name",
                "NFL Playoff Game",
            )
            notes = competition.get("notes", [])

            if name == "TBD at TBD":
                for note in notes:
                    if (
                        isinstance(note, dict)
                        and note.get("headline")
                    ):
                        name = note["headline"]
                        break

            event_id = espn_event_id
            event_uid = ""

            matches_official_super_bowl_date = (
                current_official_super_bowl is not None
                and event_datetime.astimezone(
                    CALENDAR_TIMEZONE
                ).date().isoformat()
                == current_official_super_bowl["date"]
            )

            if (
                current_super_bowl_roman
                and (
                    is_super_bowl_event(
                        raw_event,
                        competition,
                    )
                    or matches_official_super_bowl_date
                )
            ):
                event_id = super_bowl_event_id(
                    current_super_bowl_roman
                )
                event_uid = super_bowl_uid(
                    current_super_bowl_roman
                )

            venue_data = competition.get(
                "venue",
                {},
            )
            venue = (
                venue_data.get("fullName", "")
                if isinstance(venue_data, dict)
                else ""
            )
            city = ""

            if isinstance(venue_data, dict):
                address = venue_data.get("address", {})

                if isinstance(address, dict):
                    city = address.get("city", "")

            all_day = is_placeholder_time(
                event_datetime,
                competition,
            )

            if all_day:
                stored_date = event_datetime.astimezone(
                    CALENDAR_TIMEZONE
                ).date().isoformat()
            else:
                stored_date = date_text

            calendar_event = {
                "id": event_id,
                "name": name,
                "date": stored_date,
                "venue": venue,
                "city": city,
                "network": network_names(competition),
                "promotion": "NFL",
                "source": "espn",
                "espn_id": espn_event_id,
            }

            if all_day:
                calendar_event["all_day"] = True
                calendar_event["status"] = (
                    "Kickoff time TBA"
                )

            if event_uid:
                calendar_event["uid"] = event_uid

            events.append(calendar_event)

    events = deduplicate_events(events)
    validate_espn_result(
        events,
        previous_events,
        postseason_year,
    )

    retained_count = retain_temporarily_missing_events(
        events,
        previous_events,
    )

    placeholder_count = 0

    for super_bowl in OFFICIAL_FUTURE_SUPER_BOWLS:
        roman = super_bowl["roman"]
        event_id = super_bowl_event_id(roman)

        if any(
            event.get("id") == event_id
            for event in events
        ):
            continue

        event_date = datetime.strptime(
            super_bowl["date"],
            "%Y-%m-%d",
        ).date()

        if event_date < calendar_today():
            continue

        events.append({
            "id": event_id,
            "uid": super_bowl_uid(roman),
            "name": f"Super Bowl {roman}",
            "date": super_bowl["date"],
            "venue": super_bowl["venue"],
            "city": super_bowl["city"],
            "network": super_bowl.get(
                "network",
                "TBA",
            ),
            "promotion": "NFL",
            "all_day": True,
            "status": "Kickoff time TBA",
            "source": "official-future-super-bowl",
            "source_url": super_bowl["source_url"],
        })
        placeholder_count += 1

    events = deduplicate_events(events)
    events, removed_count = filter_events_by_retention(
        events
    )
    assign_stable_metadata(
        events,
        previous_events,
    )

    events.sort(
        key=lambda event: (
            event_calendar_date(event) or date.max,
            event.get("date", ""),
            event.get("id", ""),
        )
    )

    write_events_atomically(events)

    print(f"Retained {retained_count} temporarily missing events")
    print(f"Filtered {removed_count} events outside retention")
    print(f"Added {placeholder_count} official future Super Bowls")
    print(f"Generated {len(events)} events")


if __name__ == "__main__":
    main()
