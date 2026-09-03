import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

EVENTS_FILE = Path("data/events.json")
PAST_EVENT_RETENTION_DAYS = 7
CALENDAR_TIMEZONE = ZoneInfo("America/New_York")
POSTSEASON_SEASON_TYPE = 3
POSTSEASON_WEEKS = (1, 2, 3, 4)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
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


def core_get_json(url, params=None, label="ESPN Core API"):
    response = requests.get(
        str(url).replace("http://", "https://"),
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError(
            f"{label} returned invalid JSON."
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{label} returned an unexpected response."
        )

    return data


def core_collection_items(url, params=None, label="ESPN Core API"):
    data = core_get_json(
        url,
        params=params,
        label=label,
    )

    items = data.get("items")

    if not isinstance(items, list):
        raise RuntimeError(
            f"{label} response is missing an items list."
        )

    return items


def resolve_ref(value, label):
    if not isinstance(value, dict):
        return {}

    ref = value.get("$ref")

    if not ref:
        return value

    return core_get_json(ref, label=label)


def core_event_id_from_ref(item):
    if not isinstance(item, dict):
        return ""

    event_id = normalize_id(item.get("id"))

    if event_id:
        return event_id

    ref = str(item.get("$ref", ""))
    match = re.search(r"/events/([^/?]+)", ref)

    if match:
        return normalize_id(match.group(1))

    return ""


def previous_event_for_espn_id(previous_events, espn_id):
    espn_id = normalize_id(espn_id)

    for event in previous_events:
        previous_id = normalize_id(event.get("id"))
        previous_espn_id = normalize_id(
            event.get("espn_id")
            or (
                previous_id
                if previous_id.isdigit()
                else ""
            )
        )

        if previous_espn_id == espn_id:
            return event

    return None


def fetch_core_postseason_event_refs(season_year):
    base = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/seasons/"
        f"{season_year}/types/{POSTSEASON_SEASON_TYPE}/weeks"
    )

    collected = []
    seen_ids = set()

    for week in POSTSEASON_WEEKS:
        url = f"{base}/{week}/events"
        items = core_collection_items(
            url,
            params={"limit": 100},
            label=f"ESPN Core postseason week {week}",
        )

        print(
            f"ESPN Core postseason week {week}: "
            f"{len(items)} event references"
        )

        for item in items:
            event_id = core_event_id_from_ref(item)

            if not event_id or event_id in seen_ids:
                continue

            collected.append({
                "week": week,
                "id": event_id,
                "$ref": item.get(
                    "$ref",
                    (
                        "https://sports.core.api.espn.com/v2/"
                        "sports/football/leagues/nfl/events/"
                        f"{event_id}"
                    ),
                ),
            })
            seen_ids.add(event_id)

    return collected


def core_competition_for_event(event_id):
    url = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/events/"
        f"{event_id}/competitions/{event_id}"
    )

    return core_get_json(
        url,
        label=f"ESPN Core competition {event_id}",
    )


def core_broadcast_networks(event_id):
    url = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/events/"
        f"{event_id}/competitions/{event_id}/broadcasts"
    )

    try:
        items = core_collection_items(
            url,
            params={"limit": 100},
            label=f"ESPN Core broadcasts {event_id}",
        )
    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status == 404:
            return ""

        raise

    names = []

    for item in items:
        broadcast = resolve_ref(
            item,
            f"ESPN Core broadcast {event_id}",
        )

        candidates = []

        if isinstance(broadcast.get("names"), list):
            candidates.extend(broadcast["names"])

        for key in (
            "name",
            "shortName",
            "displayName",
            "shortDisplayName",
        ):
            if broadcast.get(key):
                candidates.append(broadcast[key])

        media = broadcast.get("media")

        if isinstance(media, dict):
            for key in (
                "shortName",
                "name",
                "displayName",
            ):
                if media.get(key):
                    candidates.append(media[key])

        for candidate in candidates:
            cleaned = str(candidate).strip()

            if cleaned and cleaned not in names:
                names.append(cleaned)

    return " / ".join(names)


def core_venue_details(competition):
    venue_value = competition.get("venue")

    if not isinstance(venue_value, dict):
        return "", ""

    try:
        venue = resolve_ref(
            venue_value,
            "ESPN Core venue",
        )
    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status == 404:
            venue = venue_value
        else:
            raise

    venue_name = str(
        venue.get("fullName")
        or venue.get("name")
        or ""
    ).strip()

    city = ""
    address = venue.get("address")

    if isinstance(address, dict):
        city = str(
            address.get("city")
            or address.get("summary")
            or ""
        ).strip()

    return venue_name, city


def core_placeholder_time(
    event_datetime,
    event_detail,
    competition,
):
    if event_datetime is None:
        return False

    for source in (competition, event_detail):
        if source.get("timeValid") is False:
            return True

    local_datetime = event_datetime.astimezone(
        CALENDAR_TIMEZONE
    )

    return (
        local_datetime.hour == 0
        and local_datetime.minute == 0
        and local_datetime.second == 0
    )


def sensible_core_name(
    event_detail,
    previous_event,
    week,
    current_super_bowl_roman,
):
    candidates = [
        event_detail.get("name", ""),
        event_detail.get("shortName", ""),
    ]

    for candidate in candidates:
        cleaned = str(candidate).strip()

        if cleaned and cleaned.lower() not in {
            "tbd at tbd",
            "tbd @ tbd",
            "tbd vs tbd",
            "tbd",
        }:
            return cleaned

    if previous_event and previous_event.get("name"):
        return previous_event["name"]

    if week == 1:
        return "Wild Card Playoffs"

    if week == 2:
        return "Divisional Playoffs"

    if week == 3:
        return "Conference Championship"

    if week == 4 and current_super_bowl_roman:
        return f"Super Bowl {current_super_bowl_roman}"

    return "NFL Playoff Game"


def fetch_core_postseason_events(
    season_year,
    previous_events,
    current_super_bowl_roman,
    current_official_super_bowl,
):
    event_refs = fetch_core_postseason_event_refs(
        season_year
    )
    events = []

    for item in event_refs:
        espn_event_id = item["id"]
        week = item["week"]
        event_detail = core_get_json(
            item["$ref"],
            label=f"ESPN Core event {espn_event_id}",
        )
        competition = core_competition_for_event(
            espn_event_id
        )
        previous = previous_event_for_espn_id(
            previous_events,
            espn_event_id,
        )

        date_text = str(
            event_detail.get("date")
            or competition.get("date")
            or ""
        )
        event_datetime = parse_event_datetime(
            date_text
        )

        if event_datetime is None:
            raise RuntimeError(
                "ESPN Core event has an invalid date: "
                f"{espn_event_id}"
            )

        local_date = event_datetime.astimezone(
            CALENDAR_TIMEZONE
        ).date().isoformat()

        matches_official_super_bowl_date = (
            current_official_super_bowl is not None
            and local_date
            == current_official_super_bowl["date"]
        )

        is_super_bowl = (
            week == 4
            or (
                current_super_bowl_roman
                and matches_official_super_bowl_date
            )
        )

        event_id = espn_event_id
        event_uid = ""

        if is_super_bowl and current_super_bowl_roman:
            event_id = super_bowl_event_id(
                current_super_bowl_roman
            )
            event_uid = super_bowl_uid(
                current_super_bowl_roman
            )

        venue, city = core_venue_details(
            competition
        )
        network = core_broadcast_networks(
            espn_event_id
        )

        if previous is not None:
            if not venue:
                venue = previous.get("venue", "")

            if not city:
                city = previous.get("city", "")

            if not network:
                network = previous.get("network", "")

        all_day = core_placeholder_time(
            event_datetime,
            event_detail,
            competition,
        )

        if all_day:
            stored_date = local_date
        else:
            stored_date = date_text

        name = sensible_core_name(
            event_detail,
            previous,
            week,
            current_super_bowl_roman,
        )

        calendar_event = {
            "id": event_id,
            "name": name,
            "date": stored_date,
            "venue": venue,
            "city": city,
            "network": network,
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

    return events


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
    events = fetch_core_postseason_events(
        season_year,
        previous_events,
        current_super_bowl_roman,
        current_official_super_bowl,
    )

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