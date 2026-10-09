"""Validate the published NFL calendar against its source JSON and iCalendar rules.

This is deliberately independent of generate_calendar.py, so a regression
in the generator cannot make its own validation pass.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from icalendar import Calendar


def validate(events_path=Path("data/events.json"), calendar_path=Path("nfl-playoffs.ics")):
    events = json.loads(Path(events_path).read_text(encoding="utf-8"))
    raw = Path(calendar_path).read_bytes()

    if not isinstance(events, list):
        raise ValueError("Expected a JSON array of calendar events")
    if not raw.startswith(b"BEGIN:VCALENDAR\r\n") or not raw.endswith(b"END:VCALENDAR\r\n"):
        raise ValueError("Calendar must have an RFC 5545 envelope with CRLF endings")
    if b"\n" in raw.replace(b"\r\n", b"") or b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("Calendar contains non-CRLF line endings")
    if any(len(line) > 75 for line in raw.split(b"\r\n")):
        raise ValueError("Calendar contains a line longer than 75 UTF-8 octets")

    calendar = Calendar.from_ical(raw)
    if str(calendar.get("VERSION")) != "2.0":
        raise ValueError("Calendar VERSION must be 2.0")
    if str(calendar.get("X-WR-CALNAME")) != "NFL Playoff Calendar":
        raise ValueError("Calendar name changed unexpectedly")

    components = [item for item in calendar.walk() if item.name == "VEVENT"]
    expected = {item["uid"]: item for item in events}
    actual = {str(item["UID"]): item for item in components}
    if len(expected) != len(events) or len(actual) != len(components):
        raise ValueError("Duplicate UID in JSON or ICS")
    if expected.keys() != actual.keys():
        raise ValueError("JSON and ICS event UIDs disagree")

    for uid, source in expected.items():
        item = actual[uid]
        if str(item.get("SUMMARY")) != source["name"]:
            raise ValueError(f"SUMMARY differs for {uid}")
        stamp = datetime.strptime(source["dtstamp"], "%Y%m%dT%H%M%SZ")
        if item.decoded("DTSTAMP").astimezone(timezone.utc).replace(tzinfo=None) != stamp:
            raise ValueError(f"DTSTAMP differs for {uid}")

        start = item.decoded("DTSTART")
        end = item.decoded("DTEND")
        if source.get("all_day"):
            if type(start) is not date or type(end) is not date:
                raise ValueError(f"All-day DTSTART/DTEND must be DATE for {uid}")
            if start.isoformat() != source["date"] or end - start != timedelta(days=1):
                raise ValueError(f"All-day dates are incorrect for {uid}")
        else:
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                raise ValueError(f"Timed DTSTART/DTEND must be DATE-TIME for {uid}")
            expected_start = datetime.fromisoformat(source["date"].replace("Z", "+00:00"))
            if start.astimezone(timezone.utc) != expected_start.astimezone(timezone.utc):
                raise ValueError(f"Timed kickoff differs for {uid}")
            if end - start != timedelta(hours=4):
                raise ValueError(f"Timed NFL games must last four hours for {uid}")

        notes = []
        if source.get("network"):
            notes.append("Network: " + source["network"])
        if source["id"].startswith("super-bowl-") and source.get("streaming"):
            notes.append("Streaming: " + source["streaming"])
        if source.get("status"):
            notes.append(source["status"])
        if str(item.get("DESCRIPTION", "")) != "\n".join(notes):
            raise ValueError(f"DESCRIPTION differs for {uid}")

        location = ", ".join(
            part for part in [source.get("venue", ""), source.get("city", "")] if part
        )
        if str(item.get("LOCATION", "")) != location:
            raise ValueError(f"LOCATION differs for {uid}")

        if source["id"].startswith("super-bowl-"):
            roman = source["id"].removeprefix("super-bowl-")
            if uid != f"super-bowl-{roman}@nfl-playoff-calendar":
                raise ValueError(f"Unstable Super Bowl UID: {uid}")

    return len(events)


if __name__ == "__main__":
    try:
        count = validate()
    except (ValueError, KeyError, TypeError) as error:
        print(f"Calendar validation FAILED: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"Calendar validation PASS: {count} events; RFC-style line folding, CRLF, "
          "unique UIDs, dates, four-hour duration, metadata and JSON/ICS parity")
