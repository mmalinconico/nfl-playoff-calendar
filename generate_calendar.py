import json
import re
from datetime import datetime, timedelta

from ics import Calendar, Event

calendar = Calendar()

with open("data/events.json", "r") as f:
    events = json.load(f)

for item in events:

    event = Event()

    event.name = item["name"]

    start = datetime.fromisoformat(
        item["date"].replace("Z", "+00:00")
    )

    end = start + timedelta(hours=4)

    event.begin = start
    event.end = end

    # Stable UID
    uid_name = re.sub(
        r"[^a-z0-9]+",
        "-",
        item["name"].lower()
    ).strip("-")

    event.uid = (
        f"{uid_name}-"
        f"{start.strftime('%Y%m%dT%H%M')}"
    )

    # Location
    location_parts = []

    if item["venue"]:
        location_parts.append(item["venue"])

    if item["city"]:
        location_parts.append(item["city"])

    event.location = ", ".join(location_parts)

    # Description
    description = []

    if item["network"]:
        description.append(
            f"Network: {item['network']}"
        )

    event.description = "\n".join(description)

    calendar.events.add(event)

with open("nfl-playoffs.ics", "w") as f:
    f.writelines(calendar)

print(
    f"Generated calendar with {len(events)} events"
)
