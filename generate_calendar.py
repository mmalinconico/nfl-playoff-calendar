import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVENTS_FILE = Path("data/events.json")
CALENDAR_FILE = Path("nfl-playoffs.ics")


def escape_ical_text(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold_ical_line(line):
    folded = []
    current = ""
    current_length = 0

    for character in line:
        character_length = len(
            character.encode("utf-8")
        )

        if (
            current
            and current_length + character_length > 75
        ):
            folded.append(current)
            current = f" {character}"
            current_length = 1 + character_length
        else:
            current += character
            current_length += character_length

    folded.append(current)
    return "\r\n".join(folded)


def parse_timed_datetime(date_text):
    parsed = datetime.fromisoformat(
        str(date_text).replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def format_utc_datetime(value):
    return value.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def validate_event(item):
    for field in (
        "id",
        "name",
        "date",
        "uid",
        "dtstamp",
    ):
        if not item.get(field):
            raise ValueError(
                f"Event is missing required field '{field}': {item}"
            )

    if not re.fullmatch(
        r"\d{8}T\d{6}Z",
        item["dtstamp"],
    ):
        raise ValueError(
            f"Invalid DTSTAMP for {item['name']}: "
            f"{item['dtstamp']}"
        )

    if item.get("all_day"):
        datetime.strptime(
            item["date"],
            "%Y-%m-%d",
        )
    else:
        parse_timed_datetime(item["date"])


def serialize_event(item):
    validate_event(item)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{item['uid']}",
        f"DTSTAMP:{item['dtstamp']}",
    ]

    if item.get("all_day"):
        start_date = datetime.strptime(
            item["date"],
            "%Y-%m-%d",
        ).date()
        end_date = start_date + timedelta(days=1)

        lines.extend([
            "DTSTART;VALUE=DATE:"
            f"{start_date.strftime('%Y%m%d')}",
            "DTEND;VALUE=DATE:"
            f"{end_date.strftime('%Y%m%d')}",
        ])
    else:
        start = parse_timed_datetime(item["date"])
        end = start + timedelta(hours=4)

        lines.extend([
            f"DTSTART:{format_utc_datetime(start)}",
            f"DTEND:{format_utc_datetime(end)}",
        ])

    lines.append(
        f"SUMMARY:{escape_ical_text(item['name'])}"
    )

    description = []

    if item.get("network"):
        description.append(
            f"Network: {item['network']}"
        )

    if item.get("status"):
        description.append(item["status"])

    if description:
        lines.append(
            "DESCRIPTION:"
            + escape_ical_text("\n".join(description))
        )

    location_parts = [
        value
        for value in (
            item.get("venue", ""),
            item.get("city", ""),
        )
        if value
    ]

    if location_parts:
        lines.append(
            "LOCATION:"
            + escape_ical_text(
                ", ".join(location_parts)
            )
        )

    lines.append("END:VEVENT")
    return lines


def event_sort_key(item):
    if item.get("all_day"):
        return (
            item["date"],
            0,
            item.get("id", ""),
        )

    parsed = parse_timed_datetime(item["date"])

    return (
        parsed.astimezone(timezone.utc).isoformat(),
        1,
        item.get("id", ""),
    )


def write_calendar_atomically(lines):
    temporary_file = CALENDAR_FILE.with_suffix(
        ".ics.tmp"
    )

    content = "\r\n".join(
        fold_ical_line(line)
        for line in lines
    ) + "\r\n"

    temporary_file.write_bytes(
        content.encode("utf-8")
    )
    temporary_file.replace(CALENDAR_FILE)


def main():
    with EVENTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        events = json.load(file)

    if not isinstance(events, list):
        raise ValueError(
            "data/events.json must contain a list of events"
        )

    events.sort(key=event_sort_key)
    seen_uids = set()

    calendar_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Matt Malinconico//NFL Playoff Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:NFL Playoff Calendar",
    ]

    for item in events:
        validate_event(item)
        uid = item["uid"]

        if uid in seen_uids:
            raise ValueError(
                f"Duplicate calendar UID detected: {uid}"
            )

        seen_uids.add(uid)
        calendar_lines.extend(
            serialize_event(item)
        )

    calendar_lines.append("END:VCALENDAR")
    write_calendar_atomically(calendar_lines)

    print(f"Generated calendar with {len(events)} events")


if __name__ == "__main__":
    main()
