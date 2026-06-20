import json
from datetime import datetime

import requests

events = []

current_year = datetime.utcnow().year

candidate_years = [
current_year,
current_year + 1
]

playoff_events_found = False

for season_year in candidate_years:

```
date_ranges = [
    f"{season_year + 1}0113-{season_year + 1}0119",
    f"{season_year + 1}0120-{season_year + 1}0126",
    f"{season_year + 1}0127-{season_year + 1}0202",
    f"{season_year + 1}0210-{season_year + 1}0216"
]

season_events = []

for date_range in date_ranges:

    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/football/nfl/scoreboard?dates={date_range}"
    )

    response = requests.get(url)
    response.raise_for_status()

    data = response.json()

    for event in data.get("events", []):

        date = event.get("date")

        competitions = event.get("competitions", [{}])
        competition = competitions[0]

        name = event.get("name", "NFL Playoff Game")

        notes = competition.get("notes", [])

        if (
            name == "TBD at TBD"
            and notes
            and "headline" in notes[0]
        ):
            name = notes[0]["headline"]

        venue = (
            competition.get("venue", {})
            .get("fullName", "")
        )

        city = (
            competition.get("venue", {})
            .get("address", {})
            .get("city", "")
        )

        broadcasts = event.get("broadcasts", [])
        network = ""

        if broadcasts:
            network = broadcasts[0].get("names", [""])[0]

        season_events.append({
            "id": event.get("id"),
            "name": name,
            "date": date,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL"
        })

if season_events:
    events = season_events
    playoff_events_found = True
    print(f"Using postseason for season {season_year}")
    break
```

events.sort(key=lambda x: x["date"])

with open("data/events.json", "w") as f:
json.dump(events, f, indent=2)

print(f"Generated {len(events)} events")
