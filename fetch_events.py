import json
import requests

events = []

date_ranges = [
    "20270113-20270119",  # Wild Card
    "20270120-20270126",  # Divisional
    "20270127-20270202",  # Conference Championships
    "20270210-20270216"   # Super Bowl
]

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

        # Better event name
        name = event.get("name", "NFL Playoff Game")

        if name == "TBD at TBD":
            notes = competition.get("notes", [])
            if notes:
                name = notes[0].get("headline", name)

        # Venue
        venue = (
            competition.get("venue", {})
            .get("fullName", "")
        )

        city = (
            competition.get("venue", {})
            .get("address", {})
            .get("city", "")
        )

        # Network
        broadcasts = event.get("broadcasts", [])
        network = ""

        if broadcasts:
            network = broadcasts[0].get("names", [""])[0]

        events.append({
            "name": name,
            "date": date,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL"
        })

events.sort(key=lambda x: x["date"])

with open("data/events.json", "w") as f:
    json.dump(events, f, indent=2)

print(f"Generated {len(events)} events")
